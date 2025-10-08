# -*- coding: utf-8 -*-
"""Main entry point for AYON command.

Bootstrapping process of AYON.

This script is responsible for setting up the environment and
bootstrapping AYON. It is also responsible for updating AYON
from AYON server.

Arguments that are always handled by AYON launcher:
    --verbose <level> - set log level
    --debug - enable debug mode
    --skip-headers - skip printing headers
    --skip-bootstrap - skip bootstrap process - use only for bootstrap logic
    --use-staging - use staging server
    --use-dev - use dev server
    --bundle <bundle_name> - specify bundle name to use
    --headless - enable headless mode - bootstrap won't show any UI

AYON launcher can be running in multiple different states. The top layer of
states is 'production', 'staging' and 'dev'.

To start in dev mode use one of following options:
    - by passing '--use-dev' argument
    - by setting 'AYON_USE_DEV' environment variable to '1'
    - by passing '--bundle <dev bundle name>'
    - by setting 'AYON_BUNDLE_NAME' environment variable to dev bundle name
    - by passing '--studio-bundle <dev bundle name>'
    - by setting 'AYON_STUDIO_BUNDLE_NAME' environment variable to dev bundle name

NOTE: By using bundle name you can start any dev bundle, even if is not
    assigned to current user.

To start in staging mode make sure none of develop options are used and then
use one of following options:
    - by passing '--use-staging' argument
    - by setting 'AYON_USE_STAGING' environment variable to '1'

Staging mode must be defined explicitly cannot be determined by bundle name.
In all other cases AYON launcher will start in 'production' mode.

Headless mode is not guaranteed after bootstrap process. It is possible that
some addon won't handle headless mode and will try to use UIs.

After bootstrap process AYON launcher will start 'ayon_core' addon. This addon
is responsible for handling all other addons and their logic.

Environment variables set during bootstrap:
    - AYON_VERSION - version of AYON launcher
    - AYON_BUNDLE_NAME - name of bundle to use
    - AYON_USE_STAGING - set to '1' if staging mode is enabled
    - AYON_USE_DEV - set to '1' if dev mode is enabled
    - AYON_DEBUG - set to '1' if debug mode is enabled
    - AYON_HEADLESS_MODE - set to '1' if headless mode is enabled
    - AYON_SERVER_URL - URL of AYON server
    - AYON_API_KEY - API key for AYON server
    - AYON_SERVER_TIMEOUT - timeout for AYON server
    - AYON_SERVER_RETRIES - number of retries for AYON server
    - AYON_EXECUTABLE - path to AYON executable
    - AYON_ROOT - path to AYON root directory
    - AYON_MENU_LABEL - label for AYON integrations menu
    - AYON_LAUNCHER_STORAGE_DIR - dir where addons, dependency packages,
        shim etc. are stored
    - AYON_LAUNCHER_LOCAL_DIR - dir where machine specific files are stored
    - AYON_ADDONS_DIR - path to AYON addons directory
    - AYON_DEPENDENCIES_DIR - path to AYON dependencies directory

Some of the environment variables are not in this script but in 'ayon_common'
module.
- Function 'create_global_connection' can change 'AYON_USE_DEV' and
    'AYON_USE_STAGING'.
- Bootstrap will set 'AYON_LAUNCHER_STORAGE_DIR' and 'AYON_LAUNCHER_LOCAL_DIR'
    if are not set yet.
- Distribution logic can set 'AYON_ADDONS_DIR' and 'AYON_DEPENDENCIES_DIR'
    if are not set yet.
"""

import os
import platform
import sys
import site
import time
import traceback
import subprocess
from contextlib import contextmanager
from urllib.parse import urlparse, parse_qs

from version import __version__

ORIGINAL_ARGS = list(sys.argv)

PREVIOUS_AYON_VERSION = os.getenv("AYON_VERSION", "")

os.environ["AYON_VERSION"] = __version__

# Define which bundles are used
if "--bundle" in sys.argv:
    idx = sys.argv.index("--bundle")
    sys.argv.pop(idx)
    if idx >= len(sys.argv):
        raise RuntimeError((
            "Expect value after \"--bundle\" argument."
        ))
    os.environ["AYON_STUDIO_BUNDLE_NAME"] = sys.argv.pop(idx)

if "--project-bundle" in sys.argv:
    idx = sys.argv.index("--project-bundle")
    sys.argv.pop(idx)
    if idx >= len(sys.argv):
        raise RuntimeError((
            "Expect value after \"---project-bundle\" argument."
        ))
    os.environ["AYON_BUNDLE_NAME"] = sys.argv.pop(idx)

