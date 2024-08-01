# -*- coding: utf-8 -*-
"""Main entry point for AYON command.

Bootstrapping process of AYON.

This script is responsible for setting up the environment and
bootstraping AYON. It is also responsible for updating AYON
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

After bootstrap process AYON launcher will start 'openpype' addon. This addon
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
    - AYON_ADDONS_DIR - path to AYON addons directory
    - AYON_DEPENDENCIES_DIR - path to AYON dependencies directory

OpenPype environment variables set during bootstrap
for backward compatibility:
    - PYBLISH_GUI - default pyblish UI tool - will be removed in future
    - USE_AYON_SERVER - tells openpype addon to run in AYON mode
    - AVALON_LABEL - label for AYON menu
    - OPENPYPE_VERSION - version of OpenPype addon
    - OPENPYPE_USE_STAGING - set to '1' if staging mode is enabled
    - OPENPYPE_DEBUG - set to '1' if debug mode is enabled
    - OPENPYPE_HEADLESS_MODE - set to '1' if headless mode is enabled
    - OPENPYPE_EXECUTABLE - path to OpenPype executable
    - OPENPYPE_ROOT - path to OpenPype root directory
    - OPENPYPE_REPOS_ROOT - path to OpenPype repos root directory
    - OPENPYPE_LOG_LEVEL - log level for OpenPype

Some of the environment variables are not in this script but in 'ayon_common'
module.
- Function 'create_global_connection' can change 'AYON_USE_DEV' and
    'AYON_USE_STAGING'.
- Distribution logic can set 'AYON_ADDONS_DIR' and 'AYON_DEPENDENCIES_DIR'
    if are not set yet.
"""

import os
import platform
import sys
import site
import time
import traceback
import contextlib
import subprocess
from urllib.parse import urlparse, parse_qs

from version import __version__

ORIGINAL_ARGS = list(sys.argv)

PREVIOUS_AYON_VERSION = os.getenv("AYON_VERSION", "")

os.environ["AYON_VERSION"] = __version__

# Define which bundle is used
if "--bundle" in sys.argv:
    idx = sys.argv.index("--bundle")
    sys.argv.pop(idx)
    if idx >= len(sys.argv):
        raise RuntimeError((
            "Expect value after \"--bundle\" argument."
        ))
    os.environ["AYON_BUNDLE_NAME"] = sys.argv.pop(idx)

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

    os.environ["OPENPYPE_LOG_LEVEL"] = str(log_level)
    os.environ["AYON_LOG_LEVEL"] = str(log_level)

# Enable debug mode, may affect log level if log level is not defined
if "--debug" in sys.argv:
    sys.argv.remove("--debug")
    os.environ["AYON_DEBUG"] = "1"
    os.environ["OPENPYPE_DEBUG"] = "1"

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
    os.environ["OPENPYPE_USE_STAGING"] = "1"

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
    #   will not set 'AYON_IN_LOGIN_MODE' environment variable. Therefore
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
            int(value)
            for idx, value in enumerate(version_parts)
            if idx < 3
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
    os.environ["OPENPYPE_HEADLESS_MODE"] = "1"
    sys.argv.remove("--headless")

elif (
    os.getenv("AYON_HEADLESS_MODE") != "1"
    or os.getenv("OPENPYPE_HEADLESS_MODE") != "1"
):
    os.environ.pop("AYON_HEADLESS_MODE", None)
    os.environ.pop("OPENPYPE_HEADLESS_MODE", None)

elif (
    os.getenv("AYON_HEADLESS_MODE")
    != os.getenv("OPENPYPE_HEADLESS_MODE")
):
    os.environ["OPENPYPE_HEADLESS_MODE"] = (
        os.environ["AYON_HEADLESS_MODE"]
    )

IS_BUILT_APPLICATION = getattr(sys, "frozen", False)
HEADLESS_MODE_ENABLED = os.getenv("AYON_HEADLESS_MODE") == "1"
AYON_IN_LOGIN_MODE = os.environ["AYON_IN_LOGIN_MODE"] == "1"

