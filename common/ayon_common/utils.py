import os
import sys
import platform
import json
import datetime
import subprocess
import zipfile
import tarfile
import warnings
import shutil
from uuid import UUID
from typing import Optional, Iterable, List, Dict, Tuple, Any

import appdirs
import semver
from ayon_api.constants import SITE_ID_ENV_KEY

DATE_FMT = "%Y-%m-%d %H:%M:%S"
CLEANUP_INTERVAL = 2  # days
IS_BUILT_APPLICATION = getattr(sys, "frozen", False)
HEADLESS_MODE_ENABLED = os.getenv("AYON_HEADLESS_MODE") == "1"
# UUID of the default Windows download folder
WIN_DOWNLOAD_FOLDER_ID = UUID("{374DE290-123F-4565-9164-39C4925E467B}")
IMPLEMENTED_ARCHIVE_FORMATS = {
    ".zip", ".tar", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"
}

ExecutablesInfo = Dict[str, Any]


def _get_ayon_appdirs(*args):
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


def get_ayon_appdirs(*args):
    """Local app data directory of AYON launcher.

    Deprecated:
        The function was replaced with 'get_launcher_local_dir'
            or 'get_launcher_storage_dir' based on usage.
        Deprecated since 1.1.0 .

    Args:
        *args (Iterable[str]): Subdirectories/files in local app data dir.

    Returns:
        str: Path to directory/file in local app data dir.

    """
    warnings.warn(
        (
            "Function 'get_ayon_appdirs' is deprecated. Should be replaced"
            " with 'get_launcher_local_dir' or 'get_launcher_storage_dir'"
            " based on use-case."
        ),
        DeprecationWarning
    )
    return _get_ayon_appdirs(*args)


def get_launcher_storage_dir(
    *subdirs: str,
    create: Optional[bool] = False
) -> str:
    """Get storage directory for launcher.

    Storage directory is used for storing shims, addons, dependencies, etc.

    It is not recommended, but the location can be shared across
        multiple machines.

    Note:
        This function should be called at least once on bootstrap.

    Args:
        *subdirs (str): Subdirectories relative to storage dir.
        create (Optional[bool]): Create the folder if it does not exist.

    Returns:
        str: Path to storage directory.

    """
    storage_dir = os.getenv("AYON_LAUNCHER_STORAGE_DIR")
    if not storage_dir:
        storage_dir = _get_ayon_appdirs()
        os.environ["AYON_LAUNCHER_STORAGE_DIR"] = storage_dir

    path = os.path.join(storage_dir, *subdirs)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def get_launcher_local_dir(
    *subdirs: str,
    create: Optional[bool] = False
) -> str:
    """Get local directory for launcher.

    Local directory is used for storing machine or user specific data.

    The location is user specific.

    Note:
        This function should be called at least once on bootstrap.

    Args:
        *subdirs (str): Subdirectories relative to local dir.
        create (Optional[bool]): Create the folder if it does not exist.

    Returns:
        str: Path to local directory.

    """
    storage_dir = os.getenv("AYON_LAUNCHER_LOCAL_DIR")
    if not storage_dir:
        storage_dir = _get_ayon_appdirs()
        os.environ["AYON_LAUNCHER_LOCAL_DIR"] = storage_dir

    path = os.path.join(storage_dir, *subdirs)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def is_staging_enabled() -> bool:
    """Check if staging is enabled.

    Returns:
        bool: True if staging is enabled.

    """
    return os.getenv("AYON_USE_STAGING") == "1"


def is_dev_mode_enabled() -> bool:
    """Check if dev is enabled.

    A dev bundle is used when dev is enabled.

    Returns:
        bool: Dev is enabled.

    """
    return os.getenv("AYON_USE_DEV") == "1"


def _create_local_site_id() -> str:
    """Create a local site identifier.

    Returns:
        str: Randomly generated site id.

    """
    from coolname import generate_slug

    new_id = generate_slug(3)

    print("Created local site id \"{}\"".format(new_id))

    return new_id


def get_local_site_id() -> str:
    """Get local site identifier.

    Site id is created if does not exist yet.

    Returns:
        str: Site id.

    """
    # used for background syncing
    site_id = os.environ.get(SITE_ID_ENV_KEY)
    if site_id:
        return site_id

    site_id_path = get_launcher_local_dir("site_id")
    if os.path.exists(site_id_path):
        with open(site_id_path, "r") as stream:
            site_id = stream.read()

    if not site_id:
        os.makedirs(os.path.dirname(site_id_path), exist_ok=True)
        site_id = _create_local_site_id()
        with open(site_id_path, "w") as stream:
            stream.write(site_id)
    return site_id


