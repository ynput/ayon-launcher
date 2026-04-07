# -*- coding: utf-8 -*-
"""Install runtime python modules required by AYON.

Those should be defined in `pyproject.toml` in AYON sources root.
"""

import os
import shutil
import sys
import platform
import hashlib
import time
import subprocess
from pathlib import Path

import toml
import enlighten
import blessed


term = blessed.Terminal()
manager = enlighten.get_manager()
hash_buffer_size = 65536


def sha256_sum(filename: Path):
    """Calculate sha256 hash for given file.

    Args:
        filename (Path): path to file.

    Returns:
        str: hex hash.

    """
    _hash = hashlib.sha256()
    with open(filename, 'rb', buffering=0) as f:
        buffer = bytearray(128 * 1024)
        mv = memoryview(buffer)
        for n in iter(lambda: f.readinto(mv), 0):
            _hash.update(mv[:n])
    return _hash.hexdigest()


def _print(msg: str, message_type: int = 0) -> None:
    """Print message to console.

    Args:
        msg (str): message to print
        message_type (int): type of message (0 info, 1 error, 2 note)

    """
    if message_type == 0:
        header = term.aquamarine3(">>> ")
    elif message_type == 1:
        header = term.orangered2("!!! ")
    elif message_type == 2:
        header = term.tan1("... ")
    else:
        header = term.darkolivegreen3("--- ")

    print(f"{header}{msg}")


def _pip_install(python_vendor_dir, package, version=None):
    arg = None
    if package and version:
        arg = f"{package}=={version}"
    elif package:
        arg = package

    if not arg:
        _print("Couldn't find package to install")
        sys.exit(1)

    _print(f"We'll install {arg}")

    try:
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--upgrade", arg,
                "--target", str(python_vendor_dir)
            ],
            check=True,
            stdout=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError as e:
        _print(f"Error during {package} installation.", 1)
        _print(str(e), 1)
        sys.exit(1)


def install_qtbinding(
    pyproject, python_vendor_dir, platform_name, use_pyside2
):
    _print("Handling Qt binding framework ...")

    qt_variants = []
    if use_pyside2:
        qt_variants.append("pyside2")

    # Use QT_BINDING environment variable if set
    # - existence is not validate, if does not exists it is just skipped
    qt_package = os.getenv("QT_BINDING")
    if qt_package:
        qt_variants.append(qt_package)

    qt_binding_options = pyproject["ayon"]["qtbinding"]
    qtbinding_def = None
    for qt_variant in qt_variants:
        qtbinding_def = qt_binding_options.get(qt_variant)
        if qtbinding_def:
            break

    # Use platform default Qt binding
    if not qtbinding_def:
        qtbinding_def = pyproject["ayon"]["qtbinding"][platform_name]

    package = qtbinding_def["package"]
    version = qtbinding_def.get("version")

    _pip_install(python_vendor_dir, package, version)

    # Remove libraries for QtSql which don't have available libraries
    #   by default and Postgre library would require to modify rpath of
    #   dependency
    if platform_name == "darwin":
        sqldrivers_dir = (
            python_vendor_dir / package / "Qt" / "plugins" / "sqldrivers"
        )
        for filepath in sqldrivers_dir.iterdir():
            os.remove(str(filepath))


def install_runtime_dependencies(pyproject, python_vendor_dir):
    runtime_deps = (
        pyproject
        .get("ayon", {})
        .get("runtime", {})
        .get("deps", {})
    )
    for package, version in runtime_deps.items():
        _pip_install(python_vendor_dir, package, version)


def main():
    start_time = time.time_ns()
    repo_root = Path(os.path.dirname(__file__)).parent
    python_vendor_dir = repo_root / "vendor" / "python"
    if python_vendor_dir.exists():
        _print("Removing existing vendor directory")
        shutil.rmtree(python_vendor_dir)
    python_vendor_dir.mkdir(parents=True, exist_ok=True)
    pyproject = toml.load(repo_root / "pyproject.toml")
    platform_name = platform.system().lower()
    use_pyside2 = "--use-pyside2" in sys.argv

    install_qtbinding(
        pyproject, python_vendor_dir, platform_name, use_pyside2
    )
    install_runtime_dependencies(pyproject, python_vendor_dir)
    end_time = time.time_ns()
    total_time = (end_time - start_time) / 1000000000
    _print(f"Downloading and extracting took {total_time} secs.")


if __name__ == "__main__":
    main()
