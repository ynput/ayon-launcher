# QML login

Both `ask_to_login` and `change_user` use `QmlServerLoginWindow`. When the
user is signed in on the connected server (the current session in
`change_user`, or a valid supplied API key in `ask_to_login`) the dialog
shows the account with its avatar instead of the login options: continue,
log into another account (shows the login options) or log out with an
inline confirmation. Continuing the current session closes the dialog
without changes; a confirmed logout of it returns `(None, None, None, True)`
and the caller expires the token. Logging out of a supplied API key expires
the token on the server right away and shows the login options.

Once connected, the studio logo and login background set in the server's
customization replace the AYON logo and the plain background. They and the
avatar load in the background and fade in; the login flow never waits for
them.

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

## Testing

There is no automated test suite for the dialog. Manually check both login
methods against a configured AYON server before release, and check supported
platforms and frozen builds when validating packaging. For environments
without a display, set `QT_QPA_PLATFORM=offscreen` and
`QT_QUICK_BACKEND=software`.
