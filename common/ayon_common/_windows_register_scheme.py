import os
import subprocess

import winreg

SCRIPT_PATH = os.path.abspath(__file__)
PROTOCOL_NAME = "ayon-launcher"
PROTOCOL_PATH = "\\".join(["SOFTWARE", "Classes", PROTOCOL_NAME])
_REG_ICON_PATH = "\\".join([PROTOCOL_PATH, "DefaultIcon"])
_REG_COMMAND_PATH = "\\".join([PROTOCOL_PATH, "shell", "open", "command"])


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


def _update_reg(shim_icon_path, shim_command):
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        PROTOCOL_PATH,
        access=winreg.KEY_WRITE
    ) as key:
        winreg.SetValueEx(
            key, "URL Protocol", 0, winreg.REG_SZ, ""
        )

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        _REG_ICON_PATH,
        access=winreg.KEY_WRITE
    ) as key:
        winreg.SetValueEx(
            key, "", 0, winreg.REG_SZ, shim_icon_path
        )

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
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
        not _reg_exists(winreg.HKEY_CURRENT_USER, PROTOCOL_PATH)
        or not _reg_exists(winreg.HKEY_CURRENT_USER, _REG_ICON_PATH)
        or not _reg_exists(winreg.HKEY_CURRENT_USER, _REG_COMMAND_PATH)
    ):
        return True

    # Check if protocol has set version
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        PROTOCOL_PATH,
        0,
        winreg.KEY_READ
    ) as key:
        _, values_count, _ = winreg.QueryInfoKey(key)
        if not values_count:
            return True

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
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
        winreg.HKEY_CURRENT_USER,
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


def _get_shim_icon(shim_path: str) -> str:
    return subprocess.list2cmdline([shim_path])


def _get_shim_command(shim_path: str) -> str:
    cmd = subprocess.list2cmdline([shim_path])
    return f'{cmd} "%1"'


def is_reg_set(shim_path: str) -> bool:
    shim_icon_path = _get_shim_icon(shim_path)
    shim_command = _get_shim_command(shim_path)
    return not _needs_update(shim_icon_path, shim_command)


def set_reg(shim_path: str) -> bool:
    shim_icon_path = _get_shim_icon(shim_path)
    shim_command = _get_shim_command(shim_path)
    if _needs_update(shim_icon_path, shim_command):
        return _update_reg(shim_icon_path, shim_command)
    return True
