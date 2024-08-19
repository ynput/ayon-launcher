import os
import sys
import struct
import ctypes
import time
import subprocess

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
                break

            # This does raise error
            # - 'TypeError: an integer is required (got type c_void_p)'
            # not sure what to do about it...
            # Looks like '/usr/bin/osascript' is set in '_' env variable
            #   when custom scheme is launcher, could be used?
            sts = carbon.AEProcessEvent(event)
            if sts != 0:
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


def main():
    # Trigger new process and close this
    # - we just lost track about the process which can be issue
    #   if shim is used for validation if process finished
    args = list(sys.argv)
    if getattr(sys, "frozen", False):
        macos_root = os.path.dirname(sys.executable)
    else:
        macos_root = os.path.dirname(os.path.abspath(__file__))
    args[0] = os.path.join(macos_root, "ayon")

    mac_args = ["open", "-na", args.pop(0)]
    if args:
        mac_args.append("--args")
        mac_args.extend(args)
    sys.exit(subprocess.call(mac_args))


if __name__ == "__main__":
    main()
