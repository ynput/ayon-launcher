"""Qt Quick login dialog using the launcher's existing authentication API."""

import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

import ayon_api
from ayon_api.exceptions import UnauthorizedError, UrlError
from ayon_api.utils import (
    login_to_server,
    logout_from_server,
    validate_url,
)
from qtpy import QtCore, QtGui, QtQuickWidgets, QtWidgets

from ayon_common.resources import get_icon_path
from ayon_common.ui_utils import get_qt_app

from .server import LoginServerListener


REQUEST_TIMEOUT = 10
BROWSER_TIMEOUT = 180
# Pixel size of the avatar passed to QML (twice the displayed size)
AVATAR_SIZE = 96
# Server info keys, maximum pixel size and encoding of the studio images
STUDIO_IMAGES = {
    "logo": (("studioLogo", "loginPageBrand"), (572, 120), "PNG"),
    "background": (("loginPageBackground",), (1920, 1920), "JPG"),
}


def _normalize_url(url):
    """Normalize a url for comparison; its path stays case-sensitive."""
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    return parts._replace(
        scheme=parts.scheme.lower(), netloc=parts.netloc.lower()
    ).geturl()


class LoginError(Exception):
    """An authentication error that can be displayed to the user."""


def check_server(url):
    """Normalize the address and verify that it exposes an AYON API."""
    url = url.strip()
    if not url:
        raise LoginError("Enter your AYON server address.")
    if "://" not in url:
        url = "https://" + url
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise LoginError(
            "Use an HTTP or HTTPS server address without credentials,"
            " query parameters, or a fragment."
        )
    url = validate_url(url, timeout=REQUEST_TIMEOUT)
    api = ayon_api.ServerAPI(url, timeout=REQUEST_TIMEOUT, max_retries=0)
    version = api.server_version_tuple
    if len(version) < 3 or not all(
        isinstance(part, int) for part in version[:3]
    ):
        raise LoginError("This address did not return an AYON server version.")
    return url, tuple(version[:3]) >= (1, 3, 2)


def password_login(url, username, password):
    token = login_to_server(
        url, username, password, timeout=REQUEST_TIMEOUT
    )
    if not token:
        raise LoginError(
            "Unable to sign in. Check your username and password."
        )
    return url, token, username


def get_token_user(url, token):
    """Return the authenticated user, or None for an invalid token."""
    api = ayon_api.ServerAPI(
        url, token=token, timeout=REQUEST_TIMEOUT, max_retries=0
    )
    try:
        return api.get_user()
    except UnauthorizedError:
        return None


def get_token_username(url, token):
    """Return the authenticated username, or None for an invalid token."""
    user = get_token_user(url, token)
    return user.get("name") if user else None


def saved_login(url, token, expected_username):
    """Check supplied credentials; let network errors propagate for retry."""
    user = get_token_user(url, token)
    username = user.get("name") if user else None
    if not username or (expected_username and username != expected_username):
        return None
    return url, token, username, user


def _image_data_url(image, image_format="PNG"):
    """Encode an image so QML can show it without a network request."""
    data = QtCore.QByteArray()
    buffer = QtCore.QBuffer(data)
    buffer.open(QtCore.QIODevice.WriteOnly)
    saved = image.save(buffer, image_format)
    buffer.close()
    if not saved:
        return ""
    mime = "image/jpeg" if image_format == "JPG" else "image/png"
    return f"data:{mime};base64," + bytes(data.toBase64()).decode("ascii")