if "--project" in sys.argv:
    idx = sys.argv.index("--project") + 1
    if idx >= len(sys.argv):
        raise RuntimeError((
            "Expect value after \"--project\" argument."
        ))
    os.environ["AYON_PROJECT_NAME"] = sys.argv[idx]

# Enabled logging debug mode when "--debug" is passed
if "--verbose" in sys.argv:
    expected_values = (
        "Expected: notset, debug, info, warning, error, critical"
        " or integer [0-50]."
    )
    idx = sys.argv.index("--verbose")
    sys.argv.pop(idx)
    if idx >= len(sys.argv):
        raise RuntimeError((
            f"Expect value after \"--verbose\" argument. {expected_values}"
        ))

    value = sys.argv.pop(idx)
    low_value = value.lower()
    log_level = None
    if low_value.isdigit():
        log_level = int(low_value)
    elif low_value == "notset":
        log_level = 0
    elif low_value == "debug":
        log_level = 10
    elif low_value == "info":
        log_level = 20
    elif low_value == "warning":
        log_level = 30
    elif low_value == "error":
        log_level = 40
    elif low_value == "critical":
        log_level = 50

    if log_level is None:
        raise ValueError((
            "Unexpected value after \"--verbose\" "
            f"argument \"{value}\". {expected_values}"
        ))

    os.environ["AYON_LOG_LEVEL"] = str(log_level)

# Enable debug mode, may affect log level if log level is not defined
if "--debug" in sys.argv:
    sys.argv.remove("--debug")
    os.environ["AYON_DEBUG"] = "1"

SKIP_HEADERS = False
if "--skip-headers" in sys.argv:
    sys.argv.remove("--skip-headers")
    SKIP_HEADERS = True

SKIP_BOOTSTRAP = False
if "--skip-bootstrap" in sys.argv:
    sys.argv.remove("--skip-bootstrap")
    SKIP_BOOTSTRAP = True

if "--use-staging" in sys.argv:
    sys.argv.remove("--use-staging")
    os.environ["AYON_USE_STAGING"] = "1"

if "--use-dev" in sys.argv:
    sys.argv.remove("--use-dev")
    os.environ["AYON_USE_DEV"] = "1"

SHOW_LOGIN_UI = False
if "--ayon-login" in sys.argv:
    sys.argv.remove("--ayon-login")
    SHOW_LOGIN_UI = True


def _is_in_login_mode():
    # Handle cases when source AYON launcher has version before '1.0.1'
    # - When user launcher an executable of AYON launcher it will run correct
    #   version of AYON launcher by bundle, but older launcher versions
    #   will not set 'AYON_IN_LOGIN_MODE' environment variable. Therefore,
    #   we need to check 'PREVIOUS_AYON_VERSION' and set 'AYON_IN_LOGIN_MODE'
    #   to 'True' when version is before '1.0.1'.
    # - this would be `return "AYON_API_KEY" not in os.environ` otherwise
    if "AYON_API_KEY" not in os.environ:
        return True

    # Handle cases when source AYON launcher has version before '1.0.1'
    version_parts = PREVIOUS_AYON_VERSION.split(".")
    if len(version_parts) < 3:
        return False

    try:
        # Keep only first 3 version parts which should be integers
        new_version_parts = [
            int(part_value)
            for part_idx, part_value in enumerate(version_parts)
            if part_idx < 3
        ]
    except ValueError:
        return False
    milestone = (1, 0, 1)
    return tuple(new_version_parts) < milestone


# Login mode is helper to detect if user is using AYON server credentials
#   from login UI (and keyring), or from environment variables.
# - Variable is set in first AYON launcher process for possible subprocesses
if SHOW_LOGIN_UI:
    # Make sure login mode is set to '1' when '--ayon-login' is passed
    os.environ["AYON_IN_LOGIN_MODE"] = "1"

elif "AYON_IN_LOGIN_MODE" not in os.environ:
    os.environ["AYON_IN_LOGIN_MODE"] = str(int(_is_in_login_mode()))

if "--headless" in sys.argv:
    os.environ["AYON_HEADLESS_MODE"] = "1"
    sys.argv.remove("--headless")

elif os.getenv("AYON_HEADLESS_MODE") != "1":
    os.environ.pop("AYON_HEADLESS_MODE", None)

IS_BUILT_APPLICATION = getattr(sys, "frozen", False)
HEADLESS_MODE_ENABLED = os.getenv("AYON_HEADLESS_MODE") == "1"
AYON_IN_LOGIN_MODE = os.environ["AYON_IN_LOGIN_MODE"] == "1"