_pythonpath = os.getenv("PYTHONPATH", "")
_python_paths = _pythonpath.split(os.pathsep)
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
sys.path.append(_dependencies_path)
_python_paths.append(_dependencies_path)

# Add common package to PYTHONPATH
# - common contains common code and bootstrap logic (like connection and bootstrap)
common_path = os.path.join(AYON_ROOT, "common")
sys.path.insert(0, common_path)
if common_path in _python_paths:
    _python_paths.remove(common_path)
_python_paths.insert(0, common_path)

# Vendored python modules that must not be in PYTHONPATH environment but
#   are required for OpenPype processes
sys.path.insert(0, os.path.join(AYON_ROOT, "vendor", "python"))

os.environ["PYTHONPATH"] = os.pathsep.join(_python_paths)

# enabled AYON state
os.environ["USE_AYON_SERVER"] = "1"
# Set this to point either to `python` from venv in case of live code
#    or to `ayon` or `ayon_console` in case of frozen code
os.environ["AYON_EXECUTABLE"] = sys.executable
os.environ["OPENPYPE_EXECUTABLE"] = sys.executable
os.environ["AYON_ROOT"] = AYON_ROOT
os.environ["OPENPYPE_ROOT"] = AYON_ROOT
os.environ["OPENPYPE_REPOS_ROOT"] = AYON_ROOT
os.environ["AYON_MENU_LABEL"] = "AYON"
os.environ["AVALON_LABEL"] = "AYON"

import blessed  # noqa: E402
import certifi  # noqa: E402
import requests


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


# if SSL_CERT_FILE is not set prior to OpenPype launch, we set it to point
# to certifi bundle to make sure we have reasonably new CA certificates.
if not os.getenv("SSL_CERT_FILE"):
    os.environ["SSL_CERT_FILE"] = certifi.where()
elif os.getenv("SSL_CERT_FILE") != certifi.where():
    _print("--- your system is set to use custom CA certificate bundle.")

from ayon_api import (
    get_base_url,
    set_default_settings_variant,
    get_addons_studio_settings,
)
from ayon_api.constants import (
    SERVER_URL_ENV_KEY,
    SERVER_API_ENV_KEY,
    DEFAULT_VARIANT_ENV_KEY,
    SITE_ID_ENV_KEY,
)
from ayon_common import is_staging_enabled, is_dev_mode_enabled
from ayon_common.connection.credentials import (
    ask_to_login_ui,
    add_server,
    need_server_or_login,
    load_environments,
    set_environments,
    create_global_connection,
    confirm_server_login,
    show_invalid_credentials_ui,
)
from ayon_common.distribution import (
    AyonDistribution,
    BundleNotFoundError,
    show_missing_bundle_information,
    show_installer_issue_information,
    UpdateWindowManager,
)

from ayon_common.utils import (
    store_current_executable_info,
    deploy_ayon_launcher_shims,
    get_local_site_id,
)
from ayon_common.startup import show_startup_error


def set_global_environments() -> None:
    """Set global OpenPype's environments."""
    import acre

    from openpype.settings import get_general_environments

    general_env = get_general_environments()

    # first resolve general environment because merge doesn't expect
    # values to be list.
    # TODO: switch to OpenPype environment functions
    merged_env = acre.merge(
        acre.compute(acre.parse(general_env), cleanup=False),
        dict(os.environ)
    )
    env = acre.compute(
        merged_env,
        cleanup=False
    )
    os.environ.clear()
    os.environ.update(env)

    # Hardcoded default values
    os.environ["PYBLISH_GUI"] = "pyblish_pype"
    # Change scale factor only if is not set
    if "QT_AUTO_SCREEN_SCALE_FACTOR" not in os.environ:
        os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"


