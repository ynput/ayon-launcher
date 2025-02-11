import os
import platform
import sys
import json
import subprocess

import appdirs
import semver

IS_BUILT_APPLICATION = getattr(sys, "frozen", False)
CURRENT_PATH = os.path.abspath(__file__)


def get_ayon_appdirs(*args):
    """Local app data directory of AYON launcher.

    Args:
        *args (Iterable[str]): Subdirectories/files in local app data dir.

    Returns:
        str: Path to directory/file in local app data dir.
    """

    return os.path.join(
        appdirs.user_data_dir("AYON", "Ynput"),
        *args
    )


def get_launcher_local_dir(*subdirs: str) -> str:
    """Get local directory for launcher.

    Local directory is used for storing machine or user specific data.

    The location is user specific.

    Note:
        This function should be called at least once on bootstrap.

    Args:
        *subdirs (str): Subdirectories relative to local dir.

    Returns:
        str: Path to local directory.

    """
    storage_dir = os.getenv("AYON_LAUNCHER_LOCAL_DIR")
    if not storage_dir:
        storage_dir = get_ayon_appdirs()
        os.environ["AYON_LAUNCHER_LOCAL_DIR"] = storage_dir

    return os.path.join(storage_dir, *subdirs)


# Store executables info to a file
def get_executables_info_filepath():
    """Get path to file where information about executables is stored.

    Returns:
        str: Path to json file where executables info are stored.
    """

    return get_launcher_local_dir("executables.json")


def get_executables_info():
    filepath = get_executables_info_filepath()
    data = {
        "file_version": "1.0.1",
        "available_versions": []
    }
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as stream:
                data = json.load(stream)

        except Exception:
            pass

    return data


def load_version_from_file(filepath):
    """Execute python file and return '__version__' variable."""

    with open(filepath, "r") as stream:
        version_content = stream.read()
    version_globals = {}
    exec(version_content, version_globals)
    return version_globals["__version__"]


def load_version_from_root(root):
    """Get version of executable.

    Args:
        root (str): Path to executable.

    Returns:
        Union[str, None]: Version of executable.
    """

    version = None
    if not root or not os.path.exists(root):
        return version

    version_filepath = os.path.join(root, "version.py")
    if os.path.exists(version_filepath):
        try:
            version = load_version_from_file(version_filepath)
        except Exception as exc:
            print("Failed lo load version file {}. {}".format(
                version_filepath, exc))

    return version


def load_executable_version(executable):
    """Get version of executable.

    Args:
        executable (str): Path to executable.

    Returns:
        Union[str, None]: Version of executable.
    """

    if not executable:
        return None
    return load_version_from_root(os.path.dirname(executable))


class Executable:
    def __init__(self, path, version):
        self.path = path
        self.version = version
        self._exists = None
        self._semver_version = None

    def __repr__(self):
        return f"AYON Executable ({self.version}): '{self.path}'"

    def __eq__(self, other):
        return self.semver_version == other.semver_version

    def __lt__(self, other):
        return self.semver_version < other.semver_version

    def __gt__(self, other):
        return self.semver_version > other.semver_version

    def __ge__(self, other):
        return self.semver_version >= other.semver_version

    def __le__(self, other):
        return self.semver_version <= other.semver_version

    @property
    def exists(self):
        if self._exists is None:
            self._exists = os.path.exists(self.path)
        return self._exists

    @property
    def semver_version(self):
        if self._semver_version is None:
            try:
                self._semver_version = semver.VersionInfo.parse(self.version)
            except Exception:
                self._semver_version = semver.VersionInfo.parse("0.0.0")
        return self._semver_version


def main():
    executables_info = get_executables_info()

    executables = []
    for version_info in executables_info["available_versions"]:
        executable = version_info["executable"]
        version = load_executable_version(executable)
        executable = Executable(executable, version)
        if executable.exists:
            executables.append(executable)

    if not executables:
        raise RuntimeError(
            "Shim was not able to locate any AYON launcher executables."
        )
    executables.sort()
    executable = executables[-1]

    # Split dir and filename
    # - decide if filename should be 'ayon_console.exe' for windows
    #   other platforms have only 'ayon' executable
    executable_dir, executable_filename = os.path.split(executable.path)
    if (
        platform.system().lower() == "windows"
        and (
            not IS_BUILT_APPLICATION
            or "ayon_console" in os.path.basename(sys.argv[0])
        )
    ):
        executable_filename = "ayon_console.exe"

    executable_path = os.path.join(executable_dir, executable_filename)

    # Change first argument to executable path
    # - replace shim executable when running from build
    # - replace start python script path when running from code
    args = list(sys.argv)
    args[0] = executable_path
    sys.exit(subprocess.call(args))


if __name__ == "__main__":
    main()
