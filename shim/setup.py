# -*- coding: utf-8 -*-
"""Setup info for building AYON Desktop application."""
import os
import platform
from pathlib import Path

from cx_Freeze import setup, Executable

ayon_root = Path(os.path.dirname(__file__))
resources_dir = ayon_root.parent / "common" / "ayon_common" / "resources"

__version__ = "1.0.0"

low_platform_name = platform.system().lower()
IS_WINDOWS = low_platform_name == "windows"
IS_LINUX = low_platform_name == "linux"
IS_MACOS = low_platform_name == "darwin"

base = None
if IS_WINDOWS:
    base = "Win32GUI"

include_files = [
    "version",
]

icon_path = resources_dir / "AYON.ico"
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
        "urllib",
        "xmlrps",
    ]
)

bdist_mac_options = dict(
    bundle_name=f"AYON shim {__version__}",
    iconfile=mac_icon_path
)

executables = [
    Executable(
        "shim_start.py",
        base=base,
        target_name="ayon",
        icon=icon_path.as_posix()
    ),
]
if IS_WINDOWS:
    executables.append(
        Executable(
            "shim_start.py",
            base=None,
            target_name="ayon_console",
            icon=icon_path.as_posix()
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
