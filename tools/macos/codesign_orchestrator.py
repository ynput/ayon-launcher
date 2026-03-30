#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Orchestrate macOS code signing for app bundles.

This module handles deterministic signing of nested binaries,
frameworks, and the top-level app bundle in the correct order
to ensure valid signatures.

macOS ``codesign`` treats **every** file under ``Contents/MacOS/``
as a code object that must be individually code-signed.  Non-code
files (Python sources, data, configs) must therefore live under
``Contents/Resources/`` where they are sealed as hashed resources
instead.

Signing order (deepest content first):

 0. Strip +x from non-Mach-O files.
 1. Relocate non-code content from ``Contents/MacOS/`` to
    ``Contents/Resources/``, leaving relative symlinks behind so
    that runtime path resolution is unchanged.
 2. Discover every nested bundle (``.app`` / ``.framework``)
    anywhere in the tree and sort them deepest-first.
 3. For each nested bundle sign its loose Mach-O binaries, then
    seal the bundle itself.
 4. Sign loose Mach-O binaries in the top-level bundle that live
    outside any nested bundle.
 5. Seal the top-level ``.app`` bundle.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import logging
import os
import plistlib
import shutil
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterator, Optional

try:
    from .. import utils
except ImportError:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    utils = importlib.import_module("tools.utils")

_logger = utils.get_logger(__name__)  # Initialize logger

_CODESIGN_TIMEOUT = 120  # seconds
_FILE_CMD_TIMEOUT = 10  # seconds

# Bundle directory suffixes recognized by macOS code signing.
_BUNDLE_SUFFIXES = {".app", ".framework"}

# File extensions that are never Mach-O binaries.
_NON_BINARY_EXTENSIONS = frozenset(
    {
        # Python
        ".py",
        ".pyc",
        ".pyo",
        ".pyi",
        ".pth",
        ".typed",
        # Data / config
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".cfg",
        ".ini",
        ".conf",
        # Docs / text
        ".txt",
        ".rst",
        ".md",
        ".html",
        ".htm",
        ".css",
        # Apple / XML
        ".plist",
        ".xml",
        ".xsd",
        # Images
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".ico",
        ".icns",
        # Tabular
        ".csv",
        ".tsv",
        # C / C++ headers
        ".c",
        ".h",
        ".cpp",
        ".hpp",
    }
)


# -----------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------


@dataclasses.dataclass
class CodeSigningConfig:
    """Configuration for code signing operations.

    Attributes:
        signing_identity: Certificate identity (name or SHA-1 hash).
        team_id: 10-char alphanumeric Apple Team ID.
        entitlements_file: Path to ``.entitlements`` plist.
        strict: Raise on any signing error when True.
    """

    signing_identity: str
    team_id: Optional[str] = None
    entitlements_file: Optional[str] = None
    strict: bool = True

    def __post_init__(self) -> None:
        """Validate fields after initialisation.

        Raises:
            ValueError: If *team_id* is not a 10-char alphanumeric string.
            FileNotFoundError: If *entitlements_file* path does not exist.
        """
        if self.team_id and not self._is_valid_team_id(self.team_id):
            raise ValueError(
                f"Invalid team ID format: {self.team_id}"
            )
        if self.entitlements_file and not os.path.exists(
            self.entitlements_file
        ):
            raise FileNotFoundError(
                f"Entitlements not found: {self.entitlements_file}"
            )

    @staticmethod
    def _is_valid_team_id(team_id: str) -> bool:
        return len(team_id) == 10 and team_id.isalnum()

    def to_dict(self) -> dict[str, Any]:
        """Return config as a plain dictionary.

        Returns:
            Dictionary representation of this config.
        """
        return dataclasses.asdict(self)


# -----------------------------------------------------------------
# Signer
# -----------------------------------------------------------------


