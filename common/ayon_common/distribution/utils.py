import os
import json
import subprocess
import tempfile

from ayon_common.utils import get_launcher_storage_dir, get_ayon_launch_args


def get_addons_dir():
    """Directory where addon packages are stored.

    Path to addons is defined using python module 'appdirs' which

    The path is stored into environment variable 'AYON_ADDONS_DIR'.
    Value of environment variable can be overriden, but we highly recommended
    to use that option only for development purposes.

    Returns:
        str: Path to directory where addons should be downloaded.
    """

    addons_dir = os.environ.get("AYON_ADDONS_DIR")
    if not addons_dir:
        addons_dir = get_launcher_storage_dir(
            "addons", create=True
        )
        os.environ["AYON_ADDONS_DIR"] = addons_dir
    return addons_dir


def get_dependencies_dir():
    """Directory where dependency packages are stored.

    Path to addons is defined using python module 'appdirs' which

    The path is stored into environment variable 'AYON_DEPENDENCIES_DIR'.
    Value of environment variable can be overriden, but we highly recommended
    to use that option only for development purposes.

    Returns:
        str: Path to directory where dependency packages should be downloaded.
    """

    dependencies_dir = os.environ.get("AYON_DEPENDENCIES_DIR")
    if not dependencies_dir:
        dependencies_dir = get_launcher_storage_dir(
            "dependency_packages", create=True
        )
        os.environ["AYON_DEPENDENCIES_DIR"] = dependencies_dir
    return dependencies_dir


def show_missing_permissions():
    print("TODO implement 'show_missing_permissions' function")


def show_missing_bundle_information(url, bundle_name=None, username=None):
    """Show missing bundle information window.

    This function should be called when server does not have set bundle for
    production or staging, or when bundle that should be used is not available
    on server.

    Using subprocess to show the dialog. Is blocking and is waiting until
    dialog is closed.

    Args:
        url (str): Server url where bundle is not set.
        bundle_name (Optional[str]): Name of bundle that was not found.
        username (Optional[str]): Username. Is used only when dev mode is
            enabled.
    """

    ui_dir = os.path.join(os.path.dirname(__file__), "ui")
    script_path = os.path.join(ui_dir, "missing_bundle_window.py")
    args = get_ayon_launch_args(script_path, "--skip-bootstrap", "--url", url)
    if bundle_name:
        args.extend(["--bundle", bundle_name])
    if username:
        args.extend(["--user", username])
    subprocess.call(args)


def show_installer_issue_information(message, installer_path=None):
    """Show a message that something went wrong during installer distribution.

    This will trigger a subprocess with UI message dialog.

    Args:
        message (str): Error message with description of an issue.
        installer_path (Optional[str]): Path to installer file so user can
            try to install it manually.
    """

    ui_dir = os.path.join(os.path.dirname(__file__), "ui")
    script_path = os.path.join(ui_dir, "installer_distribution_error.py")

    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False
    ) as tmp:
        filepath = tmp.name
    with open(filepath, "w") as stream:
        json.dump(
            {"message": message, "installer_path": installer_path},
            stream
        )

    args = get_ayon_launch_args(script_path, "--skip-bootstrap", filepath)
    subprocess.call(args)
    if os.path.exists(filepath):
        os.remove(filepath)


class UpdateWindowManager:
    def __init__(self):
        self._process = None

    def __enter__(self):
        self.start()
        try:
            yield
        finally:
            self.stop()

    def start(self):
        ui_dir = os.path.join(os.path.dirname(__file__), "ui")
        script_path = os.path.join(ui_dir, "update_window.py")

        args = get_ayon_launch_args(script_path, "--skip-bootstrap")
        self._process = subprocess.Popen(args)

    def stop(self):
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.kill()
        self._process = None
