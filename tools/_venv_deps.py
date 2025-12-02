"""This is a way how to receive requirements like data from poetry lock.

This is needed only for ayon dependencies tool. At this moment this is
combined with requirements.txt stored during build process, but we may want
to use only data from lock file and pass more explicit data from lock file
to installer metadata. So we could replace 'git+https://...' with 'git+<hash>'
with dictionary ready for pyproject.toml file.
"""

import os
import json
import toml
from pathlib import Path

CURRENT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT_DIR = CURRENT_DIR.parent
OUTPUT_PATH = REPO_ROOT_DIR / "build" / "poetry_lock.json"


def main():
    uv_lock_file = REPO_ROOT_DIR / "uv.lock"
    if uv_lock_file.exists():
        with open(uv_lock_file, "r") as stream:
            uv_lock_data = toml.load(stream)

    packages = {}
    package_data = uv_lock_data["package"]
    for package in package_data:
        package_name = package["name"]
        package_version = package["version"]
        source = package.get("source")
        if source:
            if source.get("git"):
                url = source["git"]
                package_version = f"git+{url}"
            else:
                # raise ValueError(f"Unknown source type {source}")
                ...

        packages[package_name] = package_version

    with open(OUTPUT_PATH, "w") as stream:
        json.dump(packages, stream, indent=4)


if __name__ == "__main__":
    main()