class MacOSCodeSigner:
    """Sign a macOS ``.app`` bundle inside-out."""

    def __init__(
        self,
        config: CodeSigningConfig,
        dry_run: bool = False,
        max_workers: int = 4,
    ):
        """Initialise the signer.

        Args:
            config: Signing configuration.
            dry_run: Print commands without executing when True.
            max_workers: Thread-pool size for parallel signing.
        """
        self.config = config
        self.dry_run = dry_run
        self.max_workers = max_workers
        self.signed_items: list[str] = []
        self.unsigned_items: list[str] = []
        self._lock = threading.Lock()
        # Cache results of expensive `file` subprocess calls keyed by path.
        self._mach_o_cache: dict[str, bool] = {}

    # =============================================================
    # Public entry point
    # =============================================================

    def sign_app_bundle(self, app_path: str) -> bool:
        """Sign a ``.app`` bundle with all nested content.

        Args:
            app_path: Path to the ``.app`` bundle.

        Returns:
            True if every signing step succeeded.
        """
        app = Path(app_path)
        if not (app / "Contents").exists():
            msg = f"Invalid app bundle: {app_path}"
            if self.config.strict:
                raise ValueError(msg)
            _logger.error(msg)
            return False

        _logger.info(f"Signing {app.name}")
        ok = True

        # Pre-step — strip extended attributes (resource forks,
        # Finder info, quarantine flags, etc.).  codesign refuses
        # to seal a bundle that contains these.
        _logger.info("Stripping extended attributes …")
        self._strip_xattrs(app)

        # Step 0 — strip +x from non-Mach-O files.
        _logger.info("Step 0: Stripping spurious +x bits …")
        self._strip_spurious_exec_bits(app)

        # Step 1 — move non-code out of Contents/MacOS/.
        _logger.info(
            "Step 1: Relocating non-code content to Contents/Resources/ …"
        )
        self._relocate_to_resources(app)

        # Step 2 — sign nested bundles (deepest first, same-depth in
        # parallel).
        nested = self._find_nested_bundles(app)
        if nested:
            _logger.info(
                f"Step 2: Signing {len(nested)} nested "
                f"bundle(s) (inside-out) …"
            )
            # Group by depth; process each level deepest-first.
            depth_groups: dict[int, list[Path]] = {}
            for bnd in nested:
                depth = len(bnd.parts)
                depth_groups.setdefault(depth, []).append(bnd)

            with ThreadPoolExecutor(
                max_workers=self.max_workers,
                thread_name_prefix="codesign",
            ) as executor:
                for depth in sorted(depth_groups, reverse=True):
                    group = depth_groups[depth]
                    _logger.debug(
                        f"Signing {len(group)} bundle(s) at depth {depth}"
                    )
                    futures = {
                        executor.submit(self._sign_nested_bundle, bnd): bnd
                        for bnd in group
                    }
                    for fut in as_completed(futures):
                        bnd = futures[fut]
                        try:
                            if not fut.result():
                                ok = False
                        except Exception as exc:
                            _logger.error(f"Error signing bundle {bnd}: {exc}")
                            ok = False
        else:
            _logger.info("Step 2: No nested bundles found.")

        # Step 3 — sign loose Mach-O binaries.
        _logger.info("Step 3: Signing loose Mach-O binaries …")
        if not self._sign_loose_binaries(app, nested):
            ok = False

        # Step 4 — seal the top-level app bundle.
        _logger.info("Step 4: Sealing top-level app bundle …")
        if not self._sign_item(str(app), is_bundle=True):
            ok = False

        _logger.info(
            f"Done — signed: {len(self.signed_items)}, "
            f"unsigned: {len(self.unsigned_items)}"
        )
        if self.unsigned_items:
            msg = f"Unsigned: {self.unsigned_items}"
            if self.config.strict:
                raise RuntimeError(msg)
            _logger.warning(msg)
            ok = False

        return ok

    # =============================================================
    # Pre-step — strip extended attributes
    # =============================================================

    @staticmethod
    def _strip_xattrs(app: Path) -> None:
        """Remove all extended attributes from the bundle.

        macOS ``codesign`` refuses to sign bundles that contain
        resource forks, Finder information, or quarantine flags.
        Running ``xattr -cr`` recursively on the bundle root
        clears everything.

        Args:
            app: ``.app`` bundle root.
        """
        if not shutil.which("xattr"):
            raise RuntimeError("xattr tool not found")

        subprocess.run(
            ["xattr", "-cr", str(app)],
            check=True,
            timeout=_CODESIGN_TIMEOUT,
        )

    # =============================================================
    # Step 0 — strip executable bits
    # =============================================================

    def _strip_spurious_exec_bits(self, app: Path) -> None:
        """Remove +x from non-Mach-O files in the bundle.

        Args:
            app: ``.app`` bundle root.
        """
        stripped = 0
        for item in self._walk_real(app):
            if not item.is_file():
                continue
            if not os.access(str(item), os.X_OK):
                continue
            is_non_binary = (
                item.suffix.lower() in _NON_BINARY_EXTENSIONS
                or not self._is_mach_o(str(item))
            )
            if is_non_binary:
                item.chmod(item.stat().st_mode & ~0o111)
                stripped += 1
        _logger.info(f"Stripped +x from {stripped} non-Mach-O files")

    # =============================================================
    # Step 1 — relocate non-code to Contents/Resources/
    # =============================================================

    def _relocate_to_resources(self, app: Path) -> None:
        """Move non-code from MacOS/ to Resources/.

        For every top-level entry in ``Contents/MacOS/``:
        * **Directories** are always moved (they may contain a
          mix of code and non-code — the symlink keeps runtime
          paths working, while codesign does not follow it).
        * **Files** that are not Mach-O binaries are moved.
        * **Mach-O files** stay in ``Contents/MacOS/``.

        A relative symlink is left behind so the application's
        path resolution is unchanged.

        Args:
            app: ``.app`` bundle root.
        """
        macos = app / "Contents" / "MacOS"
        resources = app / "Contents" / "Resources"
        resources.mkdir(exist_ok=True)

        relocated = 0
        for entry in os.scandir(str(macos)):
            src = Path(entry.path)

            if entry.is_symlink():
                continue

            # Keep Mach-O *files* in MacOS/.
            if entry.is_file(follow_symlinks=False) and self._is_mach_o(
                str(src)
            ):
                continue

            dst = resources / src.name
            if dst.exists():
                _logger.warning(
                    f"Skip relocate {src.name}: already in Resources/"
                )
                continue

            shutil.move(str(src), str(dst))
            os.symlink(
                os.path.join("..", "Resources", src.name),
                str(src),
            )
            _logger.info(f"Relocated: {src.name} → Resources/{src.name}")
            relocated += 1

        _logger.info(f"Relocated {relocated} item(s)")

    # =============================================================
    # Step 2 — discover & sign nested bundles
    # =============================================================

    def _find_nested_bundles(self, app: Path) -> list[Path]:
        """Find all ``.app`` / ``.framework`` bundles.

        Returns them deepest-first so inner content is always
        sealed before its parent.  The top-level *app* itself
        is excluded.

        Args:
            app: Top-level ``.app`` path.

        Returns:
            Sorted list of nested bundle paths.
        """
        bundles: list[Path] = []
        for item in self._walk_real(app):
            if item == app:
                continue
            if item.is_dir() and item.suffix in _BUNDLE_SUFFIXES:
                bundles.append(item)
        bundles.sort(key=lambda p: len(p.parts), reverse=True)
        return bundles

    def _sign_nested_bundle(self, bundle: Path) -> bool:
        """Sign a nested ``.framework`` or ``.app``.

        1. Sign loose Mach-O files (excluding deeper
           sub-bundles that were already signed).
        2. Seal the bundle.

        Args:
            bundle: Path to the nested bundle.

        Returns:
            True if all steps succeeded.
        """
        sub_bundles = [
            d
            for d in self._walk_real(bundle)
            if d.is_dir() and d != bundle and d.suffix in _BUNDLE_SUFFIXES
        ]

        mach_o_files = [
            str(fpath)
            for fpath in sorted(self._walk_real(bundle))
            if fpath.is_file()
            and not self._inside_any(fpath, sub_bundles)
            and self._is_mach_o(str(fpath))
        ]

        _logger.debug(
            f"Signing {len(mach_o_files)} loose file(s) in {bundle.name}"
        )
        ok = self._sign_files_parallel(mach_o_files)

        # Seal the bundle only after all its contents are signed.
        if not self._sign_item(str(bundle), is_bundle=True):
            ok = False
        return ok

    # =============================================================
    # Step 3 — sign loose binaries in the top-level app
    # =============================================================

    def _sign_loose_binaries(
        self,
        app: Path,
        nested_bundles: list[Path],
    ) -> bool:
        """Sign Mach-O files not inside any nested bundle.

        The main executable (CFBundleExecutable) is skipped here;
        it is signed as part of the top-level bundle seal.

        Args:
            app: Top-level ``.app`` path.
            nested_bundles: Already-signed nested bundles.

        Returns:
            True if all signings succeeded.
        """
        main_exec = self._get_main_executable(app)
        main_resolved = main_exec.resolve() if main_exec else None

        mach_o_files: list[str] = []
        for fpath in sorted(self._walk_real(app)):
            if not fpath.is_file():
                continue
            if self._inside_any(fpath, nested_bundles):
                continue
            if main_resolved and fpath.resolve() == main_resolved:
                _logger.info(f"Skipping (bundle exec): {fpath.name}")
                continue
            if self._is_mach_o(str(fpath)):
                mach_o_files.append(str(fpath))

        _logger.debug(f"Signing {len(mach_o_files)} loose top-level file(s)")
        return self._sign_files_parallel(mach_o_files)

    # =============================================================
    # Low-level codesign wrapper
    # =============================================================

    def _sign_item(
        self,
        file_path: str,
        is_bundle: bool = False,
    ) -> bool:
        """Invoke ``codesign`` on a single path.

        Args:
            file_path: File or bundle to sign.
            is_bundle: Apply entitlements / hardened-runtime
                flags when True.

        Returns:
            True on success.
        """
        cmd = [
            "codesign",
            "--force",
            "--timestamp",
            "--sign",
            self.config.signing_identity,
        ]
        if is_bundle and self.config.entitlements_file:
            cmd.extend(
                [
                    "--entitlements",
                    self.config.entitlements_file,
                ]
            )

        needs_runtime = (is_bundle and self.config.team_id) or os.access(
            file_path, os.X_OK
        )
        if needs_runtime:
            cmd.extend(["--options", "runtime"])

        cmd.append(file_path)

        try:
            if self.dry_run:
                _logger.info(f"[DRY RUN] {' '.join(cmd)}")
                with self._lock:
                    self.signed_items.append(file_path)
                return True

            subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=_CODESIGN_TIMEOUT,
            )
            _logger.info(f"Signed: {file_path}")
            with self._lock:
                self.signed_items.append(file_path)
            return True

        except subprocess.CalledProcessError as exc:
            _logger.error(f"Failed to sign {file_path}: {exc.stderr}")
            with self._lock:
                self.unsigned_items.append(file_path)
            if self.config.strict:
                raise
            return False

        except Exception as exc:
            _logger.error(f"Unexpected error signing {file_path}: {exc}")
            with self._lock:
                self.unsigned_items.append(file_path)
            if self.config.strict:
                raise
            return False

    def _sign_files_parallel(self, files: list[str]) -> bool:
        """Sign a list of files in parallel using the thread pool.

        Args:
            files: File paths to sign.

        Returns:
            True if every file was signed successfully.
        """
        if not files:
            return True
        ok = True
        with ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="codesign",
        ) as executor:
            futures = {executor.submit(self._sign_item, f): f for f in files}
            for fut in as_completed(futures):
                fpath = futures[fut]
                try:
                    if not fut.result():
                        ok = False
                except Exception as exc:
                    _logger.error(f"Error signing {fpath}: {exc}")
                    ok = False
        return ok

    # =============================================================
    # Helpers
    # =============================================================

    @staticmethod
    def _walk_real(root: Path) -> Iterator[Path]:
        """Yield every real (non-symlink) entry under *root*.

        Uses an explicit stack instead of recursion to avoid hitting
        Python's default recursion limit on deeply nested bundles
        (e.g. ``Qt.framework/Versions/A/…``).

        Does **not** follow directory symlinks, preventing
        double-processing after relocation creates symlinks
        in ``Contents/MacOS/``.

        Args:
            root: Directory to walk.

        Yields:
            Paths to real files and directories.
        """
        stack: list[Path] = [root]
        while stack:
            current = stack.pop()
            try:
                entries = list(os.scandir(str(current)))
            except PermissionError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                path = Path(entry.path)
                yield path
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)

    @staticmethod
    def _get_main_executable(
        app: Path,
    ) -> Optional[Path]:
        """Read CFBundleExecutable from Info.plist.

        Args:
            app: ``.app`` bundle root.

        Returns:
            Path to the main executable, or None.
        """
        plist = app / "Contents" / "Info.plist"
        if not plist.exists():
            return None
        try:
            with open(plist, "rb") as fh:
                data = plistlib.load(fh)
        except Exception:
            return None
        name = data.get("CFBundleExecutable")
        if not name:
            return None
        path = app / "Contents" / "MacOS" / name
        return path if path.exists() else None

    @staticmethod
    def _inside_any(path: Path, containers: list[Path]) -> bool:
        """True if *path* is inside any *container*.

        Args:
            path: File path to test.
            containers: Bundle root directories.
        """
        for c in containers:
            try:
                path.relative_to(c)
                return True
            except ValueError:
                continue
        return False

    def _is_mach_o(self, file_path: str) -> bool:
        """True if *file_path* is a Mach-O binary.

        Results are cached so each path is only probed once via the
        ``file(1)`` subprocess, regardless of how many signing passes
        inspect the same file.

        Args:
            file_path: Absolute path to the file to probe.

        Returns:
            True if the file is a Mach-O or universal binary.
        """
        cached = self._mach_o_cache.get(file_path)
        if cached is not None:
            return cached
        try:
            result = subprocess.run(
                ["file", file_path],
                capture_output=True,
                text=True,
                check=True,
                timeout=_FILE_CMD_TIMEOUT,
            )
            out = result.stdout.lower()
            is_binary = "mach-o" in out or "universal binary" in out
        except Exception:
            is_binary = False
        self._mach_o_cache[file_path] = is_binary
        return is_binary