def set_addons_environments():
    """Set global environments for OpenPype modules.

    This requires to have OpenPype in `sys.path`.
    """

    import acre
    from openpype.modules import ModulesManager

    modules_manager = ModulesManager()

    # Merge environments with current environments and update values
    if module_envs := modules_manager.collect_global_environments():
        parsed_envs = acre.parse(module_envs)
        env = acre.merge(parsed_envs, dict(os.environ))
        os.environ.clear()
        os.environ.update(env)


def _connect_to_ayon_server(force=False):
    """Connect to AYON server.

    Load existing credentials to AYON server, and show login dialog if are not
        valid. When 'force' is set to 'True' then login dialog is always
        shown.

    Login dialog cannot be shown in headless mode. In that case program
        is terminated with.
    If user closed dialog, program is terminated with exit code 0.

    Args:
        force (Optional[bool]): Force login to server.
    """

    if force and HEADLESS_MODE_ENABLED:
        _print("!!! Login UI was requested in headless mode.")
        sys.exit(1)

    load_environments()
    need_server = need_api_key = True
    if not force:
        need_server, need_api_key = need_server_or_login()

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
    url, token, username = ask_to_login_ui(current_url, always_on_top=True)
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
        os.environ.pop("OPENPYPE_USE_STAGING", None)
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
    distribution = AyonDistribution(
        skip_installer_dist=not IS_BUILT_APPLICATION
    )
    bundle = None
    bundle_name = None
    # Try to find required bundle and handle missing one
    try:
        bundle = distribution.bundle_to_use
        if bundle is not None:
            bundle_name = bundle.name
    except BundleNotFoundError as exc:
        bundle_name = exc.bundle_name

    if bundle is None:
        url = get_base_url()
        username = distribution.active_user
        if bundle_name:
            _print((
                f"!!! Requested release bundle '{bundle_name}'"
                " is not available on server."
            ))
            _print(
                "!!! Check if selected release bundle"
                f" is available on the server '{url}'."
            )

        else:
            mode = "production"
            if distribution.use_dev:
                mode = f"dev for user '{username}'"
            elif distribution.use_staging:
                mode = "staging"

            _print(
                f"!!! No release bundle is set as {mode} on the AYON server."
            )
            _print(
                "!!! Make sure there is a release bundle set"
                f" as \"{mode}\" on the AYON server '{url}'."
            )


        if not HEADLESS_MODE_ENABLED:
            show_missing_bundle_information(url, bundle_name, username)

        sys.exit(1)

    # With known bundle and states we can define default settings variant
    #   in global connection
    _set_default_settings_variant(
        distribution.use_dev,
        distribution.use_staging,
        bundle_name
    )
    _run_disk_mapping(bundle_name)

    # Start distribution
    update_window_manager = UpdateWindowManager()
    if not HEADLESS_MODE_ENABLED:
        update_window_manager.start()

    try:
        distribution.distribute()
    finally:
        update_window_manager.stop()

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
        # TODO figure out how this should be launched
        #   - it can technically cause infinite loop of subprocesses
        sys.exit(subprocess.call(args))

    # TODO check failed distribution and inform user
    distribution.validate_distribution()
    os.environ["AYON_BUNDLE_NAME"] = bundle_name

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


def init_launcher_executable():
    """Initialize AYON launcher executable.

    Make sure current AYON launcher executable is stored to known executables
        and shim is deployed.

    """
    create_desktop_icons = "--create-desktop-icons" in sys.argv
    store_current_executable_info()
    deploy_ayon_launcher_shims(create_desktop_icons=create_desktop_icons)


def boot():
    """Bootstrap AYON launcher."""
    init_launcher_executable()

    # Setup site id in environment variable for all possible subprocesses
    if SITE_ID_ENV_KEY not in os.environ:
        os.environ[SITE_ID_ENV_KEY] = get_local_site_id()

    _connect_to_ayon_server()
    create_global_connection()
    _start_distribution()


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


