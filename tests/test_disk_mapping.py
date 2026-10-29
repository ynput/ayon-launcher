"""Regression tests for startup disk mapping without launcher side effects."""

import ast
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from typing import Optional
from unittest.mock import Mock

import pytest


@pytest.fixture
def startup():
    """Load mapping functions without changing environment or loading Qt."""
    path = Path(__file__).resolve().parents[1] / "start.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = ast.Module(
        body=[
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in {
                "_prepare_disk_mapping_args", "_run_disk_mapping"
            }
        ],
        type_ignores=[],
    )
    namespace = {
        "Optional": Optional,
        "os": SimpleNamespace(path=SimpleNamespace(exists=lambda _: False)),
        "platform": SimpleNamespace(system=lambda: "Windows"),
        "subprocess": subprocess,
        "logger": Mock(),
        "_get_core_settings": Mock(return_value={}),
    }
    exec(compile(functions, str(path), "exec"), namespace)
    return namespace


def _set_mappings(startup, items):
    """Supply server settings for the selected platform."""
    platform = startup["platform"].system().lower()
    startup["_get_core_settings"].return_value = {
        "disk_mapping": {platform: items}
    }


def test_mapping_waits_for_completion_before_next_mapping(startup, tmp_path):
    """Later mappings and startup can rely on completed mapping commands."""
    marker = tmp_path / "finished"
    scripts = [
        "import pathlib, time; time.sleep(0.1); "
        f"pathlib.Path({str(marker)!r}).write_text('mapped')",
        f"import pathlib; assert pathlib.Path({str(marker)!r}).is_file()",
    ]
    prepare = Mock(side_effect=[
        [sys.executable, "-c", script] for script in scripts
    ])
    startup["_prepare_disk_mapping_args"] = prepare
    _set_mappings(startup, [
        {"source": "source1", "destination": "destination1"},
        {"source": "source2", "destination": "destination2"},
    ])

    startup["_run_disk_mapping"]("1.0.0")

    assert marker.read_text() == "mapped"
    assert prepare.call_count == 2
    startup["logger"].exception.assert_not_called()


def test_nonzero_exit_is_logged_and_stops_mapping(startup):
    """An asynchronous child's failure must reach the startup caller."""
    args = [sys.executable, "-c", "import time; time.sleep(0.1); exit(7)"]
    prepare = Mock(return_value=args)
    startup["_prepare_disk_mapping_args"] = prepare
    _set_mappings(startup, [
        {"source": "source", "destination": "destination"},
        {"source": "later", "destination": "later"},
    ])

    with pytest.raises(subprocess.CalledProcessError) as exc:
        startup["_run_disk_mapping"]("1.0.0")

    assert exc.value.returncode == 7
    assert exc.value.cmd == args
    prepare.assert_called_once_with("source", "destination")
    startup["logger"].exception.assert_called_once_with(
        "Error in mapping drive", src_path="source", dst_path="destination"
    )


@pytest.mark.parametrize("error", [
    FileNotFoundError("missing executable"),
    PermissionError("access denied"),
])
def test_launch_error_is_logged_and_propagated(startup, error):
    """Include mapping context when the command cannot even start."""
    startup["subprocess"] = SimpleNamespace(
        run=Mock(side_effect=error),
        Popen=Mock(side_effect=error),
        CalledProcessError=subprocess.CalledProcessError,
    )
    _set_mappings(startup, [
        {"source": "source", "destination": "destination"}
    ])

    with pytest.raises(type(error)) as exc:
        startup["_run_disk_mapping"]("1.0.0")

    assert exc.value is error
    startup["logger"].exception.assert_called_once_with(
        "Error in mapping drive", src_path="source", dst_path="destination"
    )
