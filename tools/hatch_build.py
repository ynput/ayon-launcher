"""Hatch task entrypoints for AYON launcher build and package workflows."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = REPO_ROOT / "build"


def _run(command: list[str], cwd: Path | None = None) -> None:
    process = subprocess.run(command, cwd=str(cwd) if cwd else None)
    if process.returncode != 0:
        raise RuntimeError(f"Command failed ({process.returncode}): {' '.join(command)}")


def _run_to_log(command: list[str], log_path: Path, cwd: Path | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    log_path.write_text((result.stdout or "") + (result.stderr or ""), encoding="utf-8")
    if result.returncode != 0:
        raise RuntimeError(f"Build command failed. See log: {log_path}")


def _build_command_for_platform() -> str:
    if sys.platform == "darwin":
        return "bdist_mac"
    return "build"


def _build_shim() -> None:
    command = [sys.executable, "setup.py", _build_command_for_platform()]
    _run_to_log(command, REPO_ROOT / "shim" / "build.log", cwd=REPO_ROOT / "shim")


def _build_launcher() -> None:
    command = [
        "cargo", "build",
        "-p", "shim",
        "--features", "gui",
        "--release"]
    _run_to_log(command, BUILD_ROOT / "build.log", cwd=REPO_ROOT)
    command = [
        "cargo", "build",
        "-p", "shim",
        "--features", "ayon_console",
        "--release"]
    _run_to_log(command, BUILD_ROOT / "build.log", cwd=REPO_ROOT)


def _store_requirements_snapshot() -> None:
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    freeze_output = subprocess.check_output(
        [sys.executable, "-m", "pip", "freeze"],
        text=True,
    )
    (BUILD_ROOT / "requirements.txt").write_text(freeze_output, encoding="utf-8")
    _run([sys.executable, str(REPO_ROOT / "tools" / "_venv_deps.py")])


def _run_post_build() -> None:
    _run([sys.executable, str(REPO_ROOT / "tools" / "build_post_process.py"), "build"])


def _run_make_installer() -> None:
    _run(
        [sys.executable, str(REPO_ROOT / "tools" / "build_post_process.py"), "make-installer"]
    )


def _run_packaging(formats: list[str]) -> None:
    _run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "package_builds.py"),
            "--build-root",
            str(BUILD_ROOT),
            "--formats",
            *formats,
        ]
    )


def _build(make_installer: bool = False) -> None:
    _build_shim()
    _store_requirements_snapshot()
    _build_launcher()
    _run_post_build()
    if make_installer:
        _run_make_installer()


def main() -> int:
    parser = argparse.ArgumentParser(description="Hatch-powered build helper")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("build-shim")
    subparsers.add_parser("build-launcher")
    subparsers.add_parser("build")
    subparsers.add_parser("make-installer")
    subparsers.add_parser("build-make-installer")
    subparsers.add_parser("package-conda")
    subparsers.add_parser("package-rez")
    subparsers.add_parser("package-all")
    subparsers.add_parser("build-package")

    args = parser.parse_args()

    if args.command == "build-shim":
        _build_shim()
    elif args.command == "build-launcher":
        _store_requirements_snapshot()
        _build_launcher()
    elif args.command == "build":
        _build(make_installer=False)
    elif args.command == "make-installer":
        _run_make_installer()
    elif args.command == "build-make-installer":
        _build(make_installer=True)
    elif args.command == "package-conda":
        _run_packaging(["conda"])
    elif args.command == "package-rez":
        _run_packaging(["rez"])
    elif args.command == "package-all":
        _run_packaging(["conda", "rez"])
    elif args.command == "build-package":
        _build(make_installer=True)
        _run_packaging(["conda", "rez"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