def fetch_studio_image(url, kind):
    """Return the studio logo or login background as a data URL, or ''."""
    keys, (width, height), image_format = STUDIO_IMAGES[kind]
    api = ayon_api.ServerAPI(url, timeout=REQUEST_TIMEOUT, max_retries=0)
    info = api.raw_get(
        "info", params={"full": "true"}, handle_invalid_token=False
    ).data
    path = next((info[key] for key in keys if info.get(key)), None)
    if not path:
        return ""
    base_url = api.get_base_url()
    image_url = urljoin(base_url + "/", path)
    # Only load images from the server the user is connecting to.
    if not image_url.startswith(base_url + "/"):
        return ""
    response = api.raw_get(image_url, handle_invalid_token=False)
    if response.status_code != 200:
        return ""
    image = QtGui.QImage.fromData(response.content)
    if image.isNull():
        return ""
    if image.width() > width or image.height() > height:
        image = image.scaled(
            width, height,
            QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
        )
    return _image_data_url(image, image_format)


def fetch_avatar(url, token, username):
    """Return the round avatar of the user as a data URL, or ''."""
    api = ayon_api.ServerAPI(
        url, token=token, timeout=REQUEST_TIMEOUT, max_retries=0
    )
    response = api.raw_get(f"users/{username}/avatar")
    # Users without an avatar get generated SVG initials; QML draws those.
    if response.status_code != 200 or "svg" in (response.content_type or ""):
        return ""
    image = QtGui.QImage.fromData(response.content)
    if image.isNull():
        return ""
    side = min(image.width(), image.height())
    image = image.copy(
        (image.width() - side) // 2, (image.height() - side) // 2, side, side
    ).scaled(
        AVATAR_SIZE, AVATAR_SIZE,
        QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation,
    )
    avatar = QtGui.QImage(
        AVATAR_SIZE, AVATAR_SIZE, QtGui.QImage.Format_ARGB32_Premultiplied
    )
    avatar.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(avatar)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtGui.QBrush(image))
    painter.drawEllipse(0, 0, AVATAR_SIZE, AVATAR_SIZE)
    painter.end()
    return _image_data_url(avatar)


def browser_login(url, token, forced_username):
    username = get_token_username(url, token)
    if not username:
        raise LoginError("This browser login has expired. Please try again.")
    if forced_username and username != forced_username:
        raise LoginError(
            f"Sign in as {forced_username} in your browser, or use your"
            " username and password below."
        )
    return url, token, username


def open_browser(url):
    if not webbrowser.open_new_tab(url):
        raise LoginError(
            "Your browser could not be opened. Try again or sign in below."
        )


class _Request(QtCore.QObject):
    """Keep blocking IO outside Qt without owning a running QThread."""

    completed = QtCore.Signal(int, str, object, str)

    def start(self, request_id, operation, function, args):
        threading.Thread(
            target=self._run,
            args=(request_id, operation, function, args),
            daemon=True,
        ).start()

    def _run(self, request_id, operation, function, args):
        result = None
        error = ""
        try:
            result = function(*args)
        except LoginError as exc:
            error = str(exc)
        except UrlError as exc:
            error = ". ".join([exc.title] + list(exc.hints))
        except Exception:
            # Network exceptions can contain URLs/tokens. Do not expose them.
            error = (
                "Could not connect to AYON. Check the server address and"
                " your connection, then try again."
            )
        finally:
            # Do not retain passwords in a completed request object.
            args = None
        self.completed.emit(request_id, operation, result, error)