_pythonpath = os.getenv("PYTHONPATH", "")
_python_paths = [
    path
    for path in _pythonpath.split(os.pathsep)
    if path
]
if not IS_BUILT_APPLICATION:
    # Code root defined by `start.py` directory
    AYON_ROOT = os.path.dirname(os.path.abspath(__file__))
    _dependencies_path = site.getsitepackages()[-1]
else:
    AYON_ROOT = os.path.dirname(sys.executable)

    # add dependencies folder to sys.pat for frozen code
    _dependencies_path = os.path.normpath(
        os.path.join(AYON_ROOT, "dependencies")
    )
# add stuff from `<frozen>/dependencies` to PYTHONPATH.
sys.path.insert(0, _dependencies_path)
if _dependencies_path in _python_paths:
    _python_paths.remove(_dependencies_path)
_python_paths.insert(0, _dependencies_path)

# Add common package to PYTHONPATH
# - common contains common code and bootstrap logic (like connection
#   and distribution)
common_path = os.path.join(AYON_ROOT, "common")
sys.path.insert(0, common_path)
if common_path in _python_paths:
    _python_paths.remove(common_path)
_python_paths.insert(0, common_path)

# Vendored python modules that must not be in PYTHONPATH environment but
#   are required for AYON launcher processes
sys.path.insert(0, os.path.join(AYON_ROOT, "vendor", "python"))

os.environ["PYTHONPATH"] = os.pathsep.join(_python_paths)

# enabled AYON state
os.environ["USE_AYON_SERVER"] = "1"
# Set this to point either to `python` from venv in case of live code
#    or to `ayon` or `ayon_console` in case of frozen code
os.environ["AYON_EXECUTABLE"] = sys.executable
os.environ["AYON_ROOT"] = AYON_ROOT
os.environ["AYON_MENU_LABEL"] = "AYON"

import blessed  # noqa: E402
import certifi  # noqa: E402
import requests  # noqa: E402


if sys.__stdout__:
    term = blessed.Terminal()

    def _print(message: str):
        if message.startswith("!!! "):
            print(f'{term.orangered2("!!! ")}{message[4:]}')
        elif message.startswith(">>> "):
            print(f'{term.aquamarine3(">>> ")}{message[4:]}')
        elif message.startswith("--- "):
            print(f'{term.darkolivegreen3("--- ")}{message[4:]}')
        elif message.startswith("*** "):
            print(f'{term.gold("*** ")}{message[4:]}')
        elif message.startswith("  - "):
            print(f'{term.wheat("  - ")}{message[4:]}')
        elif message.startswith("  . "):
            print(f'{term.tan("  . ")}{message[4:]}')
        elif message.startswith("     - "):
            print(f'{term.seagreen3("     - ")}{message[7:]}')
        elif message.startswith("     ! "):
            print(f'{term.goldenrod("     ! ")}{message[7:]}')
        elif message.startswith("     * "):
            print(f'{term.aquamarine1("     * ")}{message[7:]}')
        elif message.startswith("    "):
            print(f'{term.darkseagreen3("    ")}{message[4:]}')
        else:
            print(message)
else:
    def _print(message: str):
        print(message)


# if SSL_CERT_FILE is not set prior to AYON launcher launch, we set it to
#   point to certifi bundle to make sure we have reasonably
#       new CA certificates.
if not os.getenv("SSL_CERT_FILE"):
    os.environ["SSL_CERT_FILE"] = certifi.where()
elif os.getenv("SSL_CERT_FILE") != certifi.where():
    _print("--- your system is set to use custom CA certificate bundle.")

from ayon_api import (  # noqa E402
    get_base_url,
    set_default_settings_variant,
    get_addons_studio_settings,
    get_event,
    update_event,
    take_web_action_event,
    abort_web_action_event,
)
from ayon_api.constants import (  # noqa E402
    SERVER_URL_ENV_KEY,
    SERVER_API_ENV_KEY,
    DEFAULT_VARIANT_ENV_KEY,
    SITE_ID_ENV_KEY,
)
from ayon_common import is_staging_enabled, is_dev_mode_enabled  # noqa E402
from ayon_common.connection.credentials import (  # noqa E402
    ask_to_login_ui,
    add_server,
    load_token,
    need_server_or_login,
    load_environments,
    create_global_connection,
    confirm_server_login,
    show_invalid_credentials_ui,
)
from ayon_common.distribution import (  # noqa E402
    AYONDistribution,
    BundleNotFoundError,
    show_missing_bundle_information,
    show_blocked_auto_update,
    show_missing_permissions,
    show_installer_issue_information,
    UpdateWindowManager,
)

