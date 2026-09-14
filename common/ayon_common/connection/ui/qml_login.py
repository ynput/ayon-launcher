"""Qt Quick login dialog using the launcher's existing authentication API."""

import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import ayon_api
from ayon_api.exceptions import UnauthorizedError, UrlError
from ayon_api.utils import login_to_server, validate_url
from qtpy import QtCore, QtGui, QtQuickWidgets, QtWidgets

from ayon_common.resources import get_icon_path
from ayon_common.ui_utils import get_qt_app

from .server import LoginServerListener


REQUEST_TIMEOUT = 10
BROWSER_TIMEOUT = 180


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


def get_token_username(url, token):
    """Return the authenticated username, or None for an invalid token."""
    api = ayon_api.ServerAPI(
        url, token=token, timeout=REQUEST_TIMEOUT, max_retries=0
    )
    try:
        user = api.get_user()
    except UnauthorizedError:
        user = None
    return user.get("name") if user else None


def saved_login(url, token, expected_username):
    """Check supplied credentials; let network errors propagate for retry."""
    username = get_token_username(url, token)
    if not username or (expected_username and username != expected_username):
        return None
    return url, token, username


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
    authenticated = QtCore.Signal(str, str, str)
    clear_password = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._url = ""
        self._username = ""
        self._api_key = None
        self._initialized = False
        self._connection_failed = False
        self._force_username = False
        self._page = 0
        self._busy = False
        self._error = ""
        self._browser_supported = False
        self._waiting = False
        self._listener = None
        self._deadline = 0
        self._request_id = 0
        self._requests = {}
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

    @QtCore.Slot(int, str, object, str)
    def _complete(self, request_id, operation, result, error):
        self._requests.pop(request_id, None)
        if self._closed or request_id != self._request_id:
            return
        self._busy = False
        if error:
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
            if self._api_key:
                self._start(
                    "saved_login", saved_login,
                    self._url, self._api_key, self._username,
                )
                return
            self._page = 1
        elif operation == "saved_login":
            self._api_key = None
            if result is None:
                self._page = 1
                self._error = (
                    "Your saved credentials are no longer valid."
                    " Please sign in again."
                )
            else:
                self.authenticated.emit(*result)
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
        self._deadline = time.monotonic() + BROWSER_TIMEOUT
        self.clear_password.emit()
        self._timer.start()
        self._start("open_browser", open_browser, url)

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
    def clearError(self):
        if self._error or self._connection_failed:
            self._error = ""
            self._connection_failed = False
            self.changed.emit()

    def shutdown(self):
        self._closed = True
        self._api_key = None
        self.cancelBrowser()
        self.clear_password.emit()


class QmlServerLoginWindow(QtWidgets.QDialog):
    """Embed QML while preserving the existing modal dialog result contract."""

    def __init__(
        self, parent=None, *, url=None, username=None, api_key=None,
        force_username=False,
    ):
        super().__init__(parent)
        self.setWindowTitle("Sign in to AYON")
        self.setWindowIcon(QtGui.QIcon(get_icon_path()))
        self.setMinimumSize(540, 700)
        self.resize(940, 740)
        self._result = (None, None, None, False)

        self.view = QtQuickWidgets.QQuickWidget(self)
        # The view destroys its QML scene before its QObject children. Keep
        # the controller alive until all bindings that reference it are gone.
        self.controller = LoginController(self.view)
        self.controller.authenticated.connect(self._authenticated)
        self.controller.set_url(url)
        self.controller.set_username(username)
        self.controller.set_api_key(api_key)
        self.controller.set_force_username(force_username)

        self.view.setResizeMode(
            QtQuickWidgets.QQuickWidget.SizeRootObjectToView
        )
        self.view.setClearColor(QtGui.QColor("#101317"))
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

    def showEvent(self, event):
        super().showEvent(event)
        self.controller.initialize()

    @QtCore.Slot(str, str, str)
    def _authenticated(self, url, token, username):
        self._result = (url, token, username, False)
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