def get_ayon_launch_args(*args: str) -> List[str]:
    """Launch arguments that can be used to launch ayon process.

    Args:
        *args (str): Additional arguments.

    Returns:
        list[str]: Launch arguments.

    """
    output = [sys.executable]
    if not IS_BUILT_APPLICATION:
        output.append(os.path.join(os.environ["AYON_ROOT"], "start.py"))
    output.extend(args)
    return output


# Store executables info to a file
def get_executables_info_filepath() -> str:
    """Get path to file where information about executables is stored.

    Returns:
        str: Path to json file where executables info are stored.

    """
    return get_launcher_local_dir("executables.json")


def _get_default_executable_info() -> ExecutablesInfo:
    return {
        "file_version": "1.0.1",
        "available_versions": []
    }


def get_executables_info(
    check_cleanup: Optional[bool] = True
) -> ExecutablesInfo:
    filepath = get_executables_info_filepath()
    if not os.path.exists(filepath):
        return _get_default_executable_info()
    try:
        with open(filepath, "r") as stream:
            data = json.load(stream)

    except Exception:
        return _get_default_executable_info()

    if not check_cleanup:
        return data

    last_cleanup = None
    last_cleanup_info = data.get("last_cleanup")
    if last_cleanup_info:
        try:
            last_cleanup_value = last_cleanup_info["value"]
            last_cleanup_fmt = last_cleanup_info["fmt"]
            last_cleanup = datetime.datetime.strptime(
                last_cleanup_value, last_cleanup_fmt)
        except Exception:
            print("Failed to parse last cleanup timestamp")

    now = datetime.datetime.now()
    if last_cleanup and (now - last_cleanup).days < CLEANUP_INTERVAL:
        return data

    cleanup_executables_info()
    return get_executables_info(check_cleanup=False)


def store_executables_info(info: ExecutablesInfo):
    """Store information about executables.

    This will override existing information so use it wisely.

    """
    filepath = get_executables_info_filepath()
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    with open(filepath, "w") as stream:
        json.dump(info, stream, indent=4)


def load_version_from_file(filepath: str) -> str:
    """Execute python file and return '__version__' variable."""

    with open(filepath, "r") as stream:
        version_content = stream.read()
    version_globals = {}
    exec(version_content, version_globals)
    return version_globals["__version__"]


def load_version_from_root(root: str) -> Optional[str]:
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


def load_executable_version(executable: str) -> Optional[str]:
    """Get version of executable.

    Args:
        executable (str): Path to executable.

    Returns:
        Union[str, None]: Version of executable.

    """
    if not executable:
        return None
    return load_version_from_root(os.path.dirname(executable))


def store_executables(executables: Iterable[str]):
    """Store information about executables.

    Args:
        executables (Iterable[str]): Paths to executables.

    """
    info = get_executables_info(check_cleanup=False)
    info.setdefault("available_versions", [])

    for executable in executables:
        if not executable or not os.path.exists(executable):
            continue

        root, filename = os.path.split(executable)
        # Store only 'ayon.exe' executable
        if filename == "ayon_console.exe":
            filename = "ayon.exe"
            executable = os.path.join(root, filename)

        version = load_version_from_root(root)

        match_item = None
        item_is_new = True
        for item in info["available_versions"]:
            # 'executable' is unique identifier if available versions
            item_executable = item.get("executable")
            if not item_executable or item_executable != executable:
                continue

            # Version has changed, update it
            if item.get("version") != version:
                match_item = item
            item_is_new = False
            break

        if match_item is None:
            if not item_is_new:
                continue
            match_item = {}
            info["available_versions"].append(match_item)

        match_item.update({
            "version": version,
            "executable": executable,
            "added": datetime.datetime.now().strftime("%y-%m-%d-%H%M"),
        })
    store_executables_info(info)


def store_current_executable_info():
    """Store information about current executable to a file for future usage.

    Use information about current executable and version of executable and
    add it to a list of available executables.

    The function won't do anything if the application is not built or if
    version is not set or the executable is already available.

    Todos:
        Don't store executable if is located inside 'ayon-launcher' codebase?

    """
    if not IS_BUILT_APPLICATION:
        return

    store_executables([sys.executable])


