"""Handle credentials and connection to server for AYON launcher.

Cache and store used server urls. Store/load API keys to/from keyring if
needed. Store metadata about used urls, usernames for the urls and when was
the connection with the username established.

On bootstrap is created global connection with information about site and
AYON launcher version. The connection object lives in 'ayon_api'.
"""

import os
import json
import platform
import datetime
import contextlib
import subprocess
import tempfile
from typing import Optional, Union, Any

import ayon_api

from ayon_api.constants import SERVER_URL_ENV_KEY, SERVER_API_ENV_KEY
from ayon_api.exceptions import UrlError
from ayon_api.utils import (
    validate_url,
    logout_from_server,
)

from ayon_common.utils import (
    get_ayon_appdirs,
    get_local_site_id,
    get_ayon_launch_args,
)


class ChangeUserResult:
    def __init__(
        self, logged_out, old_url, old_token, old_username,
        new_url, new_token, new_username
    ):
        shutdown = logged_out
        restart = new_url is not None and new_url != old_url
        token_changed = new_token is not None and new_token != old_token

        self.logged_out = logged_out
        self.old_url = old_url
        self.old_token = old_token
        self.old_username = old_username
        self.new_url = new_url
        self.new_token = new_token
        self.new_username = new_username

        self.shutdown = shutdown
        self.restart = restart
        self.token_changed = token_changed


def _get_servers_path():
    return get_ayon_appdirs("used_servers.json")


def _get_ui_dir_path(*args) -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, "ui", *args)


def get_servers_info_data():
    """Metadata about used server on this machine.

    Store data about all used server urls, last used url and user username for
    the url. Using this metadata we can remember which username was used per
    url if token stored in keyring loose lifetime.

    Returns:
        dict[str, Any]: Information about servers.
    """

    data = {}
    servers_info_path = _get_servers_path()
    if not os.path.exists(servers_info_path):
        dirpath = os.path.dirname(servers_info_path)
        os.makedirs(dirpath, exist_ok=True)

        return data

    with open(servers_info_path, "r") as stream:
        with contextlib.suppress(BaseException):
            data = json.load(stream)
    return data


def add_server(url: str, username: str):
    """Add server to server info metadata.

    This function will also mark the url as last used url on the machine so on
    next launch will be used.

    Args:
        url (str): Server url.
        username (str): Name of user used to log in.
    """

    servers_info_path = _get_servers_path()
    data = get_servers_info_data()
    data["last_server"] = url
    if "urls" not in data:
        data["urls"] = {}
    data["urls"][url] = {
        "updated_dt": datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
        "username": username,
    }

    with open(servers_info_path, "w") as stream:
        json.dump(data, stream)


def remove_server(url: str):
    """Remove server url from servers information.

    This should be used on logout to completelly loose information about server
    on the machine.

    Args:
        url (str): Server url.
    """

    if not url:
        return

    servers_info_path = _get_servers_path()
    data = get_servers_info_data()
    if data.get("last_server") == url:
        data["last_server"] = None

    if "urls" in data:
        data["urls"].pop(url, None)

    with open(servers_info_path, "w") as stream:
        json.dump(data, stream)


def get_last_server(
    data: Optional[dict[str, Any]] = None
) -> Union[str, None]:
    """Last server used to log in on this machine.

    Args:
        data (Optional[dict[str, Any]]): Prepared server information data.

    Returns:
        Union[str, None]: Last used server url.
    """

    if data is None:
        data = get_servers_info_data()
    return data.get("last_server")


def get_last_username_by_url(
    url: str,
    data: Optional[dict[str, Any]] = None
) -> Union[str, None]:
    """Get last username which was used for passed url.

    Args:
        url (str): Server url.
        data (Optional[dict[str, Any]]): Servers info.

    Returns:
         Union[str, None]: Username.
    """

    if not url:
        return None

    if data is None:
        data = get_servers_info_data()

    if urls := data.get("urls"):
        if url_info := urls.get(url):
            return url_info.get("username")
    return None


def get_last_server_with_username():
    """Receive last server and username used in last connection.

    Returns:
        tuple[Union[str, None], Union[str, None]]: Url and username.
    """

    data = get_servers_info_data()
    url = get_last_server(data)
    username = get_last_username_by_url(url)
    return url, username


class TokenKeyring:
    # Fake username with hardcoded username
    username_key = "username"

    def __init__(self, url):
        try:
            import keyring

        except Exception as exc:
            raise NotImplementedError(
                "Python module `keyring` is not available."
            ) from exc

        # hack for cx_freeze and Windows keyring backend
        if platform.system().lower() == "windows":
            from keyring.backends import Windows

            keyring.set_keyring(Windows.WinVaultKeyring())

        self._url = url
        self._keyring_key = f"AYON/{url}"

    def get_value(self):
        import keyring

        return keyring.get_password(self._keyring_key, self.username_key)

    def set_value(self, value):
        import keyring

        if value is not None:
            keyring.set_password(self._keyring_key, self.username_key, value)
            return

        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(self._keyring_key, self.username_key)