from ayon_common.utils import (  # noqa E402
    store_current_executable_info,
    deploy_ayon_launcher_shims,
    get_local_site_id,
    get_launcher_local_dir,
    get_launcher_storage_dir,
)
from ayon_common.startup import show_startup_error  # noqa E402


def _connect_to_ayon_server(force=False, username=None):
    """Connect to AYON server.

    Load existing credentials to AYON server, and show login dialog if are not
        valid. When 'force' is set to 'True' then login dialog is always
        shown.

    Login dialog cannot be shown in headless mode. In that case program
        is terminated with.
    If user closed dialog, program is terminated with exit code 0.

    Args:
        force (Optional[bool]): Force login to server.
        username (Optional[str]): Username that will be forced to use.

    """
    if force and HEADLESS_MODE_ENABLED:
        _print("!!! Login UI was requested in headless mode.")
        sys.exit(1)

    if os.getenv(SERVER_API_ENV_KEY):
        _print("*** Using API key from environment variable to connect")

    load_environments()
    need_server = need_api_key = True
    if not force:
        need_server, need_api_key = need_server_or_login(username)

    current_url = os.environ.get(SERVER_URL_ENV_KEY)

    if not need_server and not need_api_key:
        _print(f">>> Connected to AYON server {current_url}")
        return

    if need_server:
        if current_url:
            message = f"Could not connect to AYON server '{current_url}'."
        else:
            message = "AYON Server URL is not set."
    elif os.environ.get(SERVER_API_ENV_KEY):
        message = f"Invalid API key for '{current_url}'."
    else:
        message = f"Missing API key for '{current_url}'."

    if not force:
        _print("!!! Got invalid credentials.")
        _print(message)

    # Exit in headless mode
    if HEADLESS_MODE_ENABLED:
        _print((
            f"!!! Please use '{SERVER_URL_ENV_KEY}'"
            f" and '{SERVER_API_ENV_KEY}' environment variables to specify"
            " valid server url and api key for headless mode."
        ))
        sys.exit(1)

    # Show message that used credentials are invalid
    if not AYON_IN_LOGIN_MODE:
        show_invalid_credentials_ui(message=message, in_subprocess=True)
        sys.exit(1)

    # Show login dialog
    url, token, username = ask_to_login_ui(
        current_url,
        always_on_top=False,
        username=username,
        force_username=bool(username)
    )
    if url is not None and token is not None:
        confirm_server_login(url, token, username)
        return

    if url is not None:
        add_server(url, username)

    _print("!!! Login was not successful.")
    sys.exit(0)


def _set_default_settings_variant(use_dev, use_staging, bundle_name):
    """Based on states set default settings variant.

    Tell global connection which settings variant should be used.

    Args:
        use_dev (bool): Is dev mode enabled.
        use_staging (bool): Is staging mode enabled.
        bundle_name (str): Name of bundle to use.
    """

    if use_dev:
        variant = bundle_name
    elif use_staging:
        variant = "staging"
    else:
        variant = "production"

    os.environ[DEFAULT_VARIANT_ENV_KEY] = variant
    # Make sure dev env variable is set/unset for cases when dev mode is not
    #   enabled by '--use-dev' but by bundle name
    if use_dev:
        os.environ["AYON_USE_DEV"] = "1"
    else:
        os.environ.pop("AYON_USE_DEV", None)

    # Make sure staging is unset when 'dev' should be used
    if not use_staging:
        os.environ.pop("AYON_USE_STAGING", None)
    set_default_settings_variant(variant)


def _prepare_disk_mapping_args(src_path, dst_path):
    """Prepare disk mapping arguments to run.

    Args:
        src_path (str): Source path.
        dst_path (str): Destination path.

    Returns:
        list[str]: Arguments to run in subprocess.
    """

    low_platform = platform.system().lower()
    if low_platform == "windows":
        dst_path = dst_path.replace("/", "\\").rstrip("\\")
        src_path = src_path.replace("/", "\\").rstrip("\\")
        # Add slash after ':' ('G:' -> 'G:\') only for source
        if src_path.endswith(":"):
            src_path += "\\"
        return ["subst", dst_path, src_path]

    dst_path = dst_path.rstrip("/")
    src_path = src_path.rstrip("/")

    if low_platform == "linux":
        return ["sudo", "ln", "-s", src_path, dst_path]

    if low_platform == "darwin":
        scr = (
            f'do shell script "ln -s {src_path} {dst_path}"'
            ' with administrator privileges'
        )

        return ["osascript", "-e", scr]
    return []