def get_executables_info_by_version(
    version: str, validate: Optional[bool] = True
) -> List[Dict[str, Any]]:
    """Get available executable info by version.

    Args:
        version (str): Version of executable.
        validate (bool): Validate if 'version.py' contains same version.

    Returns:
        list[dict[str, Any]]: Executable info matching version.

    """
    info = get_executables_info()
    available_versions = info.setdefault("available_versions", [])
    if validate:
        _available_versions = []
        for item in available_versions:
            executable = item.get("executable")
            if not executable or not os.path.exists(executable):
                continue

            executable_version = load_executable_version(executable)
            if executable_version == version:
                _available_versions.append(item)
        available_versions = _available_versions
    return [
        item
        for item in available_versions
        if item.get("version") == version
    ]


def get_executable_paths_by_version(version: str) -> List[str]:
    """Get executable paths by version.

    Returns:
        list[str]: Paths to executables.

    """
    return [
        item["executable"]
        for item in get_executables_info_by_version(version, validate=True)
    ]


def cleanup_executables_info():
    """Remove executables that do not exist anymore."""

    info = get_executables_info(check_cleanup=False)
    available_versions = info.setdefault("available_versions", [])

    new_executables = []
    for item in available_versions:
        executable = item.get("executable")
        if not executable or not os.path.exists(executable):
            continue

        version = load_executable_version(executable)
        if version and item.get("version") != version:
            item["version"] = version
        new_executables.append(item)

    info["available_versions"] = new_executables
    info["last_cleanup"] = {
        "value": datetime.datetime.now().strftime(DATE_FMT),
        "fmt": DATE_FMT,
    }
    store_executables_info(info)


class _Cache:
    downloads_dir = 0


def _get_linux_downloads_dir() -> str:
    return subprocess.run(
        ["xdg-user-dir", "DOWNLOAD"],
        capture_output=True, text=True
    ).stdout.strip("\n")


def _get_windows_downloads_dir() -> Optional[str]:
    import ctypes
    from ctypes import windll, wintypes

    class GUID(ctypes.Structure):  # [1]
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", wintypes.BYTE * 8)
        ]

        def __init__(self, uuid_):
            ctypes.Structure.__init__(self)
            (
                self.Data1,
                self.Data2,
                self.Data3,
                self.Data4[0],
                self.Data4[1],
                rest
            ) = uuid_.fields
            for i in range(2, 8):
                self.Data4[i] = rest >> (8 - i - 1) * 8 & 0xff

    pathptr = ctypes.c_wchar_p()
    guid = GUID(WIN_DOWNLOAD_FOLDER_ID)
    if windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, 0, ctypes.byref(pathptr)
    ):
        return None
    return pathptr.value


def _get_macos_downloads_dir() -> Optional[str]:
    """Get downloads directory on MacOS.

    Notes:
        By community forum '~/Downloads' is right way, which is default.

    Returns:
        Union[str, None]: Path to downloads directory or None if not found.

    """
    return None


def get_downloads_dir() -> str:
    """Downloads directory path.

    Each platform may use different approach how the downloads directory is
    received. This function will try to find the directory and return it.

    Returns:
        Union[str, None]: Path to downloads directory or None if not found.

    """
    if _Cache.downloads_dir != 0:
        return _Cache.downloads_dir

    path = None
    try:
        platform_name = platform.system().lower()
        if platform_name == "linux":
            path = _get_linux_downloads_dir()
        elif platform_name == "windows":
            path = _get_windows_downloads_dir()
        elif platform_name == "darwin":
            path = _get_macos_downloads_dir()

    except Exception:
        pass

    if path is None:
        default = os.path.expanduser("~/Downloads")
        if os.path.exists(default):
            path = default

    _Cache.downloads_dir = path
    return path


class ZipFileLongPaths(zipfile.ZipFile):
    """Allows longer paths in zip files.

    Regular DOS paths are limited to MAX_PATH (260) characters, including
    the string's terminating NUL character.
    That limit can be exceeded by using an extended-length path that
    starts with the '\\?\' prefix.
    """
    _is_windows = platform.system().lower() == "windows"

    def _extract_member(self, member, tpath, pwd):
        if self._is_windows:
            tpath = os.path.abspath(tpath)
            if tpath.startswith("\\\\"):
                tpath = "\\\\?\\UNC\\" + tpath[2:]
            else:
                tpath = "\\\\?\\" + tpath

        return super()._extract_member(member, tpath, pwd)


