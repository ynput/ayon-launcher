import os
import sys
import json
import datetime

import appdirs

IS_BUILT_APPLICATION = getattr(sys, "frozen", False)
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