def _run_disk_mapping(bundle_name):
    """Run disk mapping logic.

    Mapping of disks is taken from core addon settings. To run this logic
        '_set_default_settings_variant' must be called first, so correct
        settings are received from server.
    """

    low_platform = platform.system().lower()
    settings = get_addons_studio_settings(bundle_name)
    core_settings = settings.get("core") or {}
    disk_mapping = core_settings.get("disk_mapping") or {}
    platform_disk_mapping = disk_mapping.get(low_platform)
    if not platform_disk_mapping:
        return

    for item in platform_disk_mapping:
        src_path = item.get("source")
        dst_path = item.get("destination")
        if not src_path or not dst_path:
            continue

        if os.path.exists(dst_path):
            continue

        args = _prepare_disk_mapping_args(src_path, dst_path)
        if not args:
            continue

        _print(f"*** disk mapping arguments: {args}")
        try:
            output = subprocess.Popen(args)
            if output.returncode and output.returncode != 0:
                exc_msg = f'Executing was not successful: "{args}"'

                raise RuntimeError(exc_msg)
        except TypeError as exc:
            _print(
                f"Error {str(exc)} in mapping drive {src_path}, {dst_path}")
            raise


def _start_distribution():
    """Gets info from AYON server and updates possible missing pieces.

    Raises:
        RuntimeError
    """

    # Create distribution object
    try:
        distribution = AYONDistribution(
            skip_installer_dist=not IS_BUILT_APPLICATION
        )
    except PermissionError:
        _print(
            "!!! Failed to initialize distribution"
            " because of permissions error."
        )
        if not HEADLESS_MODE_ENABLED:
            show_missing_permissions()
        sys.exit(1)


    project_bundle = studio_bundle = None
    project_bundle_name = studio_bundle_name = None

    # Try to find required bundle and handle missing one
    try:
        studio_bundle = distribution.studio_bundle_to_use
        if studio_bundle is not None:
            studio_bundle_name = studio_bundle.name
    except BundleNotFoundError as exc:
        studio_bundle_name = exc.bundle_name

    try:
        project_bundle = distribution.project_bundle_to_use
        if project_bundle is not None:
            project_bundle_name = project_bundle.name
    except BundleNotFoundError as exc:
        project_bundle_name = exc.bundle_name

    if studio_bundle is None or project_bundle is None:
        url = get_base_url()
        username = distribution.active_user
        mode = "production"
        if distribution.use_dev:
            mode = f"dev for user '{username}'"
        elif distribution.use_staging:
            mode = "staging"

        _items = []
        if studio_bundle is None:
            _items.append((studio_bundle_name, "studio"))

        if (
            project_bundle is None
            and studio_bundle_name != project_bundle_name
        ):
            _items.append((project_bundle_name, "project"))

        for bundle_name, bundle_type in _items:
            if bundle_name:
                _print((
                    f"!!! Requested {bundle_type} bundle '{bundle_name}'"
                    " is not available on server."
                ))
                _print(
                    "!!! Check if is the bundle"
                    f" available on the server '{url}'."
                )

            else:
                _print(
                    f"!!! No {bundle_type} bundle is set as {mode}"
                    f" on the AYON server."
                )
                _print(
                    "!!! Make sure there is a bundle set"
                    f" as \"{mode}\" on the AYON server '{url}'."
                )

        if not HEADLESS_MODE_ENABLED:
            show_missing_bundle_information(
                url, project_bundle_name, username
            )

        sys.exit(1)

    # With known bundle and states we can define default settings variant
    #   in global connection
    _set_default_settings_variant(
        distribution.use_dev,
        distribution.use_staging,
        project_bundle_name
    )
    _run_disk_mapping(project_bundle_name)

    auto_update = (os.getenv("AYON_AUTO_UPDATE") or "").lower()
    skip_auto_update = auto_update == "skip"
    block_auto_update = auto_update == "block"
    if distribution.need_distribution and not skip_auto_update:
        if block_auto_update:
            _print(
                "!!! Automatic update is blocked by 'AYON_AUTO_UPDATE'."
            )
            if not HEADLESS_MODE_ENABLED:
                show_blocked_auto_update(
                    distribution.need_installer_distribution
                )
            sys.exit(1)

        if distribution.is_missing_permissions:
            _print(
                "!!! Failed to initialize distribution"
                " because of permissions error."
            )
            if not HEADLESS_MODE_ENABLED:
                show_missing_permissions()
            sys.exit(1)

        # Start distribution
        update_window_manager = UpdateWindowManager()
        if not HEADLESS_MODE_ENABLED:
            update_window_manager.start()

        try:
            distribution.distribute()
        finally:
            update_window_manager.stop()

        # Skip validation of addons and dep packages if launcher
        #   should be changed
        if not distribution.need_installer_change:
            # TODO check failed distribution and inform user
            distribution.validate_distribution()

    if distribution.need_installer_change:
        # Check if any error happened
        error = distribution.installer_dist_error
        if error:
            if HEADLESS_MODE_ENABLED:
                _print(error)
            else:
                show_installer_issue_information(
                    error,
                    distribution.installer_filepath
                )
            sys.exit(1)

        # Use new executable to relaunch different AYON launcher version
        executable = distribution.installer_executable
        args = list(ORIGINAL_ARGS)
        # Replace executable with new executable
        args[0] = executable

        # Cleanup 'PATH' and 'PYTHONPATH'
        env = os.environ.copy()
        path_paths = [
            path
            for path in env.get("PATH", "").split(os.pathsep)
            if path and not path.startswith(AYON_ROOT)
        ]
        python_paths = [
            path
            for path in env.get("PYTHONPATH", "").split(os.pathsep)
            if path and not path.startswith(AYON_ROOT)
        ]
        env["PATH"] = os.pathsep.join(path_paths)
        env["PYTHONPATH"] = os.pathsep.join(python_paths)

        # TODO figure out how this should be launched
        #   - it can technically cause infinite loop of subprocesses
        sys.exit(subprocess.call(args, env=env))

    # TODO check failed distribution and inform user
    distribution.validate_distribution()
    os.environ["AYON_BUNDLE_NAME"] = project_bundle_name
    os.environ["AYON_STUDIO_BUNDLE_NAME"] = studio_bundle_name

    # TODO probably remove paths to other addons?
    python_paths = [
        path
        for path in os.getenv("PYTHONPATH", "").split(os.pathsep)
        if path
    ]

    for path in distribution.get_python_paths():
        sys.path.insert(0, path)
        if path not in python_paths:
            python_paths.append(path)

    for path in distribution.get_sys_paths():
        sys.path.insert(0, path)

    os.environ["PYTHONPATH"] = os.pathsep.join(python_paths)


