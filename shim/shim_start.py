import os
import platform
import sys
import struct
import ctypes
import time
import json
import subprocess

import appdirs
import semver

IS_BUILT_APPLICATION = getattr(sys, "frozen", False)
CURRENT_PATH = os.path.abspath(__file__)

# Copyright (c) 2004 Bob Ippolito.
# Copyright (c) 2010-2024 Ronald Oussoren
# macOs process initialization sourced from https://github.com/ronaldoussoren/py2app/blob/master/src/py2app/bootstrap/_argv_emulator.py  noqa: E501
class AEDesc(ctypes.Structure):
    _fields_ = [
        ("descKey", ctypes.c_int),
        ("descContent", ctypes.c_void_p),
    ]


class EventTypeSpec(ctypes.Structure):
    _fields_ = [
        ("eventClass", ctypes.c_int),
        ("eventKind", ctypes.c_uint),
    ]


def _ctypes_setup() -> ctypes.CDLL:
    # NOTE Carbon is deprecated -> Cocoa should be used instead
    carbon = ctypes.CDLL("/System/Library/Carbon.framework/Carbon")

    ae_callback = ctypes.CFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
    )
    carbon.AEInstallEventHandler.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ae_callback,
        ctypes.c_void_p,
        ctypes.c_char,
    ]
    carbon.AERemoveEventHandler.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ae_callback,
        ctypes.c_char,
    ]

    carbon.AEProcessEvent.restype = ctypes.c_int
    carbon.AEProcessEvent.argtypes = [ctypes.c_void_p]

    carbon.ReceiveNextEvent.restype = ctypes.c_int
    carbon.ReceiveNextEvent.argtypes = [
        ctypes.c_long,
        ctypes.POINTER(EventTypeSpec),
        ctypes.c_double,
        ctypes.c_char,
        ctypes.POINTER(ctypes.c_void_p),
    ]

    carbon.AEGetParamDesc.restype = ctypes.c_int
    carbon.AEGetParamDesc.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(AEDesc),
    ]

    carbon.AECountItems.restype = ctypes.c_int
    carbon.AECountItems.argtypes = [
        ctypes.POINTER(AEDesc),
        ctypes.POINTER(ctypes.c_long),
    ]

    carbon.AEGetNthDesc.restype = ctypes.c_int
    carbon.AEGetNthDesc.argtypes = [
        ctypes.c_void_p,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]

    carbon.AEGetDescDataSize.restype = ctypes.c_int
    carbon.AEGetDescDataSize.argtypes = [ctypes.POINTER(AEDesc)]

    carbon.AEGetDescData.restype = ctypes.c_int
    carbon.AEGetDescData.argtypes = [
        ctypes.POINTER(AEDesc),
        ctypes.c_void_p,
        ctypes.c_int,
    ]

    carbon.FSRefMakePath.restype = ctypes.c_int
    carbon.FSRefMakePath.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]

    return carbon


