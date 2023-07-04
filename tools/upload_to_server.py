import os
import sys
import json
from dataclasses import dataclass
from typing import Any, Optional, Union

import ayon_api
import click


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


def find_installer_info(
    metadata_path: Optional[str] = None
) -> InstallerInfo:
    if metadata_path is None:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        build_root = os.path.join(os.path.dirname(current_dir), "build")
        if not os.path.exists(build_root):
            raise click.BadParameter("Build folder doesn't exist")

        metadata_path = os.path.join(build_root, "metadata.json")

    if not os.path.exists(metadata_path):
        raise click.BadParameter(
            "Metadata file doesn't exist."
            " Run 'build' and 'make-installer' first."
        )

    with open(metadata_path, "r") as stream:
        metadata = json.load(stream)

    installer_path = metadata.get("installer_path")
    if not installer_path or not os.path.exists(installer_path):
        raise click.BadParameter(
            "Installer is not available. Run 'make-installer' first."
        )
    metadata["filename"] = os.path.basename(installer_path)
    return InstallerInfo(**metadata)


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


def create_installer(api: ayon_api.ServerAPI, installer_info: InstallerInfo):
    server_installers: list[dict[str, Any]] = (
        api.get_installers()["installers"])

    for server_installer in server_installers:
        platform_name: Union[str, None] = server_installer.get("platform")
        version: Union[str, None] = server_installer.get("version")
        if (
            platform_name == installer_info.platform
            and version == installer_info.version
        ):
            print(f"Version {version} already exists on server")
            return False

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


def upload_installer(api: ayon_api.ServerAPI, installer_info: InstallerInfo):
    # TODO print progress over time
    print("Upload started")
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
    "--metadata",
    default=None,
    help="Path to metadata.json file")
def upload(server, api_key, username, password, metadata):
    installer_info: InstallerInfo = find_installer_info(metadata)
    api = create_connection(server, api_key, username, password)
    create_installer(api, installer_info)
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
    "--metadata",
    default=None,
    help="Path to metadata.json file")
def create_server_installer(server, api_key, username, password, metadata):
    installer_info = find_installer_info(metadata)
    api = create_connection(server, api_key, username, password)
    create_installer(api, installer_info)


def main():
    cli(obj={}, prog_name="AYON-uploader")


if __name__ == "__main__":
    main()