def init_launcher_executable(ensure_protocol_is_registered=False):
    """Initialize AYON launcher executable.

    Make sure current AYON launcher executable is stored to known executables
        and shim is deployed.

    """
    create_desktop_icons = "--create-desktop-icons" in sys.argv
    store_current_executable_info()
    deploy_ayon_launcher_shims(
        ensure_protocol_is_registered=ensure_protocol_is_registered,
        create_desktop_icons=create_desktop_icons,
    )


def fill_pythonpath():
    """Fill 'sys.path' with paths from PYTHONPATH environment variable."""
    lookup_set = set(sys.path)
    for path in (os.getenv("PYTHONPATH") or "").split(os.pathsep):
        if path not in lookup_set:
            sys.path.append(path)
            lookup_set.add(path)


def boot():
    """Bootstrap AYON launcher."""
    init_launcher_executable()

    # Setup site id in environment variable for all possible subprocesses
    if SITE_ID_ENV_KEY not in os.environ:
        os.environ[SITE_ID_ENV_KEY] = get_local_site_id()

    _connect_to_ayon_server()
    create_global_connection()
    _start_distribution()
    fill_pythonpath()

    # Call launcher storage dir getters to make sure their
    #   env variables are set
    get_launcher_local_dir()
    get_launcher_storage_dir()


def _on_main_addon_missing():
    if HEADLESS_MODE_ENABLED:
        raise RuntimeError("Failed to import required AYON core addon.")
    show_startup_error(
        "Missing core addon",
        (
            "AYON-launcher requires AYON core addon to be able to start."
            "<br/><br/>Please contact your administrator"
            " to resolve the issue."
        )
    )
    sys.exit(1)


def _on_main_addon_import_error(exception):
    if HEADLESS_MODE_ENABLED:
        raise RuntimeError(
            "Failed to import AYON core addon. Probably because"
            " of missing or incompatible dependency package"
        )
    show_startup_error(
        "Incompatible Dependency package",
        (
            "Dependency package is missing or incompatible with available"
            " addons."
            "<br/><br/>Please contact your administrator"
            " to resolve the issue."
        ),
        str(exception)
    )
    sys.exit(1)


