import sys
import traceback
from dataclasses import dataclass, field
from enum import Enum

from typing import Any, Literal, Union, Optional

PlatformName = Literal["windows", "linux", "darwin"]


class UrlType(Enum):
    HTTP = "http"
    GIT = "git"
    FILESYSTEM = "filesystem"
    SERVER = "server"


@dataclass
class MultiPlatformValue:
    windows: Union[str, None]
    linux: Union[str, None]
    darwin: Union[str, None]


# TODO use single class for all types of sources
@dataclass
class SourceInfo:
    type: UrlType


@dataclass
class LocalSourceInfo(SourceInfo):
    path: MultiPlatformValue = field(default_factory=MultiPlatformValue)


@dataclass
class WebSourceInfo(SourceInfo):
    url: str
    headers: Union[dict[str, str], None]
    filename: Union[str, None]


@dataclass
class ServerSourceInfo(SourceInfo):
    filename: Union[str, None]
    path: Union[str, None]


def convert_source(source: dict[str, Any]) -> Optional[SourceInfo]:
    """Create source object from data information.

    Args:
        source (Dict[str, any]): Information about source.

    Returns:
        Optional[SourceInfo]: Object with source information if type is
            known.

    """
    source_type = source.get("type")
    if not source_type:
        return None

    if source_type == UrlType.FILESYSTEM.value:
        return LocalSourceInfo(
            type=source_type,
            path=MultiPlatformValue(**source["path"])
        )

    if source_type == UrlType.HTTP.value:
        return WebSourceInfo(
            type=source_type,
            url=source["url"],
            headers=source.get("headers"),
            filename=source.get("filename")
        )

    if source_type == UrlType.SERVER.value:
        return ServerSourceInfo(
            type=source_type,
            filename=source.get("filename"),
            path=source.get("path")
        )


def prepare_sources(
    src_sources: list[dict[str, Any]], title: str
) -> tuple[list[SourceInfo], list[dict[str, Any]]]:
    sources = []
    unknown_sources = []
    for source in (src_sources or []):
        try:
            dependency_source = convert_source(source)
        except Exception:
            tb = "".join(traceback.format_exception(*sys.exc_info()))
            print(f"Failed to convert source: {source}\n{tb}")
            unknown_sources.append(source)
            continue

        if dependency_source is not None:
            sources.append(dependency_source)
        else:
            print(f"Unknown source '{source.get('type')}' in {title}")
            unknown_sources.append(source)
    return sources, unknown_sources


@dataclass
class AddonVersionInfo:
    version: str
    full_name: str
    title: str = None
    require_distribution: bool = False
    sources: list[SourceInfo] = field(default_factory=list)
    unknown_sources: list[dict[str, Any]] = field(default_factory=list)
    checksum: Union[str, None] = None
    checksum_algorithm: Union[str, None] = None

    @classmethod
    def from_dict(
        cls,
        addon_name: str,
        addon_title: str,
        addon_version: str,
        version_data: dict[str, Any],
    ) -> "AddonVersionInfo":
        """Addon version info.

        Args:
            addon_name (str): Name of addon.
            addon_title (str): Title of addon.
            addon_version (str): Version of addon.
            version_data (dict[str, Any]): Addon version information from
                server.

        Returns:
            AddonVersionInfo: Addon version info.

        """
        full_name = f"{addon_name}_{addon_version}"
        title = f"{addon_title} {addon_version}"

        source_info = version_data.get("clientSourceInfo")
        require_distribution = source_info is not None
        sources, unknown_sources = prepare_sources(
            source_info, f"Addon: '{title}'")
        checksum = version_data.get("checksum")
        if checksum is None:
            checksum = version_data.get("hash")

        return cls(
            version=addon_version,
            full_name=full_name,
            require_distribution=require_distribution,
            sources=sources,
            unknown_sources=unknown_sources,
            checksum=checksum,
            checksum_algorithm=version_data.get("checksumAlgorithm", "sha256"),
            title=title,
        )