def load_token(url: str) -> Union[str, None]:
    """Get token for url from keyring.

    Args:
        url (str): Server url.

    Returns:
        Union[str, None]: Token for passed url available in keyring.
    """

    return TokenKeyring(url).get_value()


def store_token(url: str, token: str):
    """Store token by url to keyring.

    Args:
        url (str): Server url.
        token (str): User token to server.
    """

    TokenKeyring(url).set_value(token)


def ask_to_login_ui(
    url: Optional[str] = None,
    always_on_top: Optional[bool] = False,
    username: Optional[str] = None,
    force_username: Optional[bool] = False
) -> tuple[str, str, str]:
    """Ask user to login using UI.

    This should be used only when user is not yet logged in at all or available
    credentials are invalid. To change credentials use 'change_user_ui'
    function.

    Use a subprocess to show UI.

    Args:
        url (Optional[str]): Server url that could be prefilled in UI.
        always_on_top (Optional[bool]): Window will be drawn on top of
            other windows.
        username (Optional[str]): Username that will be prefilled in UI.
        force_username (Optional[bool]): Username will be locked.

    Returns:
        tuple[str, str, str]: Url, user's token and username.
    """

    ui_dir = _get_ui_dir_path()
    if url is None:
        url = get_last_server()

    if not username:
        username = get_last_username_by_url(url)

    data = {
        "url": url,
        "username": username,
        "always_on_top": always_on_top,
        "force_username": force_username,
    }

    with tempfile.NamedTemporaryFile(
        mode="w", prefix="ayon_login", suffix=".json", delete=False
    ) as tmp:
        output = tmp.name
        json.dump(data, tmp)

    code = subprocess.call(
        get_ayon_launch_args(ui_dir, "--skip-bootstrap", output))
    if code != 0:
        raise RuntimeError("Failed to show login UI")

    with open(output, "r") as stream:
        data = json.load(stream)
    os.remove(output)
    return data["output"]


def show_login_ui(
    url: Union[str, None],
    username: Union[str, None],
    token: Union[str, None],
) -> ChangeUserResult:
    """Show login UI and process inputs.

    Todos:
        Add more arguments to function to be able to prefill UI with
            information, like server is unreachable, url is invalid, token is
            unauthorized, etc.

    Args:
        url (Union[str, None]): Server url that could be prefilled in UI.
        username (Union[str, None]): Username that could be prefilled in UI.
        token (Union[str, None]): User's token that could be prefilled in UI.

    Returns:
        ChangeUserResult: Information about user change.
    """

    from .ui import change_user

    result = change_user(url, username, token)
    new_url, new_token, new_username, logged_out = result

    return ChangeUserResult(
        logged_out, url, token, username,
        new_url, new_token, new_username
    )


def change_user_ui() -> ChangeUserResult:
    """Change user using UI.

    Show UI to user where he can change credentials or url. Output will contain
    all information about old/new values of url, username, api key. If user
    confirmed or declined values.

    Returns:
         ChangeUserResult: Information about user change.
    """

    # For backwards compatibility show dialog that current session does not
    #   allow credentials change
    if os.getenv("AYON_IN_LOGIN_MODE") == "0":
        show_invalid_credentials_ui(in_subprocess=False)
        return ChangeUserResult(
            False,
            os.getenv(SERVER_URL_ENV_KEY),
            os.getenv(SERVER_API_ENV_KEY),
            None,
            None,
            None,
            None
        )

    url, username = get_last_server_with_username()
    token = load_token(url)
    output = show_login_ui(url, username, token)
    if output.logged_out:
        logout(url, token)

    elif output.token_changed:
        change_token(
            output.new_url,
            output.new_token,
            output.new_username,
            output.old_url
        )
    return output


def change_token(
    url: str,
    token: str,
    username: Optional[str] = None,
    old_url: Optional[str] = None
):
    """Change url and token in currently running session.

    Function can also change server url, in that case are previous credentials
    NOT removed from cache.

    Args:
        url (str): Url to server.
        token (str): New token to be used for url connection.
        username (Optional[str]): Username of logged user.
        old_url (Optional[str]): Previous url. Value from 'get_last_server'
            is used if not entered.
    """

    if old_url is None:
        old_url = get_last_server()
    if old_url and old_url == url:
        remove_url_cache(old_url)

    # TODO check if ayon_api is already connected
    add_server(url, username)
    store_token(url, token)
    ayon_api.change_token(url, token)


def remove_url_cache(url: str):
    """Clear cache for server url.

    Args:
        url (str): Server url which is removed from cache.
    """

    store_token(url, None)


def remove_token_cache(url: str, token: str):
    """Remove token from local cache of url.

    Is skipped if cached token under the passed url is not the same
    as passed token.

    Args:
        url (str): Url to server.
        token (str): Token to be removed from url cache.
    """

    if load_token(url) == token:
        remove_url_cache(url)