def process_uri():
    if len(sys.argv) <= 1:
        return False

    uri = sys.argv[-1].strip('"')

    parsed_uri = urlparse(uri)
    if parsed_uri.scheme != "ayon-launcher":
        return False

    # NOTE This is expecting only single option of ayon-launcher launch option
    #   which is ayon-launcher://action/?server_url=...&token=...
    parsed_query = parse_qs(parsed_uri.query)

    server_url = parsed_query["server_url"][0]
    uri_token = parsed_query["token"][0]
    # Use raw requests to get all necessary information from server
    data = take_web_action_event(server_url, uri_token)
    username = data.get("userName")

    os.environ[SERVER_URL_ENV_KEY] = server_url
    token = load_token(server_url)
    if token:
        os.environ[SERVER_API_ENV_KEY] = token

    try:
        _connect_to_ayon_server(username=username)
    except SystemExit:
        try:
            # There is a bug in ayon-python-api 1.0.10
            # abort_web_action_event(
            #     server_url,
            #     uri_token,
            #     "User skipped login in AYON launcher.",
            # )
            requests.post(
                f"{server_url}/api/actions/abort/{uri_token}",
                json={"message": "User skipped login in AYON launcher."},
            )
        except Exception:
            # Silently ignore any exception, only print traceback
            traceback.print_exception(*sys.exc_info())
        raise

    event_id = data["eventId"]
    variant = data["variant"]

    # Cleanup environemnt variables
    env = os.environ.copy()
    # Remove all possible clash env keys
    for key in {
        "AYON_API_KEY",
        "AYON_USE_STAGING",
        "AYON_USE_DEV",
    }:
        env.pop(key, None)

    # Set new environment variables based on information from server
    if variant == "staging":
        env["AYON_USE_STAGING"] = "1"

    elif variant != "production":
        env["AYON_USE_DEV"] = "1"
        env["AYON_BUNDLE_NAME"] = variant

    # We're always in logic mode when running URI
    env["AYON_IN_LOGIN_MODE"] = "1"
    # Pass event id to child AYON launcher process
    env["AYON_WA_INTERNAL_EVENT_ID"] = event_id

    # Add executable to args
    uri_args = data["args"]
    args = [sys.executable]
    if not IS_BUILT_APPLICATION:
        args.append(os.path.abspath(__file__))
    args += uri_args

    kwargs = {"env": env}
    low_platform = platform.system().lower()
    if low_platform == "darwin":
        new_args = ["open", "-na", args.pop(0), "--args"]
        new_args.extend(args)
        args = new_args

    elif low_platform == "windows":
        flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | subprocess.DETACHED_PROCESS
        )
        kwargs["creationflags"] = flags

        if not sys.stdout:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL

    process = subprocess.Popen(args, **kwargs)
    # Make sure process is running
    # NOTE there might be a better way to do it?
    for _ in range(5):
        if process.pid is not None:
            break
        time.sleep(0.1)
    return True


@contextmanager
def webaction_event_handler():
    # Remove internal event id from environment and set it to
    #  'AYON_WEBACTION_EVENT_ID' for addon who is handling it
    # Reason: Environment 'AYON_WA_INTERNAL_EVENT_ID' is used to pass event id
    #   from process uri to child launcher and 'AYON_WEBACTION_EVENT_ID' can
    #   used in the logic triggered from webaction. Point is that
    #   'AYON_WA_INTERNAL_EVENT_ID' is used only in single AYON launcher
    #   process and is not handled by multiple different processes.
    event_id = os.environ.pop("AYON_WA_INTERNAL_EVENT_ID", None)
    if event_id:
        os.environ["AYON_WEBACTION_EVENT_ID"] = event_id

    def finish_event(success):
        if not event_id:
            return

        try:
            event = get_event(event_id)
            if not event:
                return
            if event["status"] == "in_progress":
                new_status = "finished" if success else "failed"
                update_event(event_id, status=new_status)
        except Exception:
            # Silently ignore any exception, only print traceback
            traceback.print_exception(*sys.exc_info())

    try:
        yield
    except SystemExit as exc:
        finish_event(exc.code == 0)
        raise
    except BaseException:
        finish_event(False)
        raise
    else:
        finish_event(True)



