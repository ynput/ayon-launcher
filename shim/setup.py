# -*- coding: utf-8 -*-
"""Setup info for building AYON Desktop application."""
import os
import platform
from pathlib import Path

from cx_Freeze import setup, Executable

ayon_root = Path(os.path.dirname(__file__))
resources_dir = ayon_root.parent / "common" / "ayon_common" / "resources"

with open(ayon_root / "version", "r") as stream:
    __version__ = stream.read().strip()

low_platform_name = platform.system().lower()
IS_WINDOWS = low_platform_name == "windows"
IS_LINUX = low_platform_name == "linux"
IS_MACOS = low_platform_name == "darwin"

base = None
icon_path = None
if IS_WINDOWS:
    base = "Win32GUI"
    icon_path = (resources_dir / "AYON.ico").as_posix()

include_files = [
    "version",
]
if IS_LINUX:
    include_files.extend([
        "ayon.desktop",
        "../common/ayon_common/resources/AYON.png",
        "../common/ayon_common/resources/AYON_staging.png",
    ])

mac_icon_path = resources_dir / "AYON.icns"

build_exe_options = dict(
    build_exe="dist",
    optimize=2,
    replace_paths=[("*", "")],
    include_files=include_files,
    excludes=[
        "_socket",
        "asyncio",
        "concurrent",
        "email",
        "html",
        "http",
        "lib2to3",
        "libcrypto",
        "libssl",
        "multiprocessing",
        "pydoc_data",
        "sqlite3",
        "test",
        "tkinter",
        "unittest",
        "xmlrps",
    ]
)

bdist_mac_options = dict(
    bundle_name="AYON",
    iconfile=mac_icon_path
)

executables = [
    Executable(
        "shim_start.py",
        base=base,
        target_name="ayon",
        icon=icon_path
    ),
]
if IS_WINDOWS:
    executables.append(
        Executable(
            "shim_start.py",
            base=None,
            target_name="ayon_console",
            icon=icon_path
        )
    )

if IS_MACOS:
    # Main executable of AYON.app will be 'ayon_macos'
    executables.insert(
        0,
        Executable(
            "macos_start.py",
            target_name="ayon_macos",
            icon=icon_path
        )
    )


setup(
    name="AYON-shim",
    version=__version__,
    description="AYON Desktop Client shim",
    options={
        "build_exe": build_exe_options,
        "bdist_mac": bdist_mac_options,
    },
    executables=executables,
    packages=[]
)