@dataclass
class AddonInfo:
    """Object matching json payload from Server"""
    name: str
    title: str
    versions: dict[str, AddonVersionInfo]
    description: Union[str, None] = None
    license: Union[str, None] = None
    authors: Union[str, None] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AddonInfo":
        """Addon info by available versions.

        Args:
            data (dict[str, Any]): Addon information from server. Should
                contain information about every version under 'versions'.

        Returns:
            AddonInfo: Addon info with available versions.

        """
        # server payload contains info about all versions
        addon_name = data["name"]
        title = data.get("title") or addon_name

        src_versions = data.get("versions") or {}
        dst_versions = {
            addon_version: AddonVersionInfo.from_dict(
                addon_name, title, addon_version, version_data
            )
            for addon_version, version_data in src_versions.items()
        }
        return cls(
            name=addon_name,
            title=title,
            versions=dst_versions,
            description=data.get("description"),
            license=data.get("license"),
            authors=data.get("authors")
        )


@dataclass
class DependencyItem:
    """Object matching payload from Server about single dependency package"""
    filename: str
    platform_name: str
    checksum: str
    checksum_algorithm: str
    sources: list[SourceInfo]
    unknown_sources: list[dict[str, Any]]
    source_addons: dict[str, str]
    python_modules: dict[str, str]

    @classmethod
    def from_dict(cls, package: dict[str, Any]) -> "DependencyItem":
        filename = package["filename"]
        src_sources = package.get("sources") or []
        for source in src_sources:
            if source.get("type") == "server" and not source.get("filename"):
                source["filename"] = filename

        sources, unknown_sources = prepare_sources(
            src_sources, f"Dependency package '{filename}'")

        return cls(
            filename=filename,
            platform_name=package["platform"],
            sources=sources,
            unknown_sources=unknown_sources,
            checksum=package["checksum"],
            # Backwards compatibility
            checksum_algorithm=package.get("checksumAlgorithm", "sha256"),
            source_addons=package["sourceAddons"],
            python_modules=package["pythonModules"]
        )


@dataclass
class Installer:
    version: str
    filename: str
    platform_name: PlatformName
    size: int
    checksum: str
    checksum_algorithm: str
    python_version: str
    python_modules: dict[str, str]
    runtime_python_modules: dict[str, str]
    sources: list[SourceInfo]
    unknown_sources: list[dict[str, Any]]

    @classmethod
    def from_dict(cls, installer_info: dict[str, Any]) -> "Installer":
        src_sources = installer_info.get("sources") or []
        for source in src_sources:
            if source.get("type") == "server" and not source.get("filename"):
                source["filename"] = installer_info["filename"]

        filename = installer_info["filename"]
        sources, unknown_sources = prepare_sources(
            src_sources, f"Installer '{filename}'"
        )

        runtime_python_modules = installer_info.get(
            "runtimePythonModules", {}
        )
        return cls(
            version=installer_info["version"],
            filename=installer_info["filename"],
            platform_name=installer_info["platform"],
            size=installer_info["size"],
            checksum=installer_info["checksum"],
            checksum_algorithm=installer_info.get("checksumAlgorithm", "md5"),
            python_version=installer_info["pythonVersion"],
            python_modules=installer_info["pythonModules"],
            runtime_python_modules=runtime_python_modules,
            sources=sources,
            unknown_sources=unknown_sources,
        )


@dataclass
class AddonDevInfo:
    enabled: bool
    path: Union[str, None]
    path_liunx: Union[str, None] = None
    path_darwin: Union[str, None] = None


@dataclass
class Bundle:
    """Class representing bundle information."""

    name: str
    installer_version: Union[str, None]
    addon_versions: dict[str, str]
    dependency_packages: dict[PlatformName, Union[str, None]]
    is_production: bool
    is_staging: bool
    is_dev: bool
    active_dev_user: Union[str, None]
    addons_dev_info: dict[str, AddonDevInfo]
    is_project_bundle: Union[bool, None] = None

    @classmethod
    def from_dict(cls, data):
        addons_dev_info = {
            addon_name: AddonDevInfo(
                info["enabled"],
                info["path"],
                info["path_linux"],
                info["path_darwin"],
            )
            for addon_name, info in data.get("addonDevelopment", {}).items()
        }
        return cls(
            name=data["name"],
            installer_version=data.get("installerVersion"),
            addon_versions=data.get("addons", {}),
            dependency_packages=data.get("dependencyPackages", {}),
            is_production=data["isProduction"],
            is_staging=data["isStaging"],
            is_dev=data.get("isDev", False),
            is_project_bundle=data.get("isProject"),
            active_dev_user=data.get("activeUser"),
            addons_dev_info=addons_dev_info,
        )
