import os
import sys
import json
import datetime

import appdirs

IS_BUILT_APPLICATION = getattr(sys, "frozen", False)


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
