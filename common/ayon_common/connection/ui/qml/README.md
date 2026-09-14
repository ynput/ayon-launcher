# QML login

The default unsigned-in flow in `ask_to_login` uses `QmlServerLoginWindow`.
Existing signed-in account management and `change_user` retain the widget
dialog, including its logout confirmation and result contract.

The first page normalizes the server URL and checks the AYON API before
enabling the sign-in page. Password authentication uses `login_to_server`;
browser authentication uses the existing local callback listener and checks
the returned token against the server. Browser login requires server 1.3.2
or newer. The controller preserves forced usernames, expires browser waits
after three minutes, and ignores requests completed after cancellation.

Network requests run in background threads. Tokens are returned to the caller
for the existing credential-storage flow; the QML UI does not store passwords
or tokens. Closing the standalone window does not save a successful login.

## Run just the login dialog

After creating the project environment and installing runtime dependencies,
run from the repository root:

```powershell
$env:PYTHONPATH = "$PWD/common;$PWD/vendor/python"
uv run python -m ayon_common.connection.ui.qml_login
```

```bash
PYTHONPATH="$PWD/common:$PWD/vendor/python" uv run python -m ayon_common.connection.ui.qml_login
```

The QML uses Qt Quick 2.15 and Qt Quick Templates 2.15 through QtPy, without
setting a process-wide Qt Quick Controls style. The `common` directory is
already included by the launcher build; QML files and the existing AYON icon
travel with it. The installed Qt runtime must include Qt Quick/QML plugins.

## Offline tests

With the same `PYTHONPATH`, run:

```sh
uv run python -m pytest common/ayon_common/connection/ui/tests/test_qml_login.py
```

For environments without a display, set `QT_QPA_PLATFORM=offscreen` and
`QT_QUICK_BACKEND=software`. Tests use mocked authentication and a loopback
callback; they do not need a real AYON server or open a browser. Manually
check both login methods against a configured AYON server before release,
and check supported platforms and frozen builds when validating packaging.