def logout(url: str, token: str):
    """Logout from server and throw token away.

    Args:
        url (str): Url from which should be logged out.
        token (str): Token which should be used to log out.
    """

    remove_server(url)
    ayon_api.close_connection()
    ayon_api.set_environments(None, None)
    remove_token_cache(url, token)
    logout_from_server(url, token)


def load_environments():
    """Load environments on startup.

    Handle environments needed for connection with server. Environments are
    'AYON_SERVER_URL' and 'AYON_API_KEY'.

    Server is looked up from environment. Already set environent is not
    changed. If environemnt is not filled then last server stored in appdirs
    is used.

    Token is skipped if url is not available. Otherwise, is also checked from
    env and if is not available then uses 'load_token' to try to get token
    based on server url.
    """

    server_url = os.environ.get(SERVER_URL_ENV_KEY)
    if not server_url:
        server_url = get_last_server()
        if not server_url:
            return
        os.environ[SERVER_URL_ENV_KEY] = server_url

    if not os.environ.get(SERVER_API_ENV_KEY):
        if token := load_token(server_url):
            os.environ[SERVER_API_ENV_KEY] = token


def set_environments(url: str, token: str):
    """Change url and token environemnts in currently running process.

    Args:
        url (str): New server url.
        token (str): User's token.
    """

    ayon_api.set_environments(url, token)


def create_global_connection():
    """Create global connection with site id and AYON launcher version.

    Make sure this function is called once during process runtime.

    The global connection in 'ayon_api' have entered site id and
        AYON launcher version.
    """

    ayon_api.create_connection(
        get_local_site_id(), os.environ.get("AYON_VERSION")
    )


def is_token_valid(
    url: str, token: str, expected_username: Optional[str] = None
) -> bool:
    """Check if token is valid.

    Note:
        This function is available in 'ayon_api', but does not support to
            validate service api key, only user's token. The support will be
            added in future PRs of 'ayon_api'.
        The function also did not support timeout which could cause
            'ayon_api.is_token_valid' to hang.

    Args:
        url (str): Server url.
        token (str): User's token.
        expected_username (Optional[str]): Token must belong to user with
            this username. Ignored if is 'None'.

    Returns:
        bool: True if token is valid.
    """

    api = ayon_api.ServerAPI(url, token)
    if not api.has_valid_token:
        return False
    if expected_username:
        return expected_username == api.get_user()["name"]
    return True


def need_server_or_login(username: Optional[str] = None) -> tuple[bool, bool]:
    """Check if server url or login to the server are needed.

    It is recommended to call 'load_environments' on startup before this check.
    But in some cases this function could be called after startup.

    Returns:
        tuple[bool, bool]: Server or api key needed. Both are 'True' if
            are available and valid.
    """

    server_url = os.environ.get(SERVER_URL_ENV_KEY)
    if not server_url:
        return True, True

    try:
        server_url = validate_url(server_url)
    except UrlError:
        return True, True

    token = os.environ.get(SERVER_API_ENV_KEY)
    if token:
        return False, not is_token_valid(server_url, token, username)

    token = load_token(server_url)
    if token:
        return False, not is_token_valid(server_url, token, username)
    return False, True


def confirm_server_login(url: str, token: str, username: Union[str, None]):
    """Confirm login of user and do necessary stepts to apply changes.

    This should not be used on "change" of user but on first login.

    Args:
        url (str): Server url where user authenticated.
        token (str): API token used for authentication to server.
        username (Union[str, None]): Username related to API token.
    """

    add_server(url, username)
    store_token(url, token)
    set_environments(url, token)


def _show_invalid_credentials_subprocess(message, always_on_top=False):
    ui_script_path = _get_ui_dir_path("invalid_window.py")
    data = {
        "message": message,
        "always_on_top": always_on_top,
    }
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="ayon_invalid_cred", suffix=".json", delete=False
    ) as tmp:
        output = tmp.name
        json.dump(data, tmp)

    code = subprocess.call(
        get_ayon_launch_args(ui_script_path, "--skip-bootstrap", output))
    if code != 0:
        raise RuntimeError("Failed to show login UI")


def show_invalid_credentials_ui(
    message: Optional[str] = None,
    in_subprocess: bool = False,
    always_on_top: bool = False,
):
    """Show UI with information about invalid credentials.

    This can be used when AYON launcher is in bypass login mode. In that case
    'change_user_ui' cannot be used to change credentials.

    Args:
        in_subprocess (bool): Show UI in subprocess.
        message (Optional[str]): Message to be shown to user.
        always_on_top (Optional[bool]): Window will be drawn on top of
            other windows.
    """

    if in_subprocess:
        return _show_invalid_credentials_subprocess(message, always_on_top)

    from .ui import invalid_credentials

    invalid_credentials(message)
