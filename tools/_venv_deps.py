"""This is a way how to receive requirements like data from poetry lock.

This is needed only for ayon dependencies tool. At this moment this is
combined with requirements.txt stored during build process, but we may want
to use only data from lock file and pass more explicit data from lock file
to installer metadata. So we could replace 'git+https://...' with 'git+<hash>'
with dictionary ready for pyproject.toml file.
"""

import os
import platform
import site
import json
if platform.python_version_tuple() >= ("3", "11"):
    import tomli as tomllib
else:
    import tomli as tomllib  # For Python 3.10
from pathlib import Path

CURRENT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT_DIR = CURRENT_DIR.parent
OUTPUT_PATH = REPO_ROOT_DIR / "build" / "poetry_lock.json"

def get_poetry_venv_root():
    venv_root = REPO_ROOT_DIR / ".poetry" / "venv"
    if platform.system().lower() == "windows":
        return venv_root / "Lib" / "site-packages"

    lib_root = venv_root / "lib"
    for subfolder in lib_root.iterdir():
        site_packages = subfolder / "site-packages"
        if site_packages.exists():
            return site_packages
    raise RuntimeError("Could not find site-packages in poetry venv")


site.addsitedir(str(get_poetry_venv_root()))

# from poetry.factory import Factory  # noqa E402


def main():
    uv_lock_file = REPO_ROOT_DIR / "uv.lock"
    if uv_lock_file.exists():
        with open(uv_lock_file, "rb") as stream:
            uv_lock_data = tomllib.load(stream)

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