def _run_argvemulator(timeout: float = 60.0):
    # Configure ctypes
    carbon = _ctypes_setup()

    # Is the emulator running?
    running = True

    (kAEInternetSuite,) = struct.unpack(">i", b"GURL")
    (kAEISGetURL,) = struct.unpack(">i", b"GURL")
    (kCoreEventClass,) = struct.unpack(">i", b"aevt")
    (kAEOpenApplication,) = struct.unpack(">i", b"oapp")
    (kAEOpenDocuments,) = struct.unpack(">i", b"odoc")
    (keyDirectObject,) = struct.unpack(">i", b"----")
    (typeAEList,) = struct.unpack(">i", b"list")
    (typeChar,) = struct.unpack(">i", b"TEXT")
    (typeFSRef,) = struct.unpack(">i", b"fsrf")
    FALSE = b"\0"
    TRUE = b"\1"
    eventLoopTimedOutErr = -9875

    (kEventClassAppleEvent,) = struct.unpack(">i", b"eppc")
    kEventAppleEvent = 1

    # Configure AppleEvent handlers
    ae_callback = ctypes.CFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p
    )

    @ae_callback
    def open_app_handler(
        message: ctypes.c_int, reply: ctypes.c_void_p, refcon: ctypes.c_void_p
    ) -> ctypes.c_void_p:
        # Got a kAEOpenApplication event, which means we can
        # start up. On some OSX versions this event is even
        # sent when an kAEOpenDocuments or kAEOpenURLs event
        # is sent later on.
        #
        # Therefore don't set running to false, but reduce the
        # timeout to at most two seconds beyond the current time.
        nonlocal timeout
        timeout = min(timeout, time.time() - start + 2)
        return ctypes.c_void_p(0)


    @ae_callback
    def open_file_handler(
        message: ctypes.c_int, reply: ctypes.c_void_p, refcon: ctypes.c_void_p
    ) -> ctypes.c_void_p:
        nonlocal running
        listdesc = AEDesc()
        sts = carbon.AEGetParamDesc(
            message, keyDirectObject, typeAEList, ctypes.byref(listdesc)
        )
        if sts != 0:
            print("argvemulator warning: cannot unpack open document event")
            running = False
            return ctypes.c_void_p(0)

        item_count = ctypes.c_long()
        sts = carbon.AECountItems(
            ctypes.byref(listdesc), ctypes.byref(item_count)
        )
        if sts != 0:
            print("argvemulator warning: cannot unpack open document event")
            running = False
            return ctypes.c_void_p(0)

        desc = AEDesc()
        for i in range(item_count.value):
            sts = carbon.AEGetNthDesc(
                ctypes.byref(listdesc), i + 1, typeFSRef, 0, ctypes.byref(desc)
            )
            if sts != 0:
                print("argvemulator warning: cannot unpack open document event")
                running = False
                return ctypes.c_void_p(0)

            sz = carbon.AEGetDescDataSize(ctypes.byref(desc))
            buf = ctypes.create_string_buffer(sz)
            sts = carbon.AEGetDescData(ctypes.byref(desc), buf, sz)
            if sts != 0:
                print("argvemulator warning: cannot extract open document event")
                continue

            fsref = buf

            buf = ctypes.create_string_buffer(1024)
            sts = carbon.FSRefMakePath(ctypes.byref(fsref), buf, 1023)
            if sts != 0:
                print("argvemulator warning: cannot extract open document event")
                continue

            sys.argv.append(buf.value.decode("utf-8"))

        running = False
        return ctypes.c_void_p(0)

    @ae_callback
    def open_url_handler(
        message: ctypes.c_int, reply: ctypes.c_void_p, refcon: ctypes.c_void_p
    ) -> ctypes.c_void_p:
        nonlocal running

        listdesc = AEDesc()
        ok = carbon.AEGetParamDesc(
            message, keyDirectObject, typeAEList, ctypes.byref(listdesc)
        )
        if ok != 0:
            print("argvemulator warning: cannot unpack open document event")
            running = False
            return ctypes.c_void_p(0)

        item_count = ctypes.c_long()
        sts = carbon.AECountItems(ctypes.byref(listdesc), ctypes.byref(item_count))
        if sts != 0:
            print("argvemulator warning: cannot unpack open url event")
            running = False
            return ctypes.c_void_p(0)

        desc = AEDesc()
        for i in range(item_count.value):
            sts = carbon.AEGetNthDesc(
                ctypes.byref(listdesc), i + 1, typeChar, 0, ctypes.byref(desc)
            )
            if sts != 0:
                print("argvemulator warning: cannot unpack open URL event")
                running = False
                return ctypes.c_void_p(0)

            sz = carbon.AEGetDescDataSize(ctypes.byref(desc))
            buf = ctypes.create_string_buffer(sz)
            sts = carbon.AEGetDescData(ctypes.byref(desc), buf, sz)
            if sts != 0:
                print("argvemulator warning: cannot extract open URL event")

            else:
                sys.argv.append(buf.value.decode("utf-8"))

        running = False
        return ctypes.c_void_p(0)

    carbon.AEInstallEventHandler(
        kCoreEventClass, kAEOpenApplication, open_app_handler, 0, FALSE
    )
    carbon.AEInstallEventHandler(
        kCoreEventClass, kAEOpenDocuments, open_file_handler, 0, FALSE
    )
    carbon.AEInstallEventHandler(
        kAEInternetSuite, kAEISGetURL, open_url_handler, 0, FALSE
    )

    # Remove the funny -psn_xxx_xxx argument
    if len(sys.argv) > 1 and sys.argv[1].startswith("-psn_"):
        del sys.argv[1]

    start = time.time()
    now = time.time()
    eventType = EventTypeSpec()
    eventType.eventClass = kEventClassAppleEvent
    eventType.eventKind = kEventAppleEvent

    try:
        while running and now - start < timeout:
            event = ctypes.c_void_p()

            sts = carbon.ReceiveNextEvent(
                1,
                ctypes.byref(eventType),
                start + timeout - now,
                TRUE,
                ctypes.byref(event),
            )

            if sts == eventLoopTimedOutErr:
                break

            elif sts != 0:
                print("argvemulator warning: fetching events failed")
                break

            # This does raise error
            # - 'TypeError: an integer is required (got type c_void_p)'
            # not sure what to do about it...
            # Looks like '/usr/bin/osascript' is set in '_' env variable
            #   when custom scheme is launcher, could be used?
            sts = carbon.AEProcessEvent(event)
            if sts != 0:
                print("argvemulator warning: processing events failed")
                break
    finally:
        carbon.AERemoveEventHandler(
            kCoreEventClass, kAEOpenApplication, open_app_handler, FALSE
        )
        carbon.AERemoveEventHandler(
            kCoreEventClass, kAEOpenDocuments, open_file_handler, FALSE
        )
        carbon.AERemoveEventHandler(
            kAEInternetSuite, kAEISGetURL, open_url_handler, FALSE
        )


