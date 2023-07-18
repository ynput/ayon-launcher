# -*- coding: utf-8 -*-
"""Script to fix frozen dependencies.

Because Pype code needs to run under different versions of Python interpreter
(yes, even Python 2) we need to include all dependencies as source code
without Python's system stuff. Cx-freeze puts everything into lib and compile
it as .pyc/.pyo files and that doesn't work for hosts like Maya 2020 with
their own Python interpreter and libraries.

This script will take ``site-packages`` and copy them to built Pype under
``dependencies`` directory. It will then compare stuff inside with ``lib``
folder in  frozen Pype, removing duplicities from there.

This must be executed after build finished and it is done by build PowerShell
script.

Note: Speedcopy can be used for copying if server-side copy is important for
speed.
"""

import os
import sys
import re
import json
import tempfile
import time
import site
import platform
import subprocess
import shutil
import tarfile
import hashlib
import copy
from pathlib import Path

import blessed
import enlighten

term = blessed.Terminal()
manager = enlighten.get_manager()


def _print(msg: str, type: int = 0) -> None:
    """Print message to console.

    Args:
        msg (str): message to print
        type (int): type of message (0 info, 1 error, 2 note)

    """
    if type == 0:
        header = term.aquamarine3(">>> ")
    elif type == 1:
        header = term.orangered2("!!! ")
    elif type == 2:
        header = term.tan1("... ")
    else:
        header = term.darkolivegreen3("--- ")

    print(f"{header}{msg}")


def count_folders(path: Path) -> int:
    """Recursively count items inside given Path.

    Args:
        path (Path): Path to count.

    Returns:
        int: number of items.

    """
    cnt = 0
    for child in path.iterdir():
        if child.is_dir():
            cnt += 1
            cnt += count_folders(child)
    return cnt


def get_site_pkg():
    """Get path to site-packages.

    Returns:
        Union[str, None]: Path to site-packages or None if not found.
    """

    # path to venv site packages
    sites = site.getsitepackages()

    # WARNING: this assumes that all we've got is path to venv itself and
    # another path ending with 'site-packages' as is default. But because
    # this must run under different platform, we cannot easily check if this path
    # is the one, because under Linux and macOS site-packages are in different
    # location.
    for s in sites:
        site_pkg = Path(s)
        if site_pkg.name == "site-packages":
            return site_pkg


def get_ayon_version(ayon_root):
    """Get AYON version from version.py file.

    Args:
        ayon_root (Path): Path to AYON root.

    Returns:
        str: AYON version.
    """

    version = {}
    with open(ayon_root / "version.py") as fp:
        exec(fp.read(), version)

    version_match = re.search(r"(\d+\.\d+.\d+).*", version["__version__"])
    return version_match[1]


def _get_darwin_output_path(build_root, ayon_version):
    return build_root / f"AYON {ayon_version}.app"


def get_build_content_root(build_root, ayon_version):
    if platform.system().lower() == "darwin":
        return _get_darwin_output_path(build_root, ayon_version).joinpath(
            "Contents",
            "MacOS"
        )
    return build_root / "output"


def get_metadata_filepath(build_root):
    return build_root / "metadata.json"


def get_build_metadata(build_root):
    with open(get_metadata_filepath(build_root), "r") as stream:
        return json.load(stream)


def store_build_metadata(build_root, metadata):
    with open(get_metadata_filepath(build_root), "w") as stream:
        json.dump(metadata, stream)


def _fix_pyside2_linux(ayon_root, build_root):
    src_pyside_dir = ayon_root / "vendor" / "python" / "PySide2"
    dst_pyside_dir = build_root / "vendor" / "python" / "PySide2"
    src_rpath_per_so_file = {}
    for filepath in src_pyside_dir.glob("*.so"):
        filename = filepath.name
        rpath = (
            subprocess.check_output(["patchelf", "--print-rpath", filepath])
            .decode("utf-8")
            .strip()
        )
        src_rpath_per_so_file[filename] = rpath

    for filepath in dst_pyside_dir.glob("*.so"):
        filename = filepath.name
        if filename not in src_rpath_per_so_file:
            continue
        src_rpath = src_rpath_per_so_file[filename]
        subprocess.check_call(
            ["patchelf", "--set-rpath", src_rpath, filepath]
        )