def _main_cli_openpype():
    try:
        from openpype import PACKAGE_DIR
    except ImportError:
        _on_main_addon_missing()

    try:
        from openpype import cli
    except ImportError as exc:
        traceback.print_exception(*sys.exc_info())
        _on_main_addon_import_error(exc)

    python_path = os.getenv("PYTHONPATH", "")
    split_paths = python_path.split(os.pathsep)

    # TODO move to ayon core import
    additional_paths = [
        # add OpenPype tools
        os.path.join(PACKAGE_DIR, "tools"),
        # add common OpenPype vendor
        # (common for multiple Python interpreter versions)
        os.path.join(PACKAGE_DIR, "vendor", "python", "common")
    ]
    for path in additional_paths:
        if path not in split_paths:
            split_paths.insert(0, path)
        if path not in sys.path:
            sys.path.insert(0, path)
    os.environ["PYTHONPATH"] = os.pathsep.join(split_paths)

    _print(">>> loading environments ...")
    _print("  - global AYON ...")
    set_global_environments()
    _print("  - for addons ...")
    set_addons_environments()

    # print info when not running scripts defined in 'silent commands'
    if not SKIP_HEADERS:
        info = get_info(is_staging_enabled(), is_dev_mode_enabled())
        info.insert(0, f">>> Using AYON from [ {AYON_ROOT} ]")

        t_width = 20
        with contextlib.suppress(ValueError, OSError):
            t_width = os.get_terminal_size().columns - 2

        _header = f"*** AYON [{__version__}] "
        info.insert(0, _header + "-" * (t_width - len(_header)))

        for i in info:
            _print(i)

    try:
        cli.main(obj={}, prog_name="ayon")
    except Exception:  # noqa
        exc_info = sys.exc_info()
        _print("!!! AYON crashed:")
        traceback.print_exception(*exc_info)
        sys.exit(1)


def process_uri():
    if len(sys.argv) <= 1:
        return False

    uri = sys.argv[-1].strip('"')

    parsed_uri = urlparse(uri)
    if parsed_uri.scheme != "ayon-launcher":
        return False

    # NOTE This is expecting only singlo option of ayon-launcher launch option
    #   which is ayon-launcher://action/?server_url=...&token=...
    parsed_query = parse_qs(parsed_uri.query)

    server_url = parsed_query["server_url"][0]
    token = parsed_query["token"][0]
    # Use raw requests to get all necessary information from server
    response = requests.get(f"{server_url}/api/actions/take/{token}")
    # TODO validate response
    data = response.json()
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


def main_cli():
    """Main startup logic.

    This is the main entry point for the AYON launcher. At this
    moment is fully dependent on 'ayon_core' addon. Which means it
    contains more logic than it should.
    """

    try:
        import ayon_core
        ayon_core_used = True
    except ImportError:
        ayon_core_used = False

    if not ayon_core_used:
        return _main_cli_openpype()

    try:
        from ayon_core import cli
    except ImportError as exc:
        traceback.print_exception(*sys.exc_info())
        _on_main_addon_import_error(exc)

    # print info when not running scripts defined in 'silent commands'
    if not SKIP_HEADERS:
        info = get_info(is_staging_enabled(), is_dev_mode_enabled())
        info.insert(0, f">>> Using AYON from [ {AYON_ROOT} ]")

        t_width = 20
        with contextlib.suppress(ValueError, OSError):
            t_width = os.get_terminal_size().columns - 2

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
        """Get path argument from args and check if can be started.

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
    bundle_name = os.getenv("AYON_BUNDLE_NAME")

    variant = "production"
    if use_dev:
        variant = "dev ({})".format(bundle_name)
    elif use_staging:
        variant = "staging"
    inf.append(("AYON variant", variant))
    inf.append(("AYON bundle", bundle_name))

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
        init_launcher_executable()
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

    if SKIP_BOOTSTRAP:
        return script_cli()

    boot()

    start_arg = StartArgScript.from_args(sys.argv)
    if start_arg.is_valid:
        script_cli(start_arg)
    else:
        main_cli()


if __name__ == "__main__":
    main()