def get_archive_ext_and_type(
    archive_file: str
) -> Tuple[Optional[str], Optional[str]]:
    """Get archive extension and type.

    Args:
        archive_file (str): Path to archive file.

    Returns:
        Tuple[str, str]: Archive extension and type.

    """
    tmp_name = archive_file.lower()
    if tmp_name.endswith(".zip"):
        return ".zip", "zip"

    for ext in (
        ".tar",
        ".tgz",
        ".tar.gz",
        ".tar.xz",
        ".tar.bz2",
    ):
        if tmp_name.endswith(ext):
            return ext, "tar"

    return None, None


def extract_archive_file(archive_file: str, dst_folder: Optional[str] = None):
    """Extract archived file to a directory.

    Args:
        archive_file (str): Path to a archive file.
        dst_folder (Optional[str]): Directory where content will be extracted.
            By default, same folder where archive file is.

    """
    if not dst_folder:
        dst_folder = os.path.dirname(archive_file)

    archive_ext, archive_type = get_archive_ext_and_type(archive_file)

    print("Extracting {} -> {}".format(archive_file, dst_folder))
    if archive_type is None:
        _, ext = os.path.splitext(archive_file)
        raise ValueError((
            f"Invalid file extension \"{ext}\"."
            f" Expected {', '.join(IMPLEMENTED_ARCHIVE_FORMATS)}"
        ))

    if archive_type == "zip":
        zip_file = ZipFileLongPaths(archive_file)
        zip_file.extractall(dst_folder)
        zip_file.close()

    elif archive_type == "tar":
        if archive_ext == ".tar":
            tar_type = "r:"
        elif archive_ext.endswith(".xz"):
            tar_type = "r:xz"
        elif archive_ext.endswith(".gz"):
            tar_type = "r:gz"
        elif archive_ext.endswith(".bz2"):
            tar_type = "r:bz2"
        else:
            tar_type = "r:*"

        try:
            tar_file = tarfile.open(archive_file, tar_type)
        except tarfile.ReadError:
            raise SystemExit("corrupted archive")

        tar_file.extractall(dst_folder)
        tar_file.close()


def calculate_file_checksum(
    filepath: str, checksum_algorithm: str, chunk_size: Optional[int]=10000
):
    """Calculate file checksum for given algorithm.

    Args:
        filepath (str): Path to a file.
        checksum_algorithm (str): Algorithm to use. ('md5', 'sha1', 'sha256')
        chunk_size (Optional[int]): Chunk size to read file.
            Defaults to 10000.

    Returns:
        str: Calculated checksum.

    Raises:
        ValueError: File not found or unknown checksum algorithm.

    """
    import hashlib

    if not filepath:
        raise ValueError("Filepath is empty.")

    if not os.path.exists(filepath):
        raise ValueError("{} doesn't exist.".format(filepath))

    if not os.path.isfile(filepath):
        raise ValueError("{} is not a file.".format(filepath))

    func = getattr(hashlib, checksum_algorithm, None)
    if func is None:
        raise ValueError(
            "Unknown checksum algorithm '{}'".format(checksum_algorithm))

    hash_obj = func()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hash_obj.update(chunk)
    return hash_obj.hexdigest()


def validate_file_checksum(
    filepath: str, checksum: str, checksum_algorithm: str
) -> bool:
    """Validate file checksum.

    Args:
        filepath (str): Path to file.
        checksum (str): Hash of file.
        checksum_algorithm (str): Type of checksum.

    Returns:
        bool: Hash is valid/invalid.

    Raises:
        ValueError: File not found or unknown checksum algorithm.

    """
    return checksum == calculate_file_checksum(filepath, checksum_algorithm)


# --- SHIM information ---
# Helpers to resolve registering shim as 'ayon-launcher' protocol handler
def _is_windows_launcher_protocol_registered() -> bool:
    from ._windows_register_scheme import is_reg_set

    return is_reg_set(get_shim_executable_path())


def _register_windows_launcher_protocol() -> bool:
    from ._windows_register_scheme import set_reg

    return set_reg(get_shim_executable_path())


def _get_linux_desktop_file_path() -> str:
    return os.path.expanduser("~/.local/share/applications/ayon.desktop")


