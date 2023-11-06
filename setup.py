# -*- coding: utf-8 -*-
"""Setup info for building AYON Desktop application."""
import os
import re
import platform
from pathlib import Path

from cx_Freeze import setup, Executable

ayon_root = Path(os.path.dirname(__file__))
resources_dir = ayon_root / "common" / "ayon_common" / "resources"

version_content = {}

with open(ayon_root / "version.py") as fp:
    exec(fp.read(), version_content)

__version__ = version_content["__version__"]

low_platform_name = platform.system().lower()
IS_WINDOWS = low_platform_name == "windows"
IS_LINUX = low_platform_name == "linux"
IS_MACOS = low_platform_name == "darwin"

base = None
if IS_WINDOWS:
    base = "Win32GUI"

# -----------------------------------------------------------------------
# build_exe
# Build options for cx_Freeze. Manually add/exclude packages and binaries

install_requires = [
    "appdirs",
    "cx_Freeze",
    "keyring",
    "pkg_resources",
    "qtpy",
    "filecmp",
    "dns",
    # Python defaults (cx_Freeze skip them by default)
    "dbm",
    "dataclasses",
    "email.mime.application",
    "email.mime.audio",
    "email.mime.base",
    "email.mime.image",
    "email.mime.message",
    "email.mime.multipart",
    "email.mime.nonmultipart",
    "email.mime.text",
    "sqlite3",
    "timeit"
]

includes = []
excludes = [
    # Make sure 'common' subfolder is not included in 'lib'
    # - can happen when there are testing imports like:
    #       'from common.ayon_common import ...'
    "common",
]
# WARNING: As of cx_freeze there is a bug?
# when this is empty, its hooks will not kick in
# and won't clean platform irrelevant modules
# like dbm mentioned above.

bin_includes = [
    "vendor"
]
include_files = [
    "version.py",
    "common",
    "LICENSE",
    "README.md"
]

if IS_WINDOWS:
    install_requires.extend([
        # `pywin32` packages
        "win32ctypes",
        "win32comext",
        "pythoncom"
    ])


icon_path = resources_dir / "AYON.ico"
mac_icon_path = resources_dir / "AYON.icns"

build_exe_options = dict(
    build_exe="build/output",
    packages=install_requires,
    includes=includes,
    excludes=excludes,
    bin_includes=bin_includes,
    include_files=include_files,
    optimize=0,
    replace_paths=[("*", "")],
)

bdist_mac_options = dict(
    bundle_name=f"AYON {__version__}",
    iconfile=mac_icon_path
)

executables = [
    Executable(
        "start.py",
        base=base,
        target_name="ayon",
        icon=icon_path.as_posix()
    ),
]
if IS_WINDOWS:
    executables.append(
        Executable(
            "start.py",
            base=None,
            target_name="ayon_console",
            icon=icon_path.as_posix()
        )
    )

if IS_LINUX:
    executables.append(
        Executable(
            "app_launcher.py",
            base=None,
            target_name="app_launcher",
            icon=icon_path.as_posix()
        )
    )

setup(
    name="AYON",
    version=__version__,
    description="AYON Desktop Client",
    options={
        "build_exe": build_exe_options,
        "bdist_mac": bdist_mac_options,
    },
    executables=executables,
    packages=[]
)
