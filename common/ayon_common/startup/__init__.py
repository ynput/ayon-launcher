"""Helpers for startup script."""
import os
import json
import subprocess
import tempfile

from ayon_common.utils import get_ayon_launch_args


def show_startup_error(title, message, detail=None):
    """Show startup error message.

    This will trigger a subprocess with UI message dialog.

    Args:
        title (str): Message title.
        message (str): Message content.
    """

    current_dir = os.path.dirname(os.path.abspath(__file__))
    ui_dir = os.path.join(current_dir, "ui")
    script_path = os.path.join(ui_dir, "startup_error.py")
    with tempfile.NamedTemporaryFile(
        suffix=".json", delete=False
    ) as tmp:
        filepath = tmp.name

    with open(filepath, "w") as stream:
        json.dump(
            {
                "title": title,
                "message": message,
                "detail": detail,
            },
            stream
        )

    args = get_ayon_launch_args(
        script_path, "--skip-bootstrap", filepath
    )
    try:
        subprocess.call(args)
    finally:
        os.remove(filepath)