def main_cli():
    """Main startup logic.

    This is the main entry point for the AYON launcher. At this
    moment is fully dependent on 'ayon_core' addon. Which means it
    contains more logic than it should.
    """
    try:
        import ayon_core  # noqa F401
    except ModuleNotFoundError:
        _on_main_addon_missing()

    try:
        from ayon_core import cli
    except ImportError as exc:
        traceback.print_exception(*sys.exc_info())
        _on_main_addon_import_error(exc)

    # print info when not running scripts defined in 'silent commands'
    if not SKIP_HEADERS:
        info = get_info(is_staging_enabled(), is_dev_mode_enabled())
        info.insert(0, f">>> Using AYON from [ {AYON_ROOT} ]")

        try:
            t_width = os.get_terminal_size().columns - 2
        except (ValueError, OSError):
            t_width = 20

        _header = f"*** AYON [{__version__}] "
        info.insert(0, _header + "-" * (t_width - len(_header)))

        for i in info:
            _print(i)

    try:
        cli.main()
    except Exception:  # noqa
        exc_info = sys.exc_info()
        _print("!!! AYON crashed:")
        traceback.print_exception(*exc_info)
        sys.exit(1)


class StartArgScript:
    def __init__(self, argument, script_path):
        self.argument = argument
        self.script_path = script_path

    @property
    def is_valid(self):
        return self.script_path is not None

    @property
    def is_dir(self):
        if self.argument:
            return os.path.isdir(self.argument)
        return False

    @classmethod
    def from_args(cls, args):
        """Get path argument from args and check if they can be started.

        Args:
            args (Iterable[str]): Arguments passed to AYON.

        Returns:
            StartArgScript: Object containing argument and script path.
        """

        if len(args) < 2:
            return cls(None, None)
        path = args[1]
        if os.path.exists(path):
            if os.path.isdir(path):
                new_path = os.path.join(path, "__main__.py")
                if os.path.exists(new_path):
                    return cls(path, new_path)
            else:
                path_ext = os.path.splitext(path)[1].lower()
                if path_ext in (".py", ".pyd", ".pyw", ".pyc"):
                    return cls(path, path)
        return cls(path, None)


def script_cli(start_arg=None):
    """Run and execute script."""

    if start_arg is None:
        start_arg = StartArgScript.from_args(sys.argv)

    # Remove first argument from sys.argv
    # - start.py when running from code
    # - ayon executable when running from build
    sys.argv.pop(0)

    # Find '__main__.py' in directory
    if not start_arg.is_valid:
        if not start_arg.argument:
            raise RuntimeError("No script to run")

        if start_arg.is_dir:
            raise RuntimeError(
                f"Can't find '__main__' module in '{start_arg.argument}'")
        raise RuntimeError(f"Can't find script to run '{start_arg.argument}'")
    filepath = start_arg.script_path

    # Add parent dir to sys path
    sys.path.insert(0, os.path.dirname(filepath))

    # Read content and execute
    with open(filepath, "r") as stream:
        content = stream.read()

    script_globals = dict(globals())
    script_globals["__file__"] = filepath
    exec(compile(content, filepath, "exec"), script_globals)


def get_info(use_staging=None, use_dev=None) -> list:
    """Print additional information to console."""

    inf = []
    project_bundle_name = os.getenv("AYON_BUNDLE_NAME")
    studio_bundle_name = os.getenv("AYON_STUDIO_BUNDLE_NAME")

    variant = "production"
    if use_dev:
        variant = "dev ({})".format(project_bundle_name)
    elif use_staging:
        variant = "staging"
    inf.append(("AYON variant", variant))
    inf.append(("AYON project bundle", project_bundle_name))
    inf.append(("AYON studio bundle", studio_bundle_name))

    # NOTE add addons information

    maximum = max(len(i[0]) for i in inf)
    formatted = []
    for info in inf:
        padding = (maximum - len(info[0])) + 1
        formatted.append(f'... {info[0]}:{" " * padding}[ {info[1]} ]')
    return formatted


def main():
    # AYON launcher was started to initialize itself
    if "init-ayon-launcher" in sys.argv:
        init_launcher_executable(ensure_protocol_is_registered=True)
        sys.exit(0)

    if SHOW_LOGIN_UI:
        if HEADLESS_MODE_ENABLED:
            _print((
                "!!! Invalid arguments combination"
                " '--ayon-login' and '--headless'."
            ))
            sys.exit(1)
        _connect_to_ayon_server(True)

    if process_uri():
        sys.exit(0)

    with webaction_event_handler():
        if SKIP_BOOTSTRAP:
            fill_pythonpath()
            return script_cli()

        boot()

        start_arg = StartArgScript.from_args(sys.argv)
        if start_arg.is_valid:
            script_cli(start_arg)
        else:
            main_cli()


if __name__ == "__main__":
    main()
