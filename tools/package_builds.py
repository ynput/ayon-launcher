"""Generate conda and rez package layouts from an existing AYON launcher build."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _read_metadata(build_root: Path) -> dict:
    metadata_path = build_root / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Build metadata was not found: {metadata_path}. Run a launcher build first."
        )
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def _get_build_content_root(build_root: Path, version: str, platform_name: str) -> Path:
    if platform_name == "darwin":
        return build_root / f"AYON {version}.app" / "Contents" / "MacOS"
    return build_root / "output"


def _clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_build_payload(source_root: Path, destination_root: Path) -> None:
    shutil.copytree(source_root, destination_root, dirs_exist_ok=True)


def _create_conda_layout(
    build_root: Path,
    packages_root: Path,
    source_root: Path,
    version: str,
    platform_name: str,
) -> Path:
    conda_root = packages_root / "conda"
    payload_root = conda_root / "payload" / "ayon-launcher"
    recipe_root = conda_root / "recipe"

    _clean_dir(conda_root)
    payload_root.parent.mkdir(parents=True, exist_ok=True)
    recipe_root.mkdir(parents=True, exist_ok=True)
    _copy_build_payload(source_root, payload_root)

    meta_yaml = f"""package:
  name: ayon-launcher-bundle
  version: \"{version}\"

source:
  path: ../payload

build:
  number: 0

about:
  home: https://github.com/ynput/ayon-launcher
  license: MIT
  summary: AYON launcher prebuilt binary bundle ({platform_name})
"""
    (recipe_root / "meta.yaml").write_text(meta_yaml, encoding="utf-8")

    build_sh = """#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$PREFIX/opt/ayon-launcher"
cp -a "$SRC_DIR/ayon-launcher/." "$PREFIX/opt/ayon-launcher/"
mkdir -p "$PREFIX/bin"
cat <<'EOF' > "$PREFIX/bin/ayon-launcher"
#!/usr/bin/env bash
exec \"$CONDA_PREFIX/opt/ayon-launcher/ayon\" \"$@\"
EOF
chmod +x "$PREFIX/bin/ayon-launcher"
"""
    (recipe_root / "build.sh").write_text(build_sh, encoding="utf-8")

    bld_bat = """@echo off
if not exist "%PREFIX%\\Library\\ayon-launcher" mkdir "%PREFIX%\\Library\\ayon-launcher"
xcopy "%SRC_DIR%\\ayon-launcher\\*" "%PREFIX%\\Library\\ayon-launcher\\" /E /I /Y >nul
>"%PREFIX%\\Scripts\\ayon-launcher.bat" echo @echo off
>>"%PREFIX%\\Scripts\\ayon-launcher.bat" echo "%CONDA_PREFIX%\\Library\\ayon-launcher\\ayon.exe" %%*
"""
    (recipe_root / "bld.bat").write_text(bld_bat, encoding="utf-8")

    readme = (
        "This folder contains a conda-build recipe generated from an existing AYON build.\n"
        "Run `conda-build recipe` from this directory to produce the final conda artifact.\n"
    )
    (conda_root / "README.txt").write_text(readme, encoding="utf-8")

    return conda_root


def _rez_platform_token(platform_name: str) -> str:
    mapping = {
        "windows": "platform-windows",
        "linux": "platform-linux",
        "darwin": "platform-osx",
    }
    return mapping.get(platform_name, f"platform-{platform_name}")


def _create_rez_layout(
    packages_root: Path,
    source_root: Path,
    version: str,
    platform_name: str,
) -> Path:
    rez_root = packages_root / "rez" / "ayon_launcher" / version
    payload_root = rez_root / "launcher"

    _clean_dir(rez_root)
    _copy_build_payload(source_root, payload_root)

    platform_token = _rez_platform_token(platform_name)
    package_py = f"""name = \"ayon_launcher\"
version = \"{version}\"

variants = [[\"{platform_token}\"]]

def commands():
    env.AYON_LAUNCHER_ROOT = \"{{root}}/launcher\"
    env.PATH.prepend(\"{{root}}/launcher\")
"""
    (rez_root / "package.py").write_text(package_py, encoding="utf-8")

    return rez_root


def create_packages(build_root: Path, formats: list[str]) -> dict[str, str]:
    metadata = _read_metadata(build_root)
    version = metadata["version"]
    platform_name = metadata["platform"]
    build_content_root = _get_build_content_root(build_root, version, platform_name)
    if not build_content_root.exists():
        raise FileNotFoundError(
            f"Build output was not found: {build_content_root}. Run a launcher build first."
        )

    packages_root = build_root / "packages"
    packages_root.mkdir(parents=True, exist_ok=True)

    created: dict[str, str] = {}
    if "conda" in formats:
        created["conda"] = str(
            _create_conda_layout(
                build_root, packages_root, build_content_root, version, platform_name
            )
        )
    if "rez" in formats:
        created["rez"] = str(
            _create_rez_layout(packages_root, build_content_root, version, platform_name)
        )

    manifest_path = packages_root / "packages_manifest.json"
    manifest_path.write_text(json.dumps(created, indent=2), encoding="utf-8")
    return created


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create conda and/or rez package layouts from build artifacts."
    )
    parser.add_argument(
        "--build-root",
        default=str(Path(__file__).resolve().parents[1] / "build"),
        help="Path to build directory containing metadata.json and output.",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        choices=["conda", "rez"],
        default=["conda", "rez"],
        help="Package layouts to generate.",
    )
    args = parser.parse_args()

    created = create_packages(Path(args.build_root), args.formats)
    for package_format, location in created.items():
        print(f"Created {package_format} package layout at: {location}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