def macos_main() -> None:
    # only use if started by LaunchServices
    _run_argvemulator()


def get_ayon_appdirs(*args):
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


def get_launcher_local_dir(*subdirs: str) -> str:
    """Get local directory for launcher.

    Local directory is used for storing machine or user specific data.

    The location is user specific.

    Note:
        This function should be called at least once on bootstrap.

    Args:
        *subdirs (str): Subdirectories relative to local dir.

    Returns:
        str: Path to local directory.

    """
    storage_dir = os.getenv("AYON_LAUNCHER_LOCAL_DIR")
    if not storage_dir:
        storage_dir = get_ayon_appdirs()
        os.environ["AYON_LAUNCHER_LOCAL_DIR"] = storage_dir

    return os.path.join(storage_dir, *subdirs)


# Store executables info to a file
def get_executables_info_filepath():
    """Get path to file where information about executables is stored.

    Returns:
        str: Path to json file where executables info are stored.
    """

    return get_launcher_local_dir("executables.json")


def get_executables_info():
    filepath = get_executables_info_filepath()
    data = {
        "file_version": "1.0.1",
        "available_versions": []
    }
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as stream:
                data = json.load(stream)

        except Exception:
            pass

    return data


def load_version_from_file(filepath):
    """Execute python file and return '__version__' variable."""

    with open(filepath, "r") as stream:
        version_content = stream.read()
    version_globals = {}
    exec(version_content, version_globals)
    return version_globals["__version__"]


def load_version_from_root(root):
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


def load_executable_version(executable):
    """Get version of executable.

    Args:
        executable (str): Path to executable.

    Returns:
        Union[str, None]: Version of executable.
    """

    if not executable:
        return None
    return load_version_from_root(os.path.dirname(executable))


class Executable:
    def __init__(self, path, version):
        self.path = path
        self.version = version
        self._exists = None
        self._semver_version = None

    def __repr__(self):
        return f"AYON Executable ({self.version}): '{self.path}'"

    def __eq__(self, other):
        return self.semver_version == other.semver_version

    def __lt__(self, other):
        return self.semver_version < other.semver_version

    def __gt__(self, other):
        return self.semver_version > other.semver_version

    def __ge__(self, other):
        return self.semver_version >= other.semver_version

    def __le__(self, other):
        return self.semver_version <= other.semver_version

    @property
    def exists(self):
        if self._exists is None:
            self._exists = os.path.exists(self.path)
        return self._exists

    @property
    def semver_version(self):
        if self._semver_version is None:
            try:
                self._semver_version = semver.VersionInfo.parse(self.version)
            except Exception:
                self._semver_version = semver.VersionInfo.parse("0.0.0")
        return self._semver_version


def main():
    executables_info = get_executables_info()

    executables = []
    for version_info in executables_info["available_versions"]:
        executable = version_info["executable"]
        version = load_executable_version(executable)
        executable = Executable(executable, version)
        if executable.exists:
            executables.append(executable)

    if not executables:
        raise RuntimeError(
            "Shim was not able to locate any AYON launcher executables."
        )
    executables.sort()
    executable = executables[-1]

    # Split dir and filename
    # - decide if filename should be 'ayon_console.exe' for windows
    #   other platforms have only 'ayon' executable
    executable_dir, executable_filename = os.path.split(executable.path)
    if (
        platform.system().lower() == "windows"
        and (
            not IS_BUILT_APPLICATION
            or "ayon_console" in os.path.basename(sys.argv[0])
        )
    ):
        executable_filename = "ayon_console.exe"

    executable_path = os.path.join(executable_dir, executable_filename)

    # Change first argument to executable path
    # - replace shim executable when running from build
    # - replace start python script path when running from code
    args = list(sys.argv)
    args[0] = executable_path
    sys.exit(subprocess.call(args))


if __name__ == "__main__":
    if macos_main is not None:
        macos_main()
    main()