def copy_files(ayon_root, build_content_root, deps_dir, site_pkg):
    vendor_dir = build_content_root / "vendor"
    vendor_src = ayon_root / "vendor"

    # copy vendor files
    _print("Copying vendor files ...")

    total_files = count_folders(vendor_src)
    progress_bar = enlighten.Counter(
        total=total_files,
        desc="Copying vendor files ...",
        units="%",
        color=(64, 128, 222))

    def _progress(_base, _names):
        progress_bar.update()
        return []

    shutil.copytree(
        vendor_src.as_posix(),
        vendor_dir.as_posix(),
        ignore=_progress
    )
    progress_bar.close()

    # copy all files
    _print("Copying dependencies ...")

    total_files = count_folders(site_pkg)
    progress_bar = enlighten.Counter(
        total=total_files,
        desc="Processing Dependencies",
        units="%",
        color=(53, 178, 202))

    shutil.copytree(
        site_pkg.as_posix(),
        deps_dir.as_posix(),
        ignore=_progress
    )
    progress_bar.close()


def cleanup_files(deps_dir, libs_dir):
    to_delete = []
    # _print("Finding duplicates ...")
    deps_items = list(deps_dir.iterdir())
    item_count = len(list(libs_dir.iterdir()))
    find_progress_bar = enlighten.Counter(
        total=item_count,
        desc="Finding duplicates",
        units="%",
        color=(56, 211, 159)
    )

    for d in libs_dir.iterdir():
        if (deps_dir / d.name) in deps_items:
            to_delete.append(d)
            # _print(f"found {d}", 3)
        find_progress_bar.update()

    find_progress_bar.close()

    to_delete.append(libs_dir / "ayon")
    to_delete.append(libs_dir / "ayon.pth")
    to_delete.append(deps_dir / "ayon.pth")

    # delete duplicates
    # _print(f"Deleting {len(to_delete)} duplicates ...")
    delete_progress_bar = enlighten.Counter(
        total=len(to_delete), desc="Deleting duplicates", units="%",
        color=(251, 192, 32))
    for d in to_delete:
        if d.is_dir():
            shutil.rmtree(d)
        else:
            try:
                d.unlink()
            except FileNotFoundError:
                # skip non-existent silently
                pass
        delete_progress_bar.update()
    delete_progress_bar.close()


def dependency_cleanup(ayon_root, build_content_root):
    """Prepare dependency for build output.

    Remove unnecessary files and copy remaining dependencies to build output.


    Args:
        ayon_root (Path): Path to ayon root.
        build_content_root (Path): Path to build output directory.
    """

    _print(f"Using build at {build_content_root}", 2)

    _print("Starting dependency cleanup ...")
    start_time = time.time_ns()

    _print("Getting venv site-packages ...")
    site_pkg = get_site_pkg()
    if not site_pkg:
        _print("No venv site-packages are found.")
        sys.exit(1)

    _print(f"Working with: {site_pkg}", 2)

    if not build_content_root.exists():
        _print("Build directory doesn't exist", 1)
        _print("Probably freezing of code failed. Check ./build/build.log", 3)
        sys.exit(1)

    # iterate over frozen libs and create list to delete
    deps_dir = build_content_root / "dependencies"
    libs_dir = build_content_root / "lib"
    copy_files(ayon_root, build_content_root, deps_dir, site_pkg)

    # On Linux use rpath from source libraries in destination libraries
    platform_name = platform.system().lower()
    if platform_name == "linux":
        _fix_pyside2_linux(ayon_root, build_content_root)

    cleanup_files(deps_dir, libs_dir)
    end_time = time.time_ns()
    total_time = (end_time - start_time) / 1000000000
    _print(f"Dependency cleanup done in {total_time} secs.")