def _get_linux_desktop_executable_content() -> str:
    dst_desktop_executable = _get_linux_desktop_file_path()
    executable_root = _get_shim_executable_root()

    desktop_filename = os.path.split(dst_desktop_executable)[-1]
    src_desktop_executable = os.path.join(executable_root, desktop_filename)
    with open(src_desktop_executable, "r") as stream:
        content = (
            stream
            .read()
            .replace("{ayon_exe_root}", executable_root)
        )
    return content


def _is_launcher_launcher_protocol_registered() -> bool:
    # Add 'ayon.desktop' to applications
    desktop_file_path = _get_linux_desktop_file_path()
    # Skip if applications directory does not exist
    # - e.g. on headless linux
    if not os.path.exists(desktop_file_path):
        return False

    new_content = _get_linux_desktop_executable_content()

    with open(desktop_file_path, "r") as stream:
        old_content = stream.read()
    return old_content == new_content


def _register_linux_launcher_protocol() -> bool:
    # Add 'ayon.desktop' to applications
    dst_desktop_file_path = _get_linux_desktop_file_path()
    desktop_filename, apps_dir = os.path.split(dst_desktop_file_path)
    # Skip if applications directory does not exist
    # - e.g. on headless linux
    if not os.path.exists(apps_dir):
        return True

    new_content = _get_linux_desktop_executable_content()

    if os.path.exists(dst_desktop_file_path):
        # Read content for comparison
        with open(dst_desktop_file_path, "r") as stream:
            old_content = stream.read()
    else:
        src_desktop_executable = os.path.join(
            _get_shim_executable_root(), desktop_filename
        )
        # Copy 'ayon.desktop' to applications
        shutil.copy(src_desktop_executable, apps_dir)
        old_content = None

    content_updated = False
    if old_content != new_content:
        content_updated = True
        with open(dst_desktop_file_path, "w") as stream:
            stream.write(new_content)

    # Symlink to desktop if has desktop and does not yet exist
    desktop_root = os.path.expanduser("~/Desktop")
    if os.path.exists(desktop_root):
        desktop_path = os.path.join(desktop_root, desktop_filename)
        if not os.path.exists(desktop_path):
            os.symlink(dst_desktop_file_path, desktop_path)

    # Update desktop database
    # TODO validate if desktop database is updated and somehow show to user?
    # - the installation also happens on headless machines
    if content_updated:
        subprocess.run(["update-desktop-database", apps_dir])
    return True


def is_ayon_launcher_protocol_registered() -> bool:
    platform_name = platform.system().lower()
    if platform_name == "windows":
        return _is_windows_launcher_protocol_registered()
    elif platform_name == "linux":
        return _is_launcher_launcher_protocol_registered()
    # macOs have registered protocol by having AYON shim in '/Applications'
    return os.path.exists(get_shim_executable_path())


def register_ayon_launcher_protocol() -> bool:
    platform_name = platform.system().lower()
    if platform_name == "windows":
        return _register_windows_launcher_protocol()
    elif platform_name == "linux":
        return _register_linux_launcher_protocol()
    # macOs has registered protocol by having AYON shim in /Applications
    return True


def _get_shim_executable_root() -> str:
    """Root to shim executable.

    Returns:
        str: Path to root or shim executable.

    """
    platform_name = platform.system().lower()
    if platform_name in ("windows", "linux"):
        return get_launcher_local_dir("shim")
    return "/Applications/AYON.app/Contents/MacOS"


def get_shim_executable_path() -> str:
    """Path to shim executable.

    It is not validated if shim exists.

    Returns:
        str: Path where shim executable should be found.

    """
    filename = "ayon"
    if platform.system().lower() == "windows":
        filename += ".exe"
    return os.path.join(_get_shim_executable_root(), filename)


def _get_installed_shim_version() -> str:
    """Get installed shim version.

    Returns:
        str: Shim version. When shim is not installed, '0.0.0' is returned.

    """
    version_root = _get_shim_executable_root()
    dst_shim_version = "0.0.0"
    if platform.system().lower() == "darwin":
        contents_dir = os.path.dirname(version_root)
        version_root = os.path.join(contents_dir, "Resources")

    dst_shim_version_path = os.path.join(version_root, "version")
    if os.path.exists(dst_shim_version_path):
        with open(dst_shim_version_path, "r") as stream:
            dst_shim_version = stream.read().strip()
    return dst_shim_version