# -----------------------------------------------------------------
# Standalone helpers
# -----------------------------------------------------------------


def verify_signature(file_path: str, strict: bool = True) -> bool:
    """Verify code signature on a file or app bundle.

    Args:
        file_path: Path to file or app bundle.
        strict: Raise on failure when True.

    Returns:
        True if valid.
    """
    try:
        result = subprocess.run(
            [
                "codesign",
                "--verify",
                "--verbose",
                file_path,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_CODESIGN_TIMEOUT,
        )
    except Exception as exc:
        msg = f"codesign verify error: {file_path}: {exc}"
        if strict:
            raise RuntimeError(msg) from exc
        _logger.error(msg)
        return False

    if result.returncode == 0:
        _logger.info(f"Verified: {file_path}")
        return True

    msg = f"Verification failed: {file_path}: {result.stderr}"
    if strict:
        raise RuntimeError(msg)
    _logger.error(msg)
    return False


def get_signature_requirements(
    file_path: str,
) -> Optional[str]:
    """Return designated requirements string, or None."""
    try:
        result = subprocess.run(
            ["codesign", "-d", "-r-", file_path],
            capture_output=True,
            text=True,
            check=True,
            timeout=_CODESIGN_TIMEOUT,
        )
        return result.stdout.strip()
    except Exception:
        return None


# -----------------------------------------------------------------
# CLI
# -----------------------------------------------------------------


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description=("Sign a macOS .app bundle with deterministic ordering."),
    )
    parser.add_argument(
        "app_path",
        help="Path to .app bundle",
    )
    parser.add_argument(
        "--identity",
        required=True,
        help="Signing identity (name or hash)",
    )
    parser.add_argument(
        "--team-id",
        help="Team ID (for hardened runtime)",
    )
    parser.add_argument(
        "--entitlements",
        help="Path to .entitlements plist",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Thread-pool size for parallel signing (default: 4)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify signatures after signing",
    )
    parser.add_argument(
        "--non-strict",
        action="store_true",
        help="Warn on errors instead of failing",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        _logger.setLevel(logging.DEBUG)

    try:
        config = CodeSigningConfig(
            signing_identity=args.identity,
            team_id=args.team_id,
            entitlements_file=args.entitlements,
            strict=not args.non_strict,
        )
        signer = MacOSCodeSigner(
            config,
            dry_run=args.dry_run,
            max_workers=args.workers,
        )

        _logger.info(
            f"Signing configuration: {json.dumps(config.to_dict(), indent=4)}"
        )
        success = signer.sign_app_bundle(args.app_path)

        if args.verify and not args.dry_run:
            _logger.info("Verifying signatures …")
            if verify_signature(args.app_path):
                _logger.info("All signatures verified")
            else:
                _logger.error("Verification failed")
                success = False

        return 0 if success else 1

    except Exception as exc:
        _logger.error(f"Fatal error: {exc}")
        raise


if __name__ == "__main__":
    sys.exit(main())