class _RuntimeModulesCache:
    cache = None


def get_runtime_modules(root):
    """Get runtime modules and their versions.

    Todos:
        Find a better way how to get runtime modules and their versions.

    Args:
        root (Path): Root to location where runtime modules are.

    Returns:
        dict[str, Union[str, None]]: Module name and version.
    """

    if _RuntimeModulesCache.cache is not None:
        return copy.deepcopy(_RuntimeModulesCache.cache)

    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "_runtime_deps.py")

    executable = root / "ayon"
    with tempfile.NamedTemporaryFile(
        prefix="ayon_rtd", suffix=".json", delete=False
    ) as tmp:
        output_path = tmp.name

    try:
        return_code = subprocess.call(
            [str(executable), "--skip-bootstrap", script_path, output_path]
        )
        if return_code != 0:
            raise ValueError("Wasn't able to get runtime modules.")

        with open(output_path, "r") as stream:
            data = json.load(stream)

    finally:
        os.remove(output_path)

    _RuntimeModulesCache.cache = data
    return data


def get_packages_info(build_root):
    """Read lock file to get packages.

    Retruns:
        list[tuple[str, Union[str, None]]]: List of tuples containing package
            name and version.
    """

    requirements_path = build_root / "requirements.txt"
    if not requirements_path.exists():
        raise RuntimeError(
            "Failed to get packages info -> couldn't find 'requirements.txt'."
        )

    with open(str(requirements_path), "r") as stream:
        content = stream.read()

    packages = {}
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue

        match = re.match(r"^(.+?)(?:==|>=|<=|~=|!=|@)(.+)$", line)
        if not match:
            raise ValueError(f"Cannot parse package info '{line}'.")
        package_name, version = match.groups()
        packages[package_name.rstrip()] = version.lstrip()

    return packages


def store_base_metadata(build_root, build_content_root, ayon_version):
    """Store metadata about build.

    The information are needed for server installer information. The build
    process does not create installer. The installer is created by other
    tools.

    Args:
        build_root (Path): Path to build directory.
        build_content_root (Path): Path build content directory.
        ayon_version (str): AYON version.
    """

    metadata = {
        "version": ayon_version,
        "platform": platform.system().lower(),
        "python_version": platform.python_version(),
        "python_modules": get_packages_info(build_root),
        "runtime_python_modules": get_runtime_modules(build_content_root),
    }
    store_build_metadata(build_root, metadata)


def post_build_process(ayon_root, build_root):
    """Post build process.

    Cleanup dependencies, fix build issues and store base build metadata.
    """

    ayon_version = get_ayon_version(ayon_root)
    build_content_root = get_build_content_root(build_root, ayon_version)

    dependency_cleanup(ayon_root, build_content_root)
    store_base_metadata(build_root, build_content_root, ayon_version)


def _find_iscc():
    """Find Inno Setup headless executable for windows installer.

    Returns:
        str: Path to ISCC.exe.

    Raises:
        ValueError: If ISCC.exe is not found.
    """

    basename = "ISCC.exe"
    try:
        subprocess.call([basename])
        return basename
    except FileNotFoundError:
        pass


    # Find automatically in program files
    program_files = os.getenv("PROGRAMFILES")
    program_files_x86 = os.getenv("PROGRAMFILES(X86)")
    for program_dir in [program_files_x86, program_files]:
        if not program_dir:
            continue

        program_dir = Path(program_dir)
        for subdir in program_dir.iterdir():
            if not subdir.name.lower().startswith("inno setup"):
                continue

            path = subdir / basename
            if path.exists():
                return str(path)

    raise ValueError("Can't find ISCC.exe")


