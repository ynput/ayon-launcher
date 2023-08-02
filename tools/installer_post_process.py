import os
import json
import platform
import zipfile
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional, Union

import ayon_api
import click

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_installer_dir():
    return Path(CURRENT_DIR).parent / "build"/ "installer"


class ZipFileLongPaths(zipfile.ZipFile):
    """Allows longer paths in zip files.

    Regular DOS paths are limited to MAX_PATH (260) characters, including
    the string's terminating NUL character.
    That limit can be exceeded by using an extended-length path that
    starts with the '\\?\' prefix.
    """
    _is_windows = platform.system().lower() == "windows"

    def _extract_member(self, member, tpath, pwd):
        if self._is_windows:
            tpath = os.path.abspath(tpath)
            if tpath.startswith("\\\\"):
                tpath = "\\\\?\\UNC\\" + tpath[2:]
            else:
                tpath = "\\\\?\\" + tpath

        return super(ZipFileLongPaths, self)._extract_member(
            member, tpath, pwd
        )


@dataclass
class InstallerInfo:
    version: str
    platform: str
    filename: str
    installer_path: str
    python_version: str
    checksum: str
    checksum_algorithm: str
    size: int
    python_modules: dict[str, str]
    runtime_python_modules: dict[str, str]


def find_installer_info(installer_dir: Optional[str]) -> InstallerInfo:
    if installer_dir is None:
        installer_dir = get_installer_dir()
    installer_dir: Path = Path(installer_dir)

    if not installer_dir.exists():
        raise click.BadParameter("Installers folder doesn't exist")

    json_files = []
    for item in installer_dir.iterdir():
        if item.name.endswith(".json"):
            json_files.append(item)

    if not json_files:
        raise click.BadParameter(f"No metadata files found in {installer_dir}")

    if len(json_files) > 1:
        raise click.BadParameter(
            f"Found more than one metadata in {installer_dir}"
        )
    metadata_path = json_files[0]

    if not metadata_path.exists():
        raise click.BadParameter(
            "Metadata file doesn't exist."
            " Run 'build' and 'make-installer' first."
        )

    with open(str(metadata_path), "r") as stream:
        metadata = json.load(stream)

    filename = metadata.get("filename")
    if not filename:
        raise click.BadParameter(
            "Metadata file does not contain information about installer name."
        )

    installer_path = installer_dir / filename
    if not installer_path.exists():
        raise click.BadParameter(
            "Installer is not available. Run 'make-installer' first."
        )

    return InstallerInfo(installer_path=str(installer_path), **metadata)


def create_connection(
    server: str, api_key: str, username: str, password: str
) -> ayon_api.ServerAPI:
    api = ayon_api.ServerAPI(server)
    if not api.is_server_available:
        raise click.BadParameter("Server is not available")

    if not api_key and not (username and password):
        raise click.BadParameter(
            "You must provide API key, or username and password",
            param_hint="api-key, username & password"
        )

    if api_key:
        api.set_token(api_key)
        if api.has_valid_token:
            return api

        if not username or not password:
            raise click.BadParameter(
                "API key is not valid."
                " Provide valid API key, or username and password.",
                param_hint="api-key"
            )

    api.login(username, password)
    if api.has_valid_token:
        return api
    raise click.BadParameter(
        "Invalid credentials."
        " Provide valid API key, or username and password.",
        param_hint="username & password"
    )


def _find_matching_installer(
    api: ayon_api.ServerAPI, installer_info: InstallerInfo
) -> Union[InstallerInfo, None]:
    server_installers: list[dict[str, Any]] = (
        api.get_installers()["installers"])

    for server_installer in server_installers:
        platform_name: Union[str, None] = server_installer.get("platform")
        version: Union[str, None] = server_installer.get("version")
        if (
            platform_name == installer_info.platform
            and version == installer_info.version
        ):
            return InstallerInfo(
                version=server_installer.get("version"),
                platform=server_installer.get("platform"),
                filename=server_installer.get("filename"),
                installer_path=installer_info.installer_path,
                python_version=server_installer.get("pythonVersion"),
                checksum=server_installer.get("checksum"),
                checksum_algorithm=server_installer.get("checksumAlgorithm"),
                size=server_installer.get("size"),
                python_modules=server_installer.get("pythonModules"),
                runtime_python_modules=(
                    server_installer.get("runtimePythonModules")),
            )
    return None


def create_installer(
    api: ayon_api.ServerAPI, installer_info: InstallerInfo, force:bool
) -> bool:
    matched_installer = _find_matching_installer(api, installer_info)
    if matched_installer is not None:
        if matched_installer == installer_info:
            return False
        if not force:
            raise RuntimeError(
                "Installer already exists on server"
                " but with different values."
                " Use --force to overwrite it."
            )
        print(
            "Removing existing installer on server"
            " because have different metadata"
        )
        api.delete_installer(matched_installer.filename)

    print(
        f"Creating installer {installer_info.version}"
        f" on server {installer_info.filename}"
    )
    api.create_installer(
        installer_info.filename,
        installer_info.version,
        installer_info.python_version,
        installer_info.platform,
        installer_info.python_modules.copy(),
        installer_info.runtime_python_modules.copy(),
        installer_info.checksum,
        installer_info.checksum_algorithm,
        installer_info.size,
    )
    return True


def upload_installer(api: ayon_api.ServerAPI, installer_info: InstallerInfo):
    # TODO print progress over time
    print(f"Upload started ({installer_info.installer_path})")
    api.upload_installer(
        installer_info.installer_path,
        installer_info.filename,
        progress=None
    )
    print("Upload finished")


@click.group()
def cli():
    pass


@cli.command(help="Upload installer to AYON server")
@click.option(
    "--server",
    help="AYON server url",
    required=True)
@click.option(
    "--api-key",
    help="Api key (Only if username and password are not provided)")
@click.option(
    "--username",
    help="Username (Only if api key is not provided)")
@click.option(
    "--password",
    help="Password (Only if api key is not provided)")
@click.option(
    "--installer-dir",
    default=None,
    help="Directory where installer with metadata is located")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force installer creation even if it already exists")
def upload(server, api_key, username, password, installer_dir, force):
    """Upload installer to a server."""

    installer_info: InstallerInfo = find_installer_info(installer_dir)
    api = create_connection(server, api_key, username, password)
    create_installer(api, installer_info, force)
    upload_installer(api, installer_info)


@cli.command(help="Upload installer to AYON server")
@click.option(
    "--server",
    help="AYON server url",
    required=True)
@click.option(
    "--api-key",
    help="Api key (Only if username and password are not provided)")
@click.option(
    "--username",
    help="Username (Only if api key is not provided)")
@click.option(
    "--password",
    help="Password (Only if api key is not provided)")
@click.option(
    "--installer-dir",
    default=None,
    help="Directory where installer with metadata is located")
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Force installer creation even if it already exists")
def create_server_installer(
    server, api_key, username, password, installer_dir, force
):
    installer_info = find_installer_info(installer_dir)
    api = create_connection(server, api_key, username, password)
    create_installer(api, installer_info, force)


def main():
    cli(obj={}, prog_name="AYON-uploader")


if __name__ == "__main__":
    main()
