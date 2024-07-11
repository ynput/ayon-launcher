import os
import sys
import json
import subprocess
import tempfile

import winreg

SCRIPT_PATH = os.path.abspath(__file__)
PROTOCOL_NAME = "ayon-launcher"
_REG_ICON_PATH = "\\".join([PROTOCOL_NAME, "DefaultIcon"])
_REG_COMMAND_PATH = "\\".join([PROTOCOL_NAME, "shell", "open", "command"])


def _reg_exists(root, path):
    try:
        handle = winreg.OpenKey(
            root,
            path,
            0,
            winreg.KEY_READ
        )
        handle.Close()
        return True
    except FileNotFoundError:
        return False


def _update_reg_in_subprocess(shim_icon_path, shim_command):
    import win32con
    import win32process
    import win32event
    import pywintypes
    from win32comext.shell.shell import ShellExecuteEx
    from win32comext.shell import shellcon

    with tempfile.NamedTemporaryFile(
        prefix="ayon_reg", mode="w", delete=False
    ) as tmp:
        tmp.write(json.dumps({
            "icon": shim_icon_path,
            "command": shim_command
        }))
        tmp_path = tmp.name

    executable = sys.executable
    command = subprocess.list2cmdline([SCRIPT_PATH, tmp_path])
    try:
        process_info = ShellExecuteEx(
            nShow=win32con.SW_SHOWNORMAL,
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS,
            lpVerb="runas",
            lpFile=executable,
            lpParameters=command,
            lpDirectory=os.path.dirname(executable)
        )

    except pywintypes.error:
        # User cancelled UAC dialog
        return False

    process_handle = process_info["hProcess"]
    win32event.WaitForSingleObject(process_handle, win32event.INFINITE)
    returncode = win32process.GetExitCodeProcess(process_handle)
    if returncode != 0:
        return False

    with open(tmp_path, "r") as stream:
        data = json.load(stream)
    return data.get("success", False)


def _update_reg(shim_icon_path, shim_command, force_current_process=False):
    try:
        with winreg.CreateKeyEx(
            winreg.HKEY_CLASSES_ROOT,
            PROTOCOL_NAME,
            access=winreg.KEY_WRITE
        ) as key:
            winreg.SetValueEx(
                key, "URL Protocol", 0, winreg.REG_SZ, ""
            )
    except PermissionError:
        if force_current_process:
            raise RuntimeError("Failed to set registry keys")
        return _update_reg_in_subprocess(shim_icon_path, shim_command)

    with winreg.CreateKeyEx(
        winreg.HKEY_CLASSES_ROOT,
        _REG_ICON_PATH,
        access=winreg.KEY_WRITE
    ) as key:
        winreg.SetValueEx(
            key, "", 0, winreg.REG_SZ, shim_icon_path
        )

    with winreg.CreateKeyEx(
        winreg.HKEY_CLASSES_ROOT,
        _REG_COMMAND_PATH,
        access=winreg.KEY_WRITE
    ) as key:
        winreg.SetValueEx(
            key, "", 0, winreg.REG_SZ, shim_command
        )
    return True


def _needs_update(shim_icon_path, shim_command):
    # Validate existence of all required registry keys
    if (
        not _reg_exists(winreg.HKEY_CLASSES_ROOT, PROTOCOL_NAME)
        or not _reg_exists(winreg.HKEY_CLASSES_ROOT, _REG_ICON_PATH)
        or not _reg_exists(winreg.HKEY_CLASSES_ROOT, _REG_COMMAND_PATH)
    ):
        return True

    # Check if protocol has set version
    with winreg.OpenKey(
        winreg.HKEY_CLASSES_ROOT,
        PROTOCOL_NAME,
        0,
        winreg.KEY_READ
    ) as key:
        _, values_count, _ = winreg.QueryInfoKey(key)
        if not values_count:
            return True

    with winreg.OpenKey(
        winreg.HKEY_CLASSES_ROOT,
        _REG_ICON_PATH,
        0,
        winreg.KEY_READ
    ) as key:
        value, _ = winreg.QueryValueEx(key, "")
        if not value:
            return True

        if value != shim_icon_path:
            return True

    with winreg.OpenKey(
        winreg.HKEY_CLASSES_ROOT,
        _REG_COMMAND_PATH,
        0,
        winreg.KEY_READ
    ) as key:
        value, _ = winreg.QueryValueEx(key, "")
        if not value:
            return True
        if value != shim_command:
            return True
    return False


def is_reg_set(shim_path: str) -> bool:
    shim_icon_path = subprocess.list2cmdline([shim_path])
    shim_command = subprocess.list2cmdline([
        shim_path, '"%1"'
    ])
    return not _needs_update(shim_icon_path, shim_command)


def set_reg(shim_path: str) -> bool:
    shim_icon_path = subprocess.list2cmdline([shim_path])
    shim_command = subprocess.list2cmdline([
        shim_path, '"%1"'
    ])
    if _needs_update(shim_icon_path, shim_command):
        return _update_reg(shim_icon_path, shim_command)
    return True


if __name__ == "__main__":
    json_path = sys.argv.pop(-1)
    with open(json_path, "r") as stream:
        data = json.load(stream)
    shim_command = data["command"]
    shim_icon_path = data["icon"]
    _update_reg(shim_icon_path, shim_command, True)
    data["success"] = True
    with open(json_path, "w") as stream:
        json.dump(data, stream)