def _create_windows_installer(
    ayon_root,
    build_root,
    build_content_root,
    ayon_version
):
    """Create Windows installer.

    Returns:
        Path: Path to installer file.
    """

    iscc_executable = _find_iscc()

    inno_setup_path = ayon_root / "inno_setup.iss"
    env = os.environ.copy()
    installer_basename = f"AYON-{ayon_version}-win-setup"

    env["BUILD_SRC_DIR"] = str(build_content_root.relative_to(ayon_root))
    env["BUILD_DST_DIR"] = str(build_root.relative_to(ayon_root))
    env["BUILD_VERSION"] = ayon_version
    env["BUILD_DST_FILENAME"] = installer_basename
    subprocess.call([iscc_executable, inno_setup_path], env=env)
    output_file = build_root / (installer_basename + ".exe")
    if output_file.exists():
        return output_file
    raise ValueError("Installer was not created")


def _create_linux_installer(
    _,
    build_root,
    build_content_root,
    ayon_version
):
    """Linux installer is just tar file.

    Returns:
        Path: Path to installer file.
    """

    basename = f"AYON-{ayon_version}-linux"
    filename = f"{basename}.tar.gz"
    output_path = build_root / filename

    # Open file in write mode to be sure that it exists
    with open(output_path, "w"):
        pass

    with tarfile.open(output_path, mode="w:gz") as tar:
        tar.add(build_content_root, arcname=basename)
    return output_path


def _create_darwin_installer(_ar, build_root, _, ayon_version):
    """Create MacOS installer (.dmg).

    Returns:
        Path: Path to installer file.

    Raises:
        ValueError: If 'create-dmg' is not available.
    """

    app_filepath = _get_darwin_output_path(build_root, ayon_version)
    output_path = build_root / f"AYON-{ayon_version}-Installer.dmg"
    # TODO check if 'create-dmg' is available
    try:
        subprocess.call(["create-dmg"])
    except FileNotFoundError:
        raise ValueError("create-dmg is not available")

    _print("Creating dmg image ...")
    args = [
        "create-dmg",
        "--volname", f"AYON {ayon_version} Installer",
        "--window-pos", "200", "120",
        "--window-size", "600", "300",
        "--app-drop-link", "100", "50",
        output_path,
        app_filepath
    ]
    if subprocess.call(args) != 0:
        raise ValueError("Failed to create DMG image")
    _print("DMG image created")
    return output_path


def _create_installer(*args, **kwargs):
    """Create single file installer of desktop application.

    Returns:
        Path: Path to installer file.

    Raises:
        ValueError: If platform is not supported.
    """

    platform_name = platform.system().lower()
    if platform_name == "windows":
        return _create_windows_installer(*args, **kwargs)

    if platform_name == "linux":
        return _create_linux_installer(*args, **kwargs)

    if platform_name == "darwin":
        return _create_darwin_installer(*args, **kwargs)

    raise ValueError(f"Unknown platform '{platform_name}'.")


def store_installer_metadata(build_root, installer_path):
    """Update base build metadata with installer information.

    Args:
        build_root (Path): Path to build root directory.
        installer_path (str): Path to installer file.
    """

    metadata = get_build_metadata(build_root)

    with open(installer_path, "rb") as stream:
        file_hash = hashlib.md5(stream.read()).hexdigest()

    metadata.update({
        "checksum": file_hash,
        "checksum_algorithm": "md5",
        "size": os.path.getsize(installer_path),
        "installer_path": installer_path
    })
    store_build_metadata(build_root, metadata)


def create_installer(ayon_root, build_root):
    metadata = get_build_metadata(build_root)
    ayon_version = metadata["version"]
    build_content_root = get_build_content_root(build_root, ayon_version)

    installer_path = _create_installer(
        ayon_root, build_root, build_content_root, ayon_version)
    store_installer_metadata(build_root, str(installer_path))


def main():
    if sys.argv[-1] == "build":
        do_post_build = True
        do_installer = False
    elif sys.argv[-1] == "make-installer":
        do_post_build = False
        do_installer = True
    else:
        do_post_build = True
        do_installer = True

    ayon_root = Path(os.path.dirname(__file__)).parent
    build_root = ayon_root / "build"

    if do_post_build:
        post_build_process(ayon_root, build_root)

    if do_installer:
        create_installer(ayon_root, build_root)


if __name__ == "__main__":
    main()