class LoginController(QtCore.QObject):
    """State shared by the two QML pages; credentials stay in Python."""

    changed = QtCore.Signal()
    server_url_changed = QtCore.Signal()
    username_changed = QtCore.Signal()
    images_changed = QtCore.Signal()
    authenticated = QtCore.Signal(str, str, str)
    logged_out = QtCore.Signal()
    dismissed = QtCore.Signal()
    clear_password = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._url = ""
        self._username = ""
        self._api_key = None
        self._initialized = False
        self._connection_failed = False
        self._force_username = False
        self._logged_in = False
        self._logged_in_username = ""
        self._logged_in_url = ""
        self._logged_in_token = None
        # Valid supplied credentials (url, token, username) the user can
        #   continue with.
        self._session = None
        # Details of the signed in user
        self._session_user_loaded = False
        self._session_expired = False
        self._full_name = ""
        self._email = ""
        # Optional images by kind ("avatar", "logo", "background")
        self._images = {}
        self._page = 0
        self._busy = False
        self._error = ""
        self._browser_supported = False
        self._waiting = False
        self._listener = None
        self._deadline = 0
        self._request_id = 0
        self._requests = {}
        # Opening the browser can block (e.g. 'webbrowser' waits for the
        #   browser process on some platforms). It runs separately so it
        #   never blocks processing of the callback token.
        self._browser_open_id = 0
        self._browser_open_request = None
        self._fetch_id = 0
        self._fetches = {}
        self._latest_fetch = {}
        self._closed = False
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll_browser)

    @QtCore.Property(str, notify=server_url_changed)
    def serverUrl(self):
        return self._url

    @QtCore.Property(str, notify=username_changed)
    def username(self):
        return self._username

    @QtCore.Property(bool, notify=changed)
    def forceUsername(self):
        return self._force_username

    @QtCore.Property(bool, notify=changed)
    def loggedIn(self):
        return self._logged_in

    @QtCore.Property(str, notify=changed)
    def loggedInUsername(self):
        return self._logged_in_username

    @QtCore.Property(str, notify=changed)
    def sessionUsername(self):
        if self._logged_in:
            return self._logged_in_username
        return self._session[2] if self._session else ""

    @QtCore.Property(str, notify=changed)
    def sessionDisplayName(self):
        return self._full_name or self.sessionUsername

    @QtCore.Property(str, notify=changed)
    def sessionShortName(self):
        """First name of the signed in user, username if it is not known."""
        if self._full_name:
            return self._full_name.split()[0]
        return self.sessionUsername

    @QtCore.Property(str, notify=changed)
    def sessionEmail(self):
        return self._email

    # Images are data URLs, empty until they are loaded from the server.
    @QtCore.Property(str, notify=images_changed)
    def sessionAvatar(self):
        return self._images.get("avatar", "")

    @QtCore.Property(str, notify=images_changed)
    def studioLogo(self):
        return self._images.get("logo", "")

    @QtCore.Property(str, notify=images_changed)
    def studioBackground(self):
        return self._images.get("background", "")

    @QtCore.Property(bool, notify=changed)
    def canContinue(self):
        """Supplied credentials are valid for the server on sign-in page."""
        return (
            self._session is not None
            and self._page == 1
            and _normalize_url(self._url) == _normalize_url(self._session[0])
        )

    @QtCore.Property(bool, notify=changed)
    def isCurrentSession(self):
        """Server on the sign-in page is the one of the current session."""
        return (
            self._logged_in
            and not self._session_expired
            and self._page == 1
            and _normalize_url(self._url) == _normalize_url(
                self._logged_in_url
            )
        )

    @QtCore.Property(int, notify=changed)
    def page(self):
        return self._page

    @QtCore.Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @QtCore.Property(str, notify=changed)
    def errorMessage(self):
        return self._error

    @QtCore.Property(bool, notify=changed)
    def browserSupported(self):
        return self._browser_supported

    @QtCore.Property(bool, notify=changed)
    def waitingForBrowser(self):
        return self._waiting

    @QtCore.Property(bool, notify=changed)
    def connectionFailed(self):
        return self._connection_failed

    def set_url(self, url):
        if (url or "").strip().rstrip("/") != self._url.strip().rstrip("/"):
            # A supplied key belongs only to its original server.
            self._api_key = None
        self._url = url or ""
        self.server_url_changed.emit()

    def set_username(self, username):
        self._username = username or ""
        self.username_changed.emit()

    def set_force_username(self, value):
        self._force_username = bool(value)
        self.changed.emit()

    def set_api_key(self, api_key):
        self._api_key = api_key or None

    def set_logged_in(self, logged_in, username=None, url=None, api_key=None):
        """Show the current session and allow logout (change user mode).

        Login options are hidden while the current session's server is
        selected; changing the server shows them again. The api key is
        only used to show details of the signed in user.
        """
        self._logged_in = bool(logged_in)
        self._logged_in_username = (username or "") if logged_in else ""
        self._logged_in_url = (url or self._url) if logged_in else ""
        self._logged_in_token = (api_key or None) if logged_in else None
        self._set_session_user(None)
        self._session_user_loaded = False
        self._session_expired = False
        self.changed.emit()

    def _expire_session(self):
        """The current session cannot be continued; ask to sign in."""
        self._session_expired = True
        self._error = "Your login has expired. Please sign in again."

    def _set_session_user(self, user):
        attrib = (user or {}).get("attrib") or {}
        self._full_name = (attrib.get("fullName") or "").strip()
        self._email = (attrib.get("email") or "").strip()
        self._clear_images("avatar")

    def _clear_images(self, *kinds):
        """Forget loaded images and ignore the ones still loading."""
        for kind in kinds:
            self._images.pop(kind, None)
            self._latest_fetch.pop(kind, None)
        self.images_changed.emit()

    def initialize(self):
        """Validate prefilled connection details once the dialog is shown."""
        if self._initialized or self._closed:
            return
        self._initialized = True
        if self._url.strip():
            self.validateServer(self._url)

    def _start(self, operation, function, *args):
        self._request_id += 1
        request_id = self._request_id
        request = _Request()
        self._requests[request_id] = request
        request.completed.connect(self._complete, QtCore.Qt.QueuedConnection)
        self._busy = True
        self._error = ""
        self.changed.emit()
        request.start(request_id, operation, function, args)

    def _fetch_image(self, kind, function, *args):
        """Load an optional image without blocking the login flow."""
        self._fetch_id += 1
        fetch_id = self._fetch_id
        request = _Request()
        self._fetches[fetch_id] = request
        self._latest_fetch[kind] = fetch_id
        request.completed.connect(self._fetched, QtCore.Qt.QueuedConnection)
        request.start(fetch_id, kind, function, args)

    @QtCore.Slot(int, str, object, str)
    def _fetched(self, fetch_id, kind, result, error):
        self._fetches.pop(fetch_id, None)
        if (
            self._closed or error or not result
            or self._latest_fetch.get(kind) != fetch_id
        ):
            return
        self._images[kind] = result
        self.images_changed.emit()

    def _fetch_avatar(self):
        if self._session:
            url, token, username = self._session
        else:
            url, token, username = (
                self._url, self._logged_in_token, self._logged_in_username
            )
        if token and username:
            self._fetch_image("avatar", fetch_avatar, url, token, username)

    @QtCore.Slot(int, str, object, str)
    def _complete(self, request_id, operation, result, error):
        self._requests.pop(request_id, None)
        if self._closed or request_id != self._request_id:
            return
        self._busy = False
        if operation == "session_user":
            self._session_user_loaded = True
            self._page = 1
            if error:
                # Details of the current session are optional.
                pass
            elif result:
                self._set_session_user(result)
                self._fetch_avatar()
            else:
                self._expire_session()
        elif error:
            self._error = error
            if operation in ("server", "saved_login"):
                self._connection_failed = True
            if operation in ("open_browser", "browser_login"):
                self._stop_listener()
            if operation == "password":
                self.clear_password.emit()
        elif operation == "server":
            self._url, self._browser_supported = result
            self.server_url_changed.emit()
            self._clear_images(*STUDIO_IMAGES)
            for kind in STUDIO_IMAGES:
                self._fetch_image(kind, fetch_studio_image, self._url, kind)
            if self._api_key:
                self._start(
                    "saved_login", saved_login,
                    self._url, self._api_key, self._username,
                )
                return
            self._page = 1
            if self.isCurrentSession and not self._session_user_loaded:
                if not self._logged_in_token:
                    self._expire_session()
                else:
                    # Check the current session before it is shown
                    self._page = 0
                    self._start(
                        "session_user", get_token_user,
                        self._url, self._logged_in_token,
                    )
                    return
        elif operation == "saved_login":
            self._api_key = None
            if result is None:
                self._page = 1
                self._error = (
                    "Your saved credentials are no longer valid."
                    " Please sign in again."
                )
            else:
                # Do not continue automatically, the user may want to
                #   login as a different user.
                self._session = result[:3]
                self._page = 1
                self._set_session_user(result[3])
                self._fetch_avatar()
        elif operation == "logout":
            self._session = None
            self._set_session_user(None)
        elif operation in ("password", "browser_login"):
            self.clear_password.emit()
            self.authenticated.emit(*result)
        self.changed.emit()

    @QtCore.Slot(str)
    def validateServer(self, url):
        if self._closed or self._busy or self._page != 0:
            return
        self._connection_failed = False
        self.set_url(url)
        self._start("server", check_server, url)

    @QtCore.Slot(str, str)
    def signIn(self, username, password):
        if self._closed or self._busy or self._waiting or self._page != 1:
            return
        username = self._username if self._force_username else username.strip()
        if not username or not password:
            self._error = "Enter your username and password."
            self.changed.emit()
            return
        self._username = username
        self._start("password", password_login, self._url, username, password)

    @QtCore.Slot()
    def openBrowser(self):
        if (
            self._closed or self._busy or self._waiting
            or self._page != 1 or not self._browser_supported
        ):
            return
        try:
            self._listener = LoginServerListener(self._url)
            self._listener.start()
        except Exception:
            self._stop_listener()
            self._error = (
                "Could not start browser login. Try again or sign in below."
            )
            self.changed.emit()
            return
        redirect = f"http://localhost:{self._listener.port}"
        url = self._url + "/?" + urlencode({"auth_redirect": redirect})
        self._waiting = True
        self._error = ""
        self._deadline = time.monotonic() + BROWSER_TIMEOUT
        self.clear_password.emit()
        self._timer.start()
        self.changed.emit()

        self._browser_open_id += 1
        request = _Request()
        self._browser_open_request = request
        request.completed.connect(
            self._browser_opened, QtCore.Qt.QueuedConnection
        )
        request.start(
            self._browser_open_id, "open_browser", open_browser, (url,)
        )

    @QtCore.Slot(int, str, object, str)
    def _browser_opened(self, open_id, operation, result, error):
        if open_id != self._browser_open_id:
            return
        self._browser_open_request = None
        # Ignore errors when the login was cancelled or already finished.
        if self._closed or not error or not self._listener:
            return
        self._stop_listener()
        self._error = error
        self.changed.emit()

    def _poll_browser(self):
        if not self._listener:
            return
        if time.monotonic() >= self._deadline:
            self.cancelBrowser()
            self._error = "Browser login timed out. Please try again."
            self.changed.emit()
            return
        if self._busy:
            return
        token = self._listener.get_token()
        if not token:
            return
        self._stop_listener()
        # Keep the cancel control available while checking the callback token.
        self._waiting = True
        forced_username = self._username if self._force_username else None
        self._start(
            "browser_login", browser_login, self._url, token, forced_username
        )

    def _stop_listener(self):
        self._timer.stop()
        listener, self._listener = self._listener, None
        self._waiting = False
        if listener:
            threading.Thread(target=listener.stop, daemon=True).start()

    @QtCore.Slot()
    def cancelBrowser(self):
        self._request_id += 1
        self._stop_listener()
        self._busy = False
        self._error = ""
        self.changed.emit()

    @QtCore.Slot()
    def back(self):
        if self._closed:
            return
        self.cancelBrowser()
        self._page = 0
        self._browser_supported = False
        self._api_key = None
        self._connection_failed = False
        self.clear_password.emit()
        self.changed.emit()

    @QtCore.Slot()
    def continueSession(self):
        if self._closed or self._busy or self._waiting:
            return
        if self.canContinue:
            self.authenticated.emit(*self._session)
        elif self.isCurrentSession:
            # Keep the current session as is.
            self.dismissed.emit()

    @QtCore.Slot()
    def logout(self):
        if self._closed:
            return
        if self._logged_in:
            # The caller logs out the current session.
            self.cancelBrowser()
            self.logged_out.emit()
        elif self.canContinue and not self._busy and not self._waiting:
            # Expire the supplied credentials and ask to sign in again.
            url, token, _ = self._session
            self._start(
                "logout", logout_from_server, url, token, REQUEST_TIMEOUT
            )

    @QtCore.Slot()
    def clearError(self):
        if self._error or self._connection_failed:
            self._error = ""
            self._connection_failed = False
            self.changed.emit()

    def shutdown(self):
        self._closed = True
        self._api_key = None
        self._session = None
        self._logged_in_token = None
        self.cancelBrowser()
        self.clear_password.emit()