def _deploy_shim_windows(
    installer_shim_root: str,
    create_desktop_icons: bool
) -> bool:
    """Deploy shim executable on Windows.

    Windows shim is deployed using exe installer.

    Args:
        installer_shim_root (str): Path to installer root.
        create_desktop_icons (bool): Create icon shortcuts.

    """
    args = [
        os.path.join(installer_shim_root, "shim.exe"),
        "/CURRENTUSER",
        "/NOCANCEL",
    ]
    if not HEADLESS_MODE_ENABLED:
        args.append("/SILENT")
    else:
        args.append("/VERYSILENT")

    if create_desktop_icons:
        args.append("/TASKS=desktopicon")
    code = subprocess.call(args)
    return code == 0


def _deploy_shim_linux(installer_shim_root: str) -> bool:
    """Deploy shim executable on Linux.

    Linux shim is deployed using zip file exported to appdirs.

    Args:
        installer_shim_root (str): Path to installer root.

    """
    executable_root = _get_shim_executable_root()
    os.makedirs(executable_root, exist_ok=True)
    extract_archive_file(
        os.path.join(installer_shim_root, "shim.tar.gz"),
        executable_root
    )
    return True


def _deploy_shim_macos(installer_shim_root: str):
    """Deploy shim executable on macOS.

    MacOS shim is deployed using dmg file exported to '/Applications'.

    Args:
        installer_shim_root (str): Path to installer root.

    """
    import plistlib

    filepath = os.path.join(installer_shim_root, "shim.dmg")
    # Attach dmg file and read plist output (bytes)
    stdout = subprocess.check_output([
        "hdiutil", "attach", filepath, "-plist", "-nobrowse"
    ])
    hdi_mounted_volume = None
    try:
        # Parse plist output and find mounted volume
        attach_info = plistlib.loads(stdout)
        mounted_volumes = []
        for entity in attach_info["system-entities"]:
            mounted_volume = entity.get("mount-point")
            if mounted_volume:
                mounted_volumes.append(mounted_volume)

        # We do expect there is only one .app in .dmg file
        src_path = None
        for mounted_volume in mounted_volumes:
            for filename in os.listdir(mounted_volume):
                if filename.endswith(".app"):
                    hdi_mounted_volume = mounted_volume
                    src_path = os.path.join(mounted_volume, filename)
                    break

        # Copy the .app file to /Applications
        dst_dir = "/Applications"
        subprocess.run(["cp", "-rf", src_path, dst_dir])

    finally:
        # Detach mounted volume
        if hdi_mounted_volume:
            subprocess.run(["hdiutil", "detach", hdi_mounted_volume])


def deploy_ayon_launcher_shims(
    create_desktop_icons: Optional[bool] = False,
    ensure_protocol_is_registered: Optional[bool] = False,
):
    """Deploy shim executables for AYON launcher.

    Argument 'validate_registers' is to fix registered protocol on Windows,
        issue caused in v1.1.0, since 1.1.1 is used different registry path.

    Args:
        create_desktop_icons (Optional[bool]): Create desktop shortcuts. Used
            only on windows.
        ensure_protocol_is_registered (Optional[bool]): Validate if protocol is
            registered on windows.

    """
    if not IS_BUILT_APPLICATION:
        return

    # Validate platform name
    platform_name = platform.system().lower()
    if platform_name not in ("windows", "linux", "darwin"):
        raise ValueError("Unsupported platform {}".format(platform_name))

    executable_root = os.path.dirname(sys.executable)
    installer_shim_root = os.path.join(executable_root, "shim")

    with open(os.path.join(installer_shim_root, "shim.json"), "r") as stream:
        shim_data = json.load(stream)

    src_shim_version = semver.VersionInfo.parse(shim_data["version"])

    # Read existing shim version (if there is any)
    dst_shim_version = _get_installed_shim_version()

    # Skip if shim is same or lower
    if src_shim_version <= semver.VersionInfo.parse(dst_shim_version):
        # Make sure windows registers are correctly set for each user
        if ensure_protocol_is_registered:
            register_ayon_launcher_protocol()
        return

    platform_name = platform.system().lower()
    if platform_name == "windows":
        _deploy_shim_windows(installer_shim_root, create_desktop_icons)

    elif platform_name == "linux":
        _deploy_shim_linux(installer_shim_root)

    elif platform_name == "darwin":
        _deploy_shim_macos(installer_shim_root)
    register_ayon_launcher_protocol()
