"""This script helps to manage the version of the project via CI action."""
import re
import sys
import argparse
from pathlib import Path

SEMVER_REGEX = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def get_current_version(version_file: Path) -> str:
    content = version_file.read_text(encoding="utf-8")
    vars = {}
    exec(content, vars)
    return vars["__version__"]


def update_version_in_src(
    version_file: Path,
    pyproject_file: Path,
    new_version: str,
):
    content = version_file.read_text(encoding="utf-8")
    new_content = re.sub(
        r'(__version__\s*=\s*").*(")',
        rf'\g<1>{new_version}\g<2>',
        content
    )
    version_file.write_text(new_content, encoding="utf-8")

    # Update pyproject.toml
    version_found = False
    content = pyproject_file.read_text(encoding="utf-8")
    new_lines = []
    for line in content.splitlines():
        if not version_found and line.startswith("version"):
            version_found = True
            line = f"version = \"{new_version}\""
        new_lines.append(line)

    pyproject_file.write_text("\n".join(new_lines), encoding="utf-8")


def bump_to_dev_version(version: str) -> str:
    version_parts = SEMVER_REGEX.match(version).groups()
    major, minor, patch = version_parts[0:3]
    patch = str(int(patch) + 1)
    return f"{major}.{minor}.{patch}-dev"


def bump_to_release_version(version: str, bump_minor: bool = False) -> str:
    version_parts = SEMVER_REGEX.match(version).groups()
    major, minor, patch = version_parts[0:3]
    if bump_minor:
        minor = str(int(minor) + 1)
        patch = "0"
    return f"{major}.{minor}.{patch}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["get-release-version", "update", "get-dev-version"]
    )
    parser.add_argument(
        "--version",
        help="Version to set for update command",
    )
    parser.add_argument(
        "--bump-minor",
        action="store_true",
        help="Bump minor version for get-release-version command",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    version_file = repo_root / "version.py"
    pyproject_file = repo_root / "pyproject.toml"

    current_version = get_current_version(version_file)

    if args.command == "get-release-version":
        if current_version:
            print(bump_to_release_version(current_version, args.bump_minor))
        else:
            sys.exit(1)
    elif args.command == "get-dev-version":
        if current_version:
            print(bump_to_dev_version(current_version))
        else:
            sys.exit(1)
    elif args.command == "update":
        if not args.version:
            print("Error: --version is required for update command")
            sys.exit(1)
        update_version_in_src(version_file, pyproject_file, args.version)
        print(f"Updated version to {args.version}")


if __name__ == "__main__":
    main()
