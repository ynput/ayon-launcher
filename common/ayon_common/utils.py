import os
import sys
import platform
import json
import datetime
import subprocess
from uuid import UUID

import appdirs

IS_BUILT_APPLICATION = getattr(sys, "frozen", False)
WIN_DOWNLOAD_FOLDER_ID = UUID("{374DE290-123F-4565-9164-39C4925E467B}")
IMPLEMENTED_ARCHIVE_FORMATS = {
    ".zip", ".tar", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"
}


def get_ayon_appdirs(*args):
    """Local app data directory of AYON client.

    Args:
        *args (Iterable[str]): Subdirectories/files in local app data dir.

    Returns:
        str: Path to directory/file in local app data dir.
    """

    return os.path.join(
        appdirs.user_data_dir("ayon", "ynput"),
        *args
    )


def is_staging_enabled():
    """Check if staging is enabled.

    Returns:
        bool: True if staging is enabled.
    """

    return os.getenv("AYON_USE_STAGING") == "1"


def _create_local_site_id():
    """Create a local site identifier.

    Returns:
        str: Randomly generated site id.
    """

    from coolname import generate_slug

    new_id = generate_slug(3)

    print("Created local site id \"{}\"".format(new_id))

    return new_id


def get_local_site_id():
    """Get local site identifier.

    Site id is created if does not exist yet.

    Returns:
        str: Site id.
    """

    # used for background syncing
    site_id = os.environ.get("AYON_SITE_ID")
    if site_id:
        return site_id

    site_id_path = get_ayon_appdirs("site_id")
    if os.path.exists(site_id_path):
        with open(site_id_path, "r") as stream:
            site_id = stream.read()

    if not site_id:
        site_id = _create_local_site_id()
        with open(site_id_path, "w") as stream:
            stream.write(site_id)
    return site_id


def get_ayon_launch_args(*args):
    """Launch arguments that can be used to launch ayon process.

    Args:
        *args (str): Additional arguments.

    Returns:
        list[str]: Launch arguments.
    """

    output = [sys.executable]
    if not IS_BUILT_APPLICATION:
        output.append(sys.argv[0])
    output.extend(args)
    return output


# Store executables info to a file
def get_executables_info_filepath():
    """Get path to file where information about executables is stored.

    Returns:
        str: Path to json file where executables info are stored.
    """

    return get_ayon_appdirs("executables.json")


def get_executables_info():
    filepath = get_executables_info_filepath()
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as stream:
                return json.load(stream)
        except Exception:
            pass

    return {"file_version": "1.0.0"}


def store_executables_info(info):
    """Store information about executables.

    This will override existing information so use it wisely.
    """

    filepath = get_executables_info_filepath()
    dirpath = os.path.dirname(filepath)
    if not os.path.exists(dirpath):
        os.makedirs(dirpath)

    with open(filepath, "w") as stream:
        json.dump(info, stream, indent=4)


def store_current_executable_info():
    """Store information about current executable to a file for future usage.

    Use information about current executable and version of executable and
    add it to a list of available executables.

    The function won't do anything if the application is not built or if
    version is not set or the executable is already available.
    """

    version = os.getenv("AYON_VERSION")
    if not IS_BUILT_APPLICATION or not version:
        return

    executable = sys.executable

    info = get_executables_info()
    info.setdefault("available_versions", [])

    match_item = None
    for item in info["available_versions"]:
        if item["executable"] == executable:
            # Version has changed, update it
            if item["version"] == version:
                return
            match_item = item
            break

    if match_item is None:
        match_item = {}
        info["available_versions"].append(match_item)

    match_item.update({
        "version": version,
        "executable": executable,
        "added": datetime.datetime.now().strftime("%y-%m-%d-%H%M")
    })
    store_executables_info(info)


def get_executables_info_by_version(version):
    """Get available executable info by version.

    Args:
        version (str): Version of executable.

    Returns:
        list[dict[str, Any]]: Executable info matching version.
    """

    executables_info = get_executables_info()
    return [
        item
        for item in executables_info.get("available_versions", [])
        if item["version"] == version
    ]


def get_executable_paths_by_version(version, only_available=True):
    """Get executable paths by version.

    Returns:
        list[str]: Paths to executables.
    """

    output = []
    for item in get_executables_info_by_version(version):
        path = item["executable"]
        # Skip if executable was not found
        if only_available and not os.path.exists(path):
            continue
        output.append(path)
    return output


def cleanup_executables_info():
    """Remove executables that do not exist anymore."""

    executables_info = get_executables_info()
    new_executables_info = [
        item
        for item in get_executables_info()
        if os.path.exists(item["executable"])
    ]
    if len(new_executables_info) != len(executables_info):
        store_executables_info(new_executables_info)


class _Cache:
    downloads_dir = 0


def _get_linux_downloads_dir():
    return subprocess.run(
        ["xdg-user-dir", "DOWNLOAD"],
        capture_output=True, text=True
    ).stdout.strip("\n")


def _get_windows_downloads_dir():
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


def _get_macos_downloads_dir():
    """Get downloads directory on MacOS.

    Notes:
        By community forum '~/Downloads' is right way, which is default.

    Returns:
        Union[str, None]: Path to downloads directory or None if not found.
    """

    return None


def get_downloads_dir():
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


def extract_archive_file(archive_file, dst_folder=None):
    _, ext = os.path.splitext(archive_file)
    ext = ext.lower()

    if not dst_folder:
        dst_folder = os.path.dirname(archive_file)

    print("Extracting {}->{}".format(archive_file, dst_folder))
    if ext == ".zip":
        import zipfile

        zip_file = zipfile.ZipFile(archive_file)
        zip_file.extractall(dst_folder)
        zip_file.close()

    elif ext in {".tar", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"}:
        import tarfile

        if ext == ".tar":
            tar_type = "r:"
        elif ext.endswith(".xz"):
            tar_type = "r:xz"
        elif ext.endswith(".gz"):
            tar_type = "r:gz"
        elif ext.endswith(".bz2"):
            tar_type = "r:bz2"
        else:
            tar_type = "r:*"
        try:
            tar_file = tarfile.open(archive_file, tar_type)
        except tarfile.ReadError:
            raise SystemExit("corrupted archive")
        tar_file.extractall(dst_folder)
        tar_file.close()

    raise ValueError((
        f"Invalid file extension \"{ext}\"."
        f" Expected {', '.join(IMPLEMENTED_ARCHIVE_FORMATS)}"
    ))


def calculate_file_checksum(filepath, checksum_algorithm, chunk_size=10000):
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


def validate_file_checksum(filepath, checksum, checksum_algorithm):
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
