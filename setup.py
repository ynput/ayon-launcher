# -*- coding: utf-8 -*-
"""Setup info for building AYON Desktop application."""
import os
import platform
import subprocess
from pathlib import Path

from cx_Freeze import setup, Executable

ayon_root = Path(os.path.dirname(__file__))
resources_dir = ayon_root / "common" / "ayon_common" / "resources"

version_content = {}

with open(ayon_root / "version.py") as fp:
    exec(fp.read(), version_content)

include_dir = ayon_root / "vendor" / "include"

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
    "platformdirs",
    "cx_Freeze",
    "keyring",
    "pkg_resources",
    "qtpy",
    "filecmp",
    "dns",
    # Python defaults (cx_Freeze skip some of them because are unused)
    "colorsys",
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
    "timeit",
]

# These are added just to be sure created executable has available even
#     unused modules. Some of them are not available on all platforms.
python_builtins = [
    # Just to be sure
    "abc",
    "argparse",
    "asyncio",
    "base64",
    "cmd",
    "code",
    "codecs",
    "codeop",
    "collections",
    "compileall",
    "configparser",
    "concurrent",
    "contextlib",
    "contextvars",
    "copy",
    "csv",
    "ctypes",
    "curses",
    "distutils",
    "datetime",
    "decimal",
    "difflib",
    "dis",
    "email",
    "encodings",
    "ensurepip",
    "enum",
    "filecmp",
    "fileinput",
    "fnmatch",
    "formatter",
    "fractions",
    "ftplib",
    "functools",
    "genericpath",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "graphlib",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "idlelib",
    "imaplib",
    "imghdr",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "json",
    "keyword",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "mailcap",
    "mimetypes",
    "modulefinder",
    "multiprocessing",
    "netrc",
    "nntplib",
    "numbers",
    "opcode",
    "operator",
    "optparse",
    "os",
    "pathlib",
    "pdb",
    "pickle",
    "pickletools",
    "pipes",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "pty",
    "py_compile",
    "pyclbr",
    "pydoc",
    "queue",
    "quopri",
    "random",
    "re",
    "reprlib",
    "rlcompleter",
    "runpy",
    "sched",
    "secrets",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "smtpd",
    "smtplib",
    "sndhdr",
    "socket",
    "socketserver",
    "sre_compile",
    "sre_constants",
    "sre_parse",
    "ssl",
    "stat",
    "statistics",
    "string",
    "stringprep",
    "struct",
    "subprocess",
    "sunau",
    "symbol",
    "symtable",
    "tarfile",
    "telnetlib",
    "tempfile",
    "textwrap",
    "threading",
    "token",
    "tokenize",
    "trace",
    "traceback",
    "tracemalloc",
    "turtle",
    "types",
    "typing",
    "uuid",
    "urllib",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "xml",
    "zipapp",
    "zipfile",
    "zipimport",
    "zoneinfo",
]
for module_name in python_builtins:
    try:
        __import__(module_name)
        install_requires.append(module_name)
    except ImportError:
        pass

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
if IS_LINUX:
    subprocess.run(
        [
            "g++",
            "-std=c++17",
            f"-I{include_dir.as_posix()}",
            "app_launcher.cpp",
            "-o", "app_launcher",
        ],
        cwd=ayon_root.as_posix(),
    )
    include_files.append("app_launcher")
    install_requires.extend([
        "bz2",
        "curses",
        "crypt",
        "dbm",
        "lzma",
        "resource",
        "readline",
        "sqlite3"
    ])

icon_path = None
mac_icon_path = resources_dir / "AYON.icns"
if IS_WINDOWS:
    icon_path = (resources_dir / "AYON.ico").as_posix()
    install_requires.extend([
        # `pywin32` packages
        "win32ctypes",
        "win32comext",
        "pythoncom"
    ])


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
        icon=icon_path
    ),
]
if IS_WINDOWS:
    executables.append(
        Executable(
            "start.py",
            base=None,
            target_name="ayon_console",
            icon=icon_path
        )
    )
    build_exe_options["include_msvcr"] = True


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