class QmlServerLoginWindow(QtWidgets.QDialog):
    """Embed QML while preserving the existing modal dialog result contract."""

    def __init__(
        self, parent=None, *, url=None, username=None, api_key=None,
        force_username=False, logged_in=False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Sign in to AYON")
        self.setWindowIcon(QtGui.QIcon(get_icon_path()))
        self.setMinimumSize(480, 560)
        self.resize(560, 720)
        self._result = (None, None, None, False)

        self.view = QtQuickWidgets.QQuickWidget(self)
        # The view destroys its QML scene before its QObject children. Keep
        # the controller alive until all bindings that reference it are gone.
        self.controller = LoginController(self.view)
        self.controller.authenticated.connect(self._authenticated)
        self.controller.logged_out.connect(self._logged_out)
        self.controller.dismissed.connect(self.reject)
        self.controller.set_url(url)
        self.controller.set_username(username)
        # The key of the current session is not used to log in again.
        self.controller.set_api_key(None if logged_in else api_key)
        self.controller.set_force_username(force_username)
        self.controller.set_logged_in(logged_in, username, url, api_key)

        self.view.setResizeMode(
            QtQuickWidgets.QQuickWidget.SizeRootObjectToView
        )
        self.view.setClearColor(QtGui.QColor("#252B32"))
        self.view.rootContext().setContextProperty("login", self.controller)
        self.view.setSource(QtCore.QUrl.fromLocalFile(str(
            Path(__file__).parent / "qml" / "Login.qml"
        )))
        if self.view.status() == QtQuickWidgets.QQuickWidget.Error:
            errors = "\n".join(
                error.toString() for error in self.view.errors()
            )
            raise RuntimeError(f"Could not load the AYON login UI:\n{errors}")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def set_url(self, url):
        self.controller.set_url(url)

    def set_username(self, username):
        self.controller.set_username(username)

    def set_force_username(self, force_username):
        self.controller.set_force_username(force_username)

    def set_api_key(self, api_key):
        self.controller.set_api_key(api_key)

    def set_logged_in(self, logged_in, username=None, url=None, api_key=None):
        self.controller.set_logged_in(logged_in, username, url, api_key)

    def showEvent(self, event):
        super().showEvent(event)
        self.controller.initialize()

    @QtCore.Slot(str, str, str)
    def _authenticated(self, url, token, username):
        self._result = (url, token, username, False)
        self.accept()

    @QtCore.Slot()
    def _logged_out(self):
        self._result = (None, None, None, True)
        self.accept()

    def result(self):
        return self._result

    def done(self, result):
        self.controller.shutdown()
        super().done(result)

    def closeEvent(self, event):
        self.controller.shutdown()
        super().closeEvent(event)


if __name__ == "__main__":
    # Standalone manual check; successful credentials are never printed/saved.
    app = get_qt_app()
    window = QmlServerLoginWindow()
    window.show()
    app.exec_()
