import os
import sys
import json
import time
import uuid
import ctypes
import tempfile
import traceback
import collections
import datetime
import logging
import shutil
import platform
import subprocess
import dataclasses
from enum import Enum
from abc import ABC, abstractmethod
from typing import Optional, Any, Generator
from urllib.parse import urlencode

import ayon_api

from ayon_common.utils import (
    HEADLESS_MODE_ENABLED,
    extract_archive_file,
    is_staging_enabled,
    is_dev_mode_enabled,
    get_executables_info_by_version,
    get_downloads_dir,
    calculate_file_checksum,
)

from .exceptions import BundleNotFoundError, InstallerDistributionError
from .data_structures import (
    SourceInfo,
    Installer,
    AddonInfo,
    DependencyItem,
    Bundle,
)
from .utils import (
    get_addons_dir,
    get_dependencies_dir,
)
from .downloaders import (
    SourceDownloader,
    get_default_download_factory,
    DownloadFactory,
)


def _unknown_bool(self):
    return False


NOT_SET = type("UNKNOWN", (), {"__bool__": _unknown_bool})()
DIST_PROGRESS_FILENAME = "dist_progress.json"
MOVE_WAIT_TRESHOLD_TIME = 20
IS_WINDOWS = platform.system().lower() == "windows"


class DistributionProgressInterupted(Exception):
    pass


def _windows_dir_requires_permissions(dirpath: str) -> bool:
    try:
        # Attempt to create a temporary file in the folder
        temp_file_path = os.path.join(dirpath, uuid.uuid4().hex)
        with open(temp_file_path, "w"):
            pass
        os.remove(temp_file_path)  # Clean up temporary file
        return False

    except PermissionError:
        return True

    except BaseException as exc:
        print(
            "Failed to determine if root requires permissions."
            f"Unexpected error: {exc}"
        )
        return False


def _has_write_permissions(dirpath: str) -> bool:
    while not os.path.exists(dirpath):
        _dirpath = os.path.dirname(dirpath)
        if _dirpath == dirpath:
            print((
                "Failed to determine if root requires permissions."
                " The disk is probably not mounted."
            ))
            return False
        dirpath = _dirpath

    if IS_WINDOWS:
        if ctypes.windll.shell32.IsUserAnAdmin():
            return True

        return not _windows_dir_requires_permissions(dirpath)

    return os.access(dirpath, os.W_OK)


class UpdateState(Enum):
    UNKNOWN = "unknown"
    UPDATED = "udated"
    OUTDATED = "outdated"
    UPDATE_FAILED = "failed"
    MISS_SOURCE_FILES = "miss_source_files"


# --- Distribution metadata file ---
# The file is stored to destination directory to keep track of distribution
#   of the item.
class DistFileStates(Enum):
    moving = "moving"
    done = "done"
    failed = "failed"


def _read_progress_file(progress_dir: str):
    progress_path = os.path.join(progress_dir, DIST_PROGRESS_FILENAME)
    try:
        with open(progress_path, "r") as stream:
            return json.loads(stream.read())
    except Exception:
        return {}


def _store_progress_file(progress_dir: str, progress_info: dict[str, Any]):
    progress_path = os.path.join(progress_dir, DIST_PROGRESS_FILENAME)
    if not os.path.exists(progress_dir):
        os.makedirs(progress_dir, exist_ok=True)
    with open(progress_path, "w") as stream:
        json.dump(progress_info, stream)


def _create_progress_file(
    progress_dir: str,
    progress_id: str,
    checksum: Optional[str],
    checksum_algorithm: Optional[str],
    state: Optional[DistFileStates] = None
):
    if state is None:
        state = DistFileStates.moving

    progress_info = {
        # State of the progress
        "state": state.value,
        # Unique identifier of the progress
        "progress_id": progress_id,
        # Just a metadata about the file
        "checksum": checksum,
        "checksum_algorithm": checksum_algorithm,
        "dist_started": (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ),
    }
    _store_progress_file(progress_dir, progress_info)


def _clean_dist_dir(dist_dirpath: str):
    if not os.path.exists(dist_dirpath):
        return
    for subname in os.listdir(dist_dirpath):
        if subname == DIST_PROGRESS_FILENAME:
            continue
        path = os.path.join(dist_dirpath, subname)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)


def _wait_for_other_process(
    progress_dir: str,
    progress_id: str,
    log: logging.Logger,
) -> Generator[Optional[bool], None, None]:
    progress_path = os.path.join(progress_dir, DIST_PROGRESS_FILENAME)
    started = time.time()
    progress_existed = False
    threshold_time = None
    state = None
    output = False
    while True:
        if not os.path.exists(progress_path):
            if progress_existed:
                log.debug(
                    "Other processed didn't finish download or extraction,"
                    " trying to do so."
                )
            break

        progress_info = _read_progress_file(progress_dir)
        if progress_info.get("progress_id") == progress_id:
            break

        current_state = progress_info.get("state")

        if not progress_existed:
            log.debug(
                "Other process already created progress file"
                " in target directory. Waiting for finishing it."
            )

        progress_existed = True
        if current_state is None:
            log.warning(
                "Other process did not store 'state' to progress file."
            )
            break

        if current_state == DistFileStates.done.value:
            log.debug("Other process finished distribution.")
            output = True
            break

        if current_state == DistFileStates.failed.value:
            log.debug("Other process failed distribution.")
            state = current_state
            threshold_time = 0

        if current_state != state:
            started = time.time()
            threshold_time = None
            state = current_state

        if threshold_time is None:
            threshold_time = MOVE_WAIT_TRESHOLD_TIME

        if (time.time() - started) > threshold_time:
            log.debug(
                f"Waited for treshold time ({threshold_time}s)."
                f" Extracting downloaded content."
            )
            _clean_dist_dir(progress_dir)
            break
        yield None
    yield output


def change_permissions_recursive(path: str, mode: int = 0o777):
    if IS_WINDOWS or not os.path.exists(path):
        return

    if os.path.isfile(path):
        # If the path is a file, change its permissions directly
        os.chmod(path, mode)
        return

    # Traverse the directory tree starting from 'path' to top
    for root, dirnames, filenames in os.walk(path, topdown=False):
        # Change the permissions of each directory
        for dirname in dirnames:
            dirpath = os.path.join(root, dirname)
            os.chmod(dirpath, mode)

        for filename in filenames:
            filepath = os.path.join(root, filename)
            os.chmod(filepath, mode)


# --- Distribution download directories ---
# Where to store downloaded files before extration.
def _get_dist_download_dir(*args):
    return os.path.join(
        tempfile.gettempdir(), "ayon_dist_downloads", *args
    )


def _create_dist_expire_file(process_dir: str):
    """Create distribution temp directory with metadata file.

    The metadata file contains information about expiration time of the
        temp folder. Lifetime is 1 hour (more than should be needed).

    Args:
        process_dir (str): Path to distribution temp directory.

    """
    info_path = os.path.join(process_dir, "download_info.json")
    if os.path.exists(info_path):
        return

    if not os.path.exists(process_dir):
        os.makedirs(process_dir, exist_ok=True)

    with open(info_path, "w") as stream:
        json.dump(
            {"expiration_time": time.time() + (60 * 60)},
            stream,
        )

    change_permissions_recursive(process_dir)


def _dist_expire_file_expired(process_dir: str) -> bool:
    """Check if distribution temp directory is expired.

    Args:
        process_dir (str): Path to distribution temp directory.

    Returns:
        bool: Directory is expired and can be removed.

    """
    info_path = os.path.join(process_dir, "download_info.json")
    if not os.path.exists(info_path):
        return True

    try:
        with open(info_path, "r") as stream:
            data = json.load(stream)
    except Exception:
        data = {}
    expiration_time = data.get("expiration_time")
    if not isinstance(expiration_time, int):
        return False
    return expiration_time < time.time()


def _cleanup_dist_expire_dirs(process_dir: str):
    if not os.path.exists(process_dir):
        return
    for subname in os.listdir(process_dir):
        path = os.path.join(process_dir, subname)
        if os.path.isdir(path) and _dist_expire_file_expired(path):
            try:
                shutil.rmtree(path)
            except Exception:
                print(
                    f"Failed to remove expired distribution directory: {path}"
                )


def _cleanup_dist_download_dirs():
    """Clean up old distribution download directories.

    If distribution crashed in past this function makes sure they are removed.

    """
    _cleanup_dist_expire_dirs(_get_dist_download_dir())


class DistributeTransferProgress:
    """Progress of single source item in 'DistributionItem'.

    The item is to keep track of single source item.
    """

    def __init__(self):
        self._transfer_progress = ayon_api.TransferProgress()
        self._started = False
        self._failed = False
        self._fail_reason = None
        self._unzip_started = False
        self._unzip_finished = False
        self._hash_check_started = False
        self._hash_check_finished = False

    def set_started(self):
        """Call when source distribution starts."""

        self._started = True

    def set_failed(self, reason: str):
        """Set source distribution as failed.

        Args:
            reason (str): Error message why the transfer failed.

        """
        self._failed = True
        self._fail_reason = reason

    def set_hash_check_started(self):
        """Call just before hash check starts."""

        self._hash_check_started = True

    def set_hash_check_finished(self):
        """Call just after hash check finishes."""

        self._hash_check_finished = True

    def set_unzip_started(self):
        """Call just before unzip starts."""

        self._unzip_started = True

    def set_unzip_finished(self):
        """Call just after unzip finishes."""

        self._unzip_finished = True

    @property
    def is_running(self) -> bool:
        """Source distribution is in progress.

        Returns:
            bool: Transfer is in progress.
        """

        return bool(
            self._started
            and not self._failed
            and not self._hash_check_finished
        )

    @property
    def transfer_progress(self) -> ayon_api.TransferProgress:
        """Source file 'download' progress tracker.

        Returns:
            ayon_api.TransferProgress: Content download progress.

        """
        return self._transfer_progress

    @property
    def started(self) -> bool:
        return self._started

    @property
    def hash_check_started(self) -> bool:
        return self._hash_check_started

    @property
    def hash_check_finished(self) -> bool:
        return self._hash_check_finished

    @property
    def unzip_started(self) -> bool:
        return self._unzip_started

    @property
    def unzip_finished(self) -> bool:
        return self._unzip_finished

    @property
    def failed(self) -> bool:
        return self._failed or self._transfer_progress.failed

    @property
    def fail_reason(self) -> Optional[str]:
        return self._fail_reason or self._transfer_progress.fail_reason


class BaseDistributionItem(ABC):
    """Distribution item with sources and target directories.

    Distribution item can be an installer, addon or dependency package.
    Distribution item can be already distributed and don't need any
    progression. The item keeps track of the progress. The reason is to be
    able to use the distribution items as source data for UI without
    implementing the same logic.

    Distribution is "state" based. Distribution can be 'UPDATED' or 'OUTDATED'
    at the initialization. If item is 'UPDATED' the distribution is skipped
    and 'OUTDATED' will trigger the distribution process.

    Because the distribution may have multiple sources each source has own
    progress item.

    Args:
        download_dirpath (str): Path to directory where file is unzipped.
        state (UpdateState): Initial state (UpdateState.UPDATED or
            UpdateState.OUTDATED).
        checksum (Optional[str]): Hash of file for validation.
        checksum_algorithm (Optional[str]): Algorithm used to generate the hash.
        factory (DownloadFactory): Downloaders factory object.
        sources (List[SourceInfo]): Possible sources to receive the
            distribution item.
        downloader_data (Dict[str, Any]): More information for downloaders.
        item_label (str): Label used in log outputs (and in UI).
        progress_dir (Optional[str]): Directory where progress is stored for
            other processes.
        logger (Optional[logging.Logger]): Logger object.

    """
    def __init__(
        self,
        download_dirpath: str,
        state: UpdateState,
        checksum: Optional[str],
        checksum_algorithm: Optional[str],
        factory: DownloadFactory,
        sources: list[SourceInfo],
        downloader_data: dict[str, Any],
        item_label: str,
        progress_dir: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        if logger is None:
            logger = logging.getLogger(self.__class__.__name__)
        self.log: logging.Logger = logger
        self.state: UpdateState = state
        self.download_dirpath: str = download_dirpath
        self.checksum: Optional[str] = checksum
        self.checksum_algorithm: Optional[str] = checksum_algorithm
        self.factory: DownloadFactory = factory
        self.sources = self._prepare_sources(sources)
        self.downloader_data: dict[str, Any] = downloader_data
        self.item_label: str = item_label

        self._need_distribution = state != UpdateState.UPDATED
        self._current_source_progress = None
        self._used_source_progress = None
        self._used_source = None
        self._dist_started = False

        self._progress_id = uuid.uuid4().hex
        self._progress_dir = progress_dir

        self._error_msg = None
        self._error_detail = None

    @staticmethod
    def _prepare_sources(sources: list[SourceInfo]):
        return [
            (source, DistributeTransferProgress())
            for source in sources
        ]

    @property
    def need_distribution(self) -> bool:
        """Need distribution based on initial state.

        Returns:
            bool: Need distribution.

        """
        return self._need_distribution

    @property
    def current_source_progress(self) -> Optional[DistributeTransferProgress]:
        """Currently processed source progress object.

        Returns:
            Optional[DistributeTransferProgress]: Transfer progress or None.

        """
        return self._current_source_progress

    @property
    def used_source_progress(self) -> Optional[DistributeTransferProgress]:
        """Transfer progress that successfully distributed the item.

        Returns:
            Optional[DistributeTransferProgress]: Transfer progress or None.

        """
        return self._used_source_progress

    @property
    def used_source(self) -> Optional[dict[str, Any]]:
        """Data of source item.

        Returns:
            Optional[dict[str, Any]]: SourceInfo data or None.

        """
        return self._used_source

    @property
    def error_message(self) -> Optional[str]:
        """Reason why distribution item failed.

        Returns:
            Optional[str]: Error message.
        """

        return self._error_msg

    @property
    def error_detail(self) -> Optional[str]:
        """Detailed reason why distribution item failed.

        Returns:
            Optional[str]: Detailed information (maybe traceback).
        """

        return self._error_detail

    @property
    @abstractmethod
    def is_missing_permissions(self) -> bool:
        pass

    def _pre_source_process(self):
        if not os.path.exists(self.download_dirpath):
            os.makedirs(self.download_dirpath, exist_ok=True)

        change_permissions_recursive(self.download_dirpath)

    def _receive_file(
        self,
        source_data: dict[str, Any],
        source_progress: DistributeTransferProgress,
        downloader: SourceDownloader,
    ) -> Optional[str]:
        """Receive source filepath using source data and downloader.

        Args:
            source_data (dict[str, Any]): Source information.
            source_progress (DistributeTransferProgress): Object where to
                track process of a source.
            downloader (SourceDownloader): Downloader object which should care
                about receiving file from source.

        Returns:
            Optional[str]: Filepath to received file from source.

        """
        download_dirpath = self.download_dirpath

        try:
            filepath = downloader.download(
                source_data,
                download_dirpath,
                self.downloader_data,
                source_progress.transfer_progress,
            )
        except Exception:
            message = "Failed to download source"
            source_progress.set_failed(message)
            self.log.warning(
                f"{self.item_label}: {message}",
                exc_info=True
            )
            return None

        source_progress.set_hash_check_started()
        try:
            # WARNING This condition was added because addons don't have
            #   information about checksum at the moment.
            # TODO remove once addon can supply checksum.
            if self.checksum:
                downloader.check_hash(
                    filepath, self.checksum, self.checksum_algorithm
                )
            else:
                # Fill checksum automatically based on downloaded file
                # - still better than nothing
                if not self.checksum_algorithm:
                    self.checksum_algorithm = "sha256"
                self.checksum = calculate_file_checksum(
                    filepath, self.checksum_algorithm
                )

        except Exception:
            message = "File hash does not match"
            source_progress.set_failed(message)
            self.log.warning(
                f"{self.item_label}: {message}",
                exc_info=True
            )
            return None
        source_progress.set_hash_check_finished()
        return filepath

    def _post_source_process(
        self,
        filepath: str,
        source_data: dict[str, Any],
        source_progress: DistributeTransferProgress,
        downloader: SourceDownloader,
    ) -> Generator[Optional[bool], None, None]:
        """Process source after it is downloaded and validated.

        Override this method if downloaded file needs more logic to do, like
            extraction.

        This part will mark source as updated and will trigger cleanup of
        source files via downloader (e.g. to remove downloaded file).

        Args:
            filepath (str): Path to a downloaded source.
            source_data (dict[str, Any]): Source information data.
            source_progress (DistributeTransferProgress): Source progress.
            downloader (SourceDownloader): Object which cared about download
                of file.

        Returns:
            Generator[Optional[bool], None, None]: Post processing finished
                in a way that it is not needed to process other possible
                sources. Does not mean that it was successful. If yields None
                then is still working.

        """
        if filepath:
            self.state = UpdateState.UPDATED
            self._used_source = source_data

        downloader.cleanup(
            source_data,
            self.download_dirpath,
            self.downloader_data
        )
        yield bool(filepath)

    def _process_source(
        self,
        source: SourceInfo,
        source_progress: DistributeTransferProgress,
    ) -> Generator[Optional[bool], None, None]:
        """Process single source item.

        Cares about download, validate and process source.

        Args:
            source (SourceInfo): Source information.
            source_progress (DistributeTransferProgress): Object to keep track
                about process of a source.

        Returns:
            Generator[Optional[bool], None, None]: Source was processed so
                any other sources can be skipped. Does not have to be
                successfull. Is still working if yields None.

        """
        self._current_source_progress = source_progress
        source_progress.set_started()

        self._pre_source_process()
        try:
            downloader = self.factory.get_downloader(source.type)
        except Exception:
            message = f"Unknown downloader {source.type}"
            source_progress.set_failed(message)
            self.log.warning(message, exc_info=True)
            yield False
            return

        try:
            source_data = dataclasses.asdict(source)
            filepath = self._receive_file(
                source_data,
                source_progress,
                downloader
            )

            yield from self._post_source_process(
                filepath, source_data, source_progress, downloader
            )

        except Exception:
            message = "Failed to process source"
            source_progress.set_failed(message)
            self.log.warning(
                f"{self.item_label}: {message}",
                exc_info=True
            )
            yield False

    def _set_progress_state(self, state: DistFileStates):
        if not self._progress_dir:
            return

        progress_info = _read_progress_file(self._progress_dir)
        if progress_info.get("progress_id") != self._progress_id:
            # Ignore if wanted to set 'failed' state
            if state == DistFileStates.failed:
                return
            raise DistributionProgressInterupted(
                "Different process took over progress file."
            )

        progress_info["state"] = state.value
        if state == DistFileStates.done:
            # Update checksum if it was not set from server information
            if not progress_info["checksum"] and self.checksum:
                progress_info["checksum"] = self.checksum
                progress_info["checksum_algorithm"] = self.checksum_algorithm
            progress_info["dist_finished"] = (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

        _store_progress_file(self._progress_dir, progress_info)

    def _distribute(self) -> Generator[bool, None, None]:
        if not self.sources:
            message = (
                f"{self.item_label}: Don't have"
                " any sources to download from."
            )
            self.log.error(message)
            self._error_msg = message
            self.state = UpdateState.MISS_SOURCE_FILES
            yield True
            return

        # Progress file
        # - Check if other process/machine already started the job
        if self._progress_dir:
            result = False
            for result in _wait_for_other_process(
                self._progress_dir,
                self._progress_id,
                self.log
            ):
                if result is not None:
                    # Give other distribution items option to start waiting
                    #   cycle
                    yield False
                    break
                yield False

            if result is True:
                self.state = UpdateState.UPDATED
                self.log.info(f"{self.item_label}: Already distributed")
                yield True
                return

            _create_progress_file(
                self._progress_dir,
                self._progress_id,
                self.checksum,
                self.checksum_algorithm,
            )

        # Download
        for source, source_progress in self.sources:
            yield False
            result = False
            for result in self._process_source(source, source_progress):
                if result is not None:
                    break

            if result:
                break

        last_progress = self._current_source_progress
        self._current_source_progress = None
        if self.state == UpdateState.UPDATED:
            self._set_progress_state(DistFileStates.done)
            self._used_source_progress = last_progress
            self.log.info(f"{self.item_label}: Distributed")
        else:
            self._set_progress_state(DistFileStates.failed)
            self.log.error(f"{self.item_label}: Failed to distribute")
            self._error_msg = "Failed to receive or install source files"
        yield True

    def _post_distribute(self):
        pass

    def is_distributed(self):
        if not self.need_distribution:
            return True
        return self.state == UpdateState.UPDATED

    def distribute(self) -> Generator[bool, None, None]:
        """Execute distribution logic."""
        if self.is_distributed() or self._dist_started:
            yield True
            return

        self._dist_started = True
        try:
            try:
                for result in self._distribute():
                    if result:
                        break
                    yield False

            except DistributionProgressInterupted:
                wait_result = False
                for wait_result in _wait_for_other_process(
                    self._progress_dir, self._progress_id, self.log
                ):
                    if wait_result is not None:
                        break
                    yield False

                if wait_result:
                    self.state = UpdateState.UPDATED
                else:
                    self.state = UpdateState.UPDATE_FAILED
                    self._error_msg = (
                        "Other process took over distribution and failed."
                    )
                    self._error_detail = (
                        "Please try to start AYON again and contact"
                        " administrator if issue persist."
                    )
                    self.log.error(
                        f"{self.item_label}: {self._error_msg}"
                    )

        except Exception as exc:
            self.state = UpdateState.UPDATE_FAILED
            self._error_msg = str(exc)
            self._error_detail = "".join(
                traceback.format_exception(*sys.exc_info())
            )
            self.log.error(
                f"{self.item_label}: Distibution failed",
                exc_info=True
            )

        finally:
            if self.state == UpdateState.OUTDATED:
                self.state = UpdateState.UPDATE_FAILED
                self._error_msg = "Distribution failed"

            self._post_distribute()
            yield True


def create_tmp_file(
    suffix: Optional[str] = None,
    prefix: Optional[str] = None
) -> str:
    with tempfile.NamedTemporaryFile(
        suffix=suffix, prefix=prefix, delete=False
    ) as tmp:
        filepath = tmp.name
    return filepath


class InstallerDistributionItem(BaseDistributionItem):
    """Distribution of new version of AYON launcher/Installer."""

    def __init__(self, cleanup_on_fail: bool, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cleanup_on_fail = cleanup_on_fail
        self._executable = None
        self._installer_path = None
        self._installer_error = None

    @property
    def executable(self) -> Optional[str]:
        """Path to distributed ayon executable.

        Returns:
            Optional[str]: Path to executable path which was distributed.

        """
        return self._executable

    @property
    def installer_path(self) -> Optional[str]:
        """Path to a distribution package/installer.

        This can be used as reference for user where to find downloaded
            installer on disk and distribute it manually.

        Returns:
            Optional[str]: Path to installer.

        """
        return self._installer_path

    @property
    def installer_error(self) -> Optional[str]:
        """Known installer error that happened during distribution.

        Returns:
            Optional[str]: Message that will be shown to user and logged
                out.

        """
        return self._installer_error

    @property
    def is_missing_permissions(self) -> bool:
        return not _has_write_permissions(
            os.path.dirname(os.path.dirname(sys.executable))
        )

    def _find_windows_executable(self, log_output: str):
        """Find executable path in log output.

        Setup exe should print out log output to a file where are described
        steps that happened during installation.

        Todos:
            Find a better way how to find out where AYON launcher was
                installed.

        Args:
            log_output (str): Output from installer log.

        """
        exe_name = "ayon.exe"
        for line in log_output.splitlines():
            idx = line.find(exe_name)
            if idx < 0:
                continue

            line = line[:idx + len(exe_name)]
            parts = line.split("\\")
            if len(parts) < 2:
                parts = line.replace("/", "\\").split("\\")

            last_part = parts.pop(-1)
            found_valid = False
            final_parts = []
            for part in parts:
                if found_valid:
                    final_parts.append(part)
                    continue
                part = part + "\\"
                while part:
                    if os.path.exists(part):
                        break
                    part = part[1:]

                if part:
                    found_valid = True
                    final_parts.append(part[:-1])
            final_parts.append(last_part)
            executable_path = "\\".join(final_parts)
            if os.path.exists(executable_path):
                return executable_path

    def _install_windows(self, filepath: str):
        """Install windows AYON launcher.

        Args:
            filepath (str): Path to setup.exe file.

        """
        install_root = os.path.dirname(os.path.dirname(sys.executable))

        # A file where installer may store log output
        log_file = create_tmp_file(suffix="ayon_install")
        # A file where installer may store output directory
        install_exe_tmp = create_tmp_file(suffix="ayon_install_dir")
        user_arg = "/CURRENTUSER"
        # Ask for admin permissions if user is not admin and
        if not _has_write_permissions(install_root):
            if HEADLESS_MODE_ENABLED:
                raise InstallerDistributionError((
                    "Installation requires administration permissions, which"
                    " cannot be granted in headless mode."
                ))
            user_arg = "/ALLUSERS"
        args = [
            filepath,
            user_arg,
            "/NOCANCEL",
            f"/LOG={log_file}",
            f"/INSTALLROOT={install_root}"
        ]
        if not HEADLESS_MODE_ENABLED:
            args.append("/SILENT")
        else:
            args.append("/VERYSILENT")

        env = dict(os.environ.items())
        env["AYON_INSTALL_EXE_OUTPUT"] = install_exe_tmp

        code = subprocess.call(args, env=env)
        with open(log_file, "r") as stream:
            log_output = stream.read()
        with open(install_exe_tmp, "r") as stream:
            install_exe_path = stream.read()
        os.remove(log_file)
        os.remove(install_exe_tmp)
        if code != 0:
            self.log.error(log_output)
            raise InstallerDistributionError(
                "Install process failed without known reason."
                " Try to install AYON manually."
            )

        executable = install_exe_path.strip() or None
        if not executable or not os.path.exists(executable):
            executable = self._find_windows_executable(log_output)

        self._executable = executable

    def _install_linux(self, filepath: str):
        """Install linux AYON launcher.

        Linux installations are just an archive file, so we attempt to unzip
            the new installation one level up of the one being run.

        Args:
            filepath (str): Path to a .tar.gz file.

        """
        install_root = os.path.dirname(os.path.dirname(sys.executable))

        self.log.info(
            f"Installing AYON launcher {filepath} into:\n{install_root}"
        )

        if not os.path.exists(install_root):
            os.makedirs(install_root, exist_ok=True)

        try:
            extract_archive_file(filepath, install_root)
        except Exception as e:
            self.log.error(e)
            raise InstallerDistributionError(
                "Install process failed without known reason."
                " Try to install AYON manually."
            )

        installer_dir = os.path.basename(filepath).replace(".tar.gz", "")
        executable = os.path.join(install_root, installer_dir, "ayon")
        self.log.info(f"Setting executable to {executable}")
        self._executable = executable

    def _install_macos(self, filepath: str):
        """Install macOS AYON launcher.

        Args:
            filepath (str): Path to a .dmg file.

        """
        import plistlib

        # Attach dmg file and read plist output (bytes)
        stdout = subprocess.check_output([
            "hdiutil", "attach", filepath, "-plist", "-nobrowse"
        ])
        mounted_volumes = []
        try:
            # Parse plist output and find mounted volume
            attach_info = plistlib.loads(stdout)
            for entity in attach_info["system-entities"]:
                mounted_volume = entity.get("mount-point")
                if mounted_volume:
                    mounted_volumes.append(mounted_volume)

            # We do expect there is only one .app in .dmg file
            src_path = None
            src_filename = None
            for mounted_volume in mounted_volumes:
                for filename in os.listdir(mounted_volume):
                    if filename.endswith(".app"):
                        src_filename = filename
                        src_path = os.path.join(mounted_volume, src_filename)
                        break

            if src_path is not None:
                # Copy the .app file to /Applications
                dst_dir = "/Applications"
                dst_path = os.path.join(dst_dir, src_filename)
                subprocess.run(["cp", "-rf", src_path, dst_dir])

        finally:
            # Detach mounted volume
            for mounted_volume in mounted_volumes:
                subprocess.run(["hdiutil", "detach", mounted_volume])

        # Find executable inside .app file and return its path
        contents_dir = os.path.join(dst_path, "Contents")
        # Load plist file and check for bundle executable
        plist_filepath = os.path.join(contents_dir, "Info.plist")
        if hasattr(plistlib, "load"):
            with open(plist_filepath, "rb") as stream:
                parsed_plist = plistlib.load(stream)
        else:
            parsed_plist = plistlib.readPlist(plist_filepath)
        executable_filename = parsed_plist.get("CFBundleExecutable")
        self._executable = os.path.join(
            contents_dir, "MacOS", executable_filename
        )

    def _install_file(self, filepath):
        """Trigger installation installer file based on platform."""

        # TODO consider using platform name in target folder
        #  - for windows and linux
        platform_name = platform.system().lower()
        if platform_name == "windows":
            self._install_windows(filepath)
        elif platform_name == "linux":
            self._install_linux(filepath)
        elif platform_name == "darwin":
            self._install_macos(filepath)
        else:
            raise InstallerDistributionError(
                f"Unsupported platform: {platform_name}"
            )

    def _post_source_process(
        self,
        filepath: str,
        source_data: dict[str, Any],
        source_progress: DistributeTransferProgress,
        downloader: SourceDownloader,
    ) -> Generator[Optional[bool], None, None]:
        self._installer_path = filepath
        success = False
        try:
            if filepath:
                self._install_file(filepath)
                success = True
            else:
                message = "File was not downloaded"
                source_progress.set_failed(message)

        except Exception as exc:
            message = "Installation failed"
            source_progress.set_failed(message)
            if isinstance(exc, InstallerDistributionError):
                self._installer_error = str(exc)
            else:
                self.log.warning(
                    f"{self.item_label}: {message}",
                    exc_info=True
                )
                self._installer_error = (
                    "Distribution of AYON launcher"
                    " failed with unexpected reason."
                )

        self.state = (
            UpdateState.UPDATED if success else UpdateState.UPDATE_FAILED
        )

        self._used_source = source_data
        if success or self._cleanup_on_fail:
            downloader.cleanup(
                source_data,
                self.download_dirpath,
                self.downloader_data
            )

        yield True


class DistributionItem(BaseDistributionItem):
    """Distribution item with sources and target directories.

    Distribution item for addons and dependency packages. They have defined
    unzip directory where the downloaded content is unzipped.

    Args:
        target_dirpath (str): Path to directory where zip is downloaded.
        download_dirpath (str): Path to directory where file is unzipped.
        state (UpdateState): Initial state (UpdateState.UPDATED or
            UpdateState.OUTDATED).
        file_hash (str): Hash of file for validation.
        factory (DownloadFactory): Downloaders factory object.
        sources (List[SourceInfo]): Possible sources to receive the
            distribution item.
        downloader_data (Dict[str, Any]): More information for downloaders.
        item_label (str): Label used in log outputs (and in UI).
        progress_dir (Optional[str]): Directory where progress is stored for
            other processes.
        logger (logging.Logger): Logger object.

    """
    def __init__(
        self, target_dirpath: str, unzip_temp_dir: str, *args, **kwargs
    ):
        self.target_dirpath = target_dirpath
        self.unzip_temp_dir = unzip_temp_dir
        super().__init__(*args, **kwargs)

    @property
    def is_missing_permissions(self) -> bool:
        return not _has_write_permissions(self.target_dirpath)

    def _post_source_process(
        self,
        filepath: str,
        source_data: dict[str, Any],
        source_progress: DistributeTransferProgress,
        downloader: SourceDownloader,
    ) -> Generator[Optional[bool], None, None]:
        source_progress.set_unzip_started()
        result = False
        for result in _wait_for_other_process(
            self._progress_dir, self._progress_id, self.log
        ):
            if result is not None:
                break
            yield None

        if result is True:
            self.state = UpdateState.UPDATED
            yield True
            return

        filename = os.path.basename(self.target_dirpath)
        unzip_dirpath = os.path.join(self.unzip_temp_dir, filename)
        # NOTE This is a workaround for dependency packages
        # TODO remove when dependency packages are not stored to directory
        #   ending with .zip
        if filepath == unzip_dirpath:
            filedir = os.path.dirname(filepath)
            ext = os.path.splitext(filepath)[-1]
            new_filepath = os.path.join(filedir, f"{uuid.uuid4().hex}{ext}")
            os.rename(filepath, new_filepath)
            filepath = new_filepath

        # Create directory
        os.makedirs(unzip_dirpath, exist_ok=True)
        change_permissions_recursive(unzip_dirpath)

        try:
            downloader.unzip(filepath, unzip_dirpath)
        except Exception:
            message = "Couldn't unzip source file"
            source_progress.set_failed(message)
            self.log.warning(
                f"{self.item_label}: {message}",
                exc_info=True
            )
            yield False
            return

        source_progress.set_unzip_finished()

        yield None

        result = False
        for result in _wait_for_other_process(
            self._progress_dir, self._progress_id, self.log
        ):
            if result is not None:
                break
            yield None

        if result is True:
            self.state = UpdateState.UPDATED
            yield True
            return

        failed = False
        renamed_mapping = []

        # Target directory can contain only distribution metadata file
        #   anything else is temporarily moved to different directory
        #   - next to target directory
        # NOTE: We might validate if the content is exactly same?
        tmp_subfolder = os.path.join(
            os.path.dirname(self.target_dirpath), uuid.uuid4().hex
        )
        if not os.path.exists(self.target_dirpath):
            os.makedirs(self.target_dirpath, exist_ok=True)
            change_permissions_recursive(self.target_dirpath)

        for name in os.listdir(self.target_dirpath):
            if name == DIST_PROGRESS_FILENAME:
                continue
            if not os.path.exists(tmp_subfolder):
                os.makedirs(tmp_subfolder, exist_ok=True)
                change_permissions_recursive(tmp_subfolder)

            current_path = os.path.join(self.target_dirpath, name)
            new_path = os.path.join(tmp_subfolder, name)
            try:
                os.rename(current_path, new_path)
            except Exception:
                message = (
                    "Target files already exist and can't be renamed."
                )
                source_progress.set_failed(message)
                self.log.warning(
                    f"{self.item_label}: {message}",
                    exc_info=True
                )
                failed = True
                break
            renamed_mapping.append((current_path, new_path))

        if failed:
            # Rollback renamed files
            for src_path, renamed_path in renamed_mapping:
                os.rename(renamed_path, src_path)
            yield False
            return

        yield None

        # Move unzipped content to target directory
        moved_paths = []
        rename_attemps = 5
        for subname in os.listdir(unzip_dirpath):
            target_path = os.path.join(self.target_dirpath, subname)
            src_path = os.path.join(unzip_dirpath, subname)
            dst_path = os.path.join(self.target_dirpath, subname)
            self.log.debug("Copying %s to %s", src_path, dst_path)
            # Sometimes 'os.rename' crashes because of permissions issue
            #   even though it can be done in a future attempt (probably some
            #   service traversing through files blocking it?)
            for attempt in range(rename_attemps):
                try:
                    os.rename(src_path, dst_path)
                    break
                except Exception:
                    if attempt < (rename_attemps - 1):
                        yield None
                        continue
                    message = (
                        "Failed to move unzipped content to target directory."
                    )
                    source_progress.set_failed(message)
                    self.log.warning(
                        f"{self.item_label}: {message}",
                        exc_info=True
                    )
                    failed = True

            if failed:
                break

            moved_paths.append(target_path)

        # Handle failed movement
        if failed:
            # Remove moved files
            for path in moved_paths:
                if os.path.isfile(path):
                    os.remove(path)
                else:
                    shutil.rmtree(path)

            # Rename renamed files back to original
            for src_path, renamed_path in renamed_mapping:
                os.rename(renamed_path, src_path)

        # Remove temp subfolder used for renaming
        if os.path.exists(tmp_subfolder):
            shutil.rmtree(tmp_subfolder)

        if failed:
            yield False
            return

        yield from super()._post_source_process(
            filepath, source_data, source_progress, downloader
        )

    def _post_distribute(self):
        if (
            self.state != UpdateState.UPDATED
            and self.target_dirpath
            and os.path.isdir(self.target_dirpath)
        ):
            self.log.debug(f"Cleaning {self.target_dirpath}")
            # TODO use '_clean_dist_dir' when backwards compatibility with
            #   previous versions of AYON launchers is not needed.
            # _clean_dist_dir(self.target_dirpath)
            shutil.rmtree(self.target_dirpath)


class AYONDistribution:
    """Distribution control.

    Receive information from server what addons and dependency packages
    should be available locally and prepare/validate their distribution.

    Arguments are available for testing of the class.

    Args:
        addon_dirpath (Optional[str]): Where addons will be stored.
        dependency_dirpath (Optional[str]): Where dependencies will be stored.
        dist_factory (Optional[DownloadFactory]): Factory which cares about
            downloading of items based on source type.
        installers_info (Optional[list[dict[str, Any]]]): List of prepared
            installers' info.
        addons_info (Optional[list[dict[str, Any]]]): List of prepared
            addons' info.
        dependency_packages_info (Optional[list[dict[str, Any]]]): Info
            about packages from server.
        bundles_info (Optional[dict[str, Any]]): Info about
            bundles.
        studio_bundle_name (Optional[str]): Name of studio bundle to use.
        project_bundle_name (Optional[str]): Name of project bundle to use.
        project_name (Optional[str]): Name of project for which project bundle
            can be auto-detected.
        use_staging (Optional[bool]): Use staging versions of an addon.
            If not passed, 'is_staging_enabled' is used as default value.
        use_dev (Optional[bool]): Use develop versions of an addon.
            If not passed, 'is_dev_mode_enabled' is used as default value.
        skip_installer_dist (bool): Skip installer distribution. This
            is for testing purposes and for running from code.

    """
    def __init__(
        self,
        addon_dirpath: Optional[str] = None,
        dependency_dirpath: Optional[str] = None,
        dist_factory: Optional[DownloadFactory] = None,
        installers_info: Optional[list[dict[str, Any]]] = NOT_SET,
        addons_info: Optional[list[dict[str, Any]]] = NOT_SET,
        dependency_packages_info: Optional[list[dict[str, Any]]] = NOT_SET,
        bundles_info: Optional[list[dict[str, Any]]] = NOT_SET,
        studio_bundle_name: Optional[str] = NOT_SET,
        project_bundle_name: Optional[str] = NOT_SET,
        project_name: Optional[str] = NOT_SET,
        use_staging: Optional[bool] = None,
        use_dev: Optional[bool] = None,
        active_user: Optional[bool] = None,
        skip_installer_dist: bool = False,
    ):
        self._log = None

        self._dist_started = False

        self._addons_dirpath = addon_dirpath or get_addons_dir()
        self._dependency_dirpath = dependency_dirpath or get_dependencies_dir()
        self._dist_factory = (
            dist_factory or get_default_download_factory()
        )

        if studio_bundle_name is NOT_SET:
            studio_bundle_name = (
                os.environ.get("AYON_STUDIO_BUNDLE_NAME") or NOT_SET
            )

        if project_bundle_name is NOT_SET:
            project_bundle_name = (
                os.environ.get("AYON_BUNDLE_NAME") or NOT_SET
            )

        if project_name is NOT_SET:
            project_name = os.environ.get("AYON_PROJECT_NAME") or NOT_SET

        # Where addon zip files and dependency packages are downloaded
        self._dist_download_dirs = []
        self._dist_unzip_dirs = []

        self._dist_addons_unzip_temp = os.path.join(
            self._addons_dirpath, ".unzip_temp"
        )
        self._dist_dep_packages_unzip_temp = os.path.join(
            self._dependency_dirpath, ".unzip_temp"
        )

        self._installers_info = installers_info
        self._installer_items = NOT_SET
        self._expected_installer_version = NOT_SET
        self._installer_item = NOT_SET
        self._installer_executable = NOT_SET
        self._skip_installer_dist = skip_installer_dist
        self._installer_filepath = None
        self._installer_dist_error = None

        # Raw addons data from server
        self._addons_info = addons_info
        # Prepared data as Addon objects
        self._addon_items = NOT_SET
        # Distrubtion items of addons
        #   - only those addons and versions that should be distributed
        self._addon_dist_items = NOT_SET

        # Raw dependency packages data from server
        self._dependency_packages_info = dependency_packages_info
        # Prepared dependency packages as objects
        self._dependency_packages_items = NOT_SET
        # Dependency package item that should be used
        self._dependency_package_item = NOT_SET
        # Distribution item of dependency package
        self._dependency_dist_item = NOT_SET

        # Raw bundles data from server
        self._bundles_info = bundles_info
        # Bundles as objects
        self._bundle_items = NOT_SET

        # Bundle that should be used in production
        self._studio_production_bundle = NOT_SET
        # Bundle that should be used in staging
        self._studio_staging_bundle = NOT_SET
        # Bundle that should be used in dev
        self._studio_dev_bundle = NOT_SET
        # Boolean that defines if staging bundle should be used
        self._use_staging = use_staging
        self._use_dev = use_dev
        self._active_user = active_user

        # Specific bundle name should be used
        self._studio_bundle_name = studio_bundle_name
        self._project_bundle_name = project_bundle_name
        self._project_name = project_name

        # Final bundles that will be used
        self._studio_bundle = NOT_SET
        self._project_bundle = NOT_SET

    @property
    def active_user(self) -> str:
        if self._active_user is None:
            user = ayon_api.get_user()
            self._active_user = user["name"]
        return self._active_user

    @property
    def use_staging(self) -> bool:
        """Staging version of a bundle should be used.

        This value is completely ignored if specific bundle name should
            be used.

        Returns:
            bool: True if staging version should be used.

        """
        if self._use_staging is None:
            self._use_staging = is_staging_enabled()

        if self._use_staging and self.use_dev:
            self._use_staging = False
        return self._use_staging

    @property
    def use_dev(self) -> bool:
        """Develop version of a bundle should be used.

        This value is completely ignored if specific bundle name should
            be used.

        Returns:
            bool: True if staging version should be used.

        """
        if self._use_dev is None:
            if self._studio_bundle_name is NOT_SET:
                self._use_dev = is_dev_mode_enabled()
            else:
                bundle = next(
                    (
                        bundle
                        for bundle in self.bundle_items
                        if bundle.name == self._studio_bundle_name
                    ),
                    None
                )
                if bundle is not None:
                    self._use_dev = bundle.is_dev
                else:
                    self._use_dev = False
        return self._use_dev

    @property
    def log(self) -> logging.Logger:
        """Helper to access logger.

        Returns:
             logging.Logger: Logger instance.

        """
        if self._log is None:
            self._log = logging.getLogger(self.__class__.__name__)
        return self._log

    @property
    def bundles_info(self) -> list[dict[str, Any]]:
        """

        Returns:
            list[dict[str, Any]]: Bundles information from server.

        """
        if self._bundles_info is NOT_SET:
            self._bundles_info = ayon_api.get_bundles()["bundles"]
        return self._bundles_info

    @property
    def bundle_items(self) -> list[Bundle]:
        """

        Returns:
            list[Bundle]: List of bundles info.

        """
        if self._bundle_items is NOT_SET:
            self._bundle_items = [
                Bundle.from_dict(info)
                for info in self.bundles_info
            ]
        return self._bundle_items

    @property
    def studio_production_bundle(self) -> Optional[Bundle]:
        """

        Returns:
            Optional[Bundle]: Bundle that should be used in production.

        """
        if self._studio_production_bundle is NOT_SET:
            self._prepare_bundles()
        return self._studio_production_bundle

    @property
    def studio_staging_bundle(self) -> Optional[Bundle]:
        """

        Returns:
            Optional[Bundle]: Bundle that should be used in staging.

        """
        if self._studio_staging_bundle is NOT_SET:
            self._prepare_bundles()
        return self._studio_staging_bundle

    @property
    def studio_dev_bundle(self) -> Optional[Bundle]:
        """

        Returns:
            Optional[Bundle]: Bundle that should be used in dev.

        """
        if self._studio_dev_bundle is NOT_SET:
            self._prepare_bundles()
        return self._studio_dev_bundle

    @property
    def studio_bundle_to_use(self) -> Optional[Bundle]:
        """

        Returns:
            Optional[Bundle]: Bundle that should be used in distribution.

        """
        if self._studio_bundle is not NOT_SET:
            return self._studio_bundle

        self._prepare_bundles()
        if self._studio_bundle_name is NOT_SET:
            if self.use_staging:
                self._studio_bundle = self.studio_staging_bundle
            elif self.use_dev:
                self._studio_bundle = self.studio_dev_bundle
            else:
                self._studio_bundle = self.studio_production_bundle
            return self._studio_bundle

        bundle = next(
            (
                bundle
                for bundle in self.bundle_items
                if bundle.name == self._studio_bundle_name
            ),
            None
        )
        if bundle is None:
            raise BundleNotFoundError(self._studio_bundle_name)
        self._studio_bundle = bundle
        return self._studio_bundle

    @property
    def project_bundle_to_use(self) -> Optional[Bundle]:
        """Bundle that will be used for distribution.

        Bundle that should be used can be affected by 'project_bundle_name',
            'project_name', 'studio_bundle_name' or 'use_staging'.

        Returns:
            Optional[Bundle]: Bundle that will be used for distribution
                or None.

        Raises:
            BundleNotFoundError: When bundle name to use is defined
                but is not available on server.

        """
        if not self._project_bundle:
            project_bundle = self._get_project_bundle()
            if not project_bundle:
                project_bundle = self.studio_bundle_to_use
            self._project_bundle = project_bundle
        return self._project_bundle

    @property
    def project_bundle_name_to_use(self) -> Optional[str]:
        """Name of bundle that will be used for distribution.

        Returns:
            Optional[str]: Name of bundle that will be used for
                distribution.

        """
        bundle = self.project_bundle_to_use
        return None if bundle is None else bundle.name

    @property
    def installers_info(self) -> list[dict[str, Any]]:
        """Installers information from server.

        Returns:
            list[dict[str, Any]]: Installers information from server.

        """
        if self._installers_info is NOT_SET:
            self._installers_info = ayon_api.get_installers()["installers"]
        return self._installers_info

    @property
    def installer_items(self) -> list[Installer]:
        """Installers as objects.

        Returns:
            list[Installer]: List of installers info from server.

        """
        if self._installer_items is NOT_SET:
            self._installer_items = [
                Installer.from_dict(info)
                for info in self.installers_info
            ]
        return self._installer_items

    @property
    def expected_installer_version(self) -> Optional[str]:
        """Excepted installer version.

        Returns:
            Optional[str]: Expected installer version or None defined by
                bundle that should be used.

        """
        if self._expected_installer_version is not NOT_SET:
            return self._expected_installer_version

        bundle = self.project_bundle_to_use
        version = None if bundle is None else bundle.installer_version
        self._expected_installer_version = version
        return version

    @property
    def need_installer_change(self) -> bool:
        """Installer should be changed.

        Current installer is using different version than what is expected
            by bundle.

        Returns:
            bool: True if installer should be changed.

        """
        if self._skip_installer_dist:
            return False

        version = os.getenv("AYON_VERSION")
        return version != self.expected_installer_version

    @property
    def need_installer_distribution(self) -> bool:
        """Installer distribution is needed.

        Todos:
            Add option to skip if running from code?

        Returns:
            bool: True if installer distribution is needed.

        """
        if not self.need_installer_change:
            return False

        return self.installer_executable is None

    @property
    def installer_dist_error(self) -> Optional[str]:
        """Installer distribution error message.

        Returns:
              Optional[str]: Error that happened during installer
                distribution.

        """
        return self._installer_dist_error

    @property
    def installer_filepath(self) -> Optional[str]:
        """Path to a distribution package/installer.

        This can be used as reference for user where to find downloaded
            installer on disk and distribute it manually.

        Returns:
            Optional[str]: Path to installer.

        """
        return self._installer_filepath

    @property
    def installer_executable(self) -> Optional[str]:
        """Path to installer executable that should be used.

        Notes:
            The 'installer_executable' is maybe confusing naming. It might be
                called 'ayon_executable'?

        Returns:
            Optional[str]: Path to installer executable that should be
                used. None if executable is not found and must be distributed
                or bundle does not have defined an installer to use.

        """
        if self._installer_executable is not NOT_SET:
            return self._installer_executable

        path = None
        if not self.need_installer_change:
            self._installer_executable = sys.executable
            return self._installer_executable

        # Compare existing executable with current executable
        current_executable = sys.executable
        # Use 'ayon.exe' for executable lookup on Windows
        root, filename = os.path.split(current_executable)
        if filename == "ayon_console.exe":
            current_executable = os.path.join(root, "ayon.exe")

        # TODO look to expected target install directory too
        executables_info = get_executables_info_by_version(
            self.expected_installer_version)
        for executable_info in executables_info:
            executable_path = executable_info.get("executable")
            if (
                not os.path.exists(executable_path)
                or executable_path == current_executable
            ):
                continue
            path = executable_path
            break

        # Make sure current executable filename is used on Windows
        if path and filename == "ayon_console.exe":
            path = os.path.join(os.path.dirname(path), filename)

        if path:
            self._installer_executable = path
            return path

        # Guess based on "expected" path of the version
        # - is used if the AYON is already installed at target location but is
        #   missing in the metadata file
        current_version = os.environ["AYON_VERSION"]
        platform_name = platform.system().lower()
        if platform_name in {"windows", "linux"}:
            executable_dir, exe_name = os.path.split(sys.executable)
            install_root, dirname = os.path.split(executable_dir)
            if current_version in dirname:
                new_dirname = dirname.replace(
                    current_version,
                    self.expected_installer_version
                )
                executable = os.path.join(
                    install_root, new_dirname, exe_name
                )
                if os.path.exists(executable):
                    path = executable

        elif platform_name == "darwin":
            app_name = f"AYON {self.expected_installer_version}.app"
            excutable = f"/Applications/{app_name}/Contents/MacOS/ayon"
            if os.path.exists(excutable):
                path = excutable

        self._installer_executable = path
        return path

    @property
    def installer_item(self):
        """Installer item that should be used for distribution.

        Returns:
            Union[Installer, None]: Installer information item.

        """
        if self._installer_item is not NOT_SET:
            return self._installer_item

        final_item = None
        expected_version = self.expected_installer_version
        if expected_version:
            final_item = next(
                (
                    item
                    for item in self.installer_items
                    if (
                        item.version == expected_version
                        and item.platform_name == platform.system().lower()
                    )
                ),
                None
            )

        self._installer_item = final_item
        return final_item

    def distribute_installer(self):
        """Distribute installer."""

        installer_item = self.installer_item
        if installer_item is None:
            self._installer_executable = None
            self._installer_dist_error = (
                f"Bundle '{self.project_bundle_name_to_use}'"
                " does not have set installer version to use."
            )
            return

        downloader_data = {
            "type": "installer",
            "version": installer_item.version,
            "filename": installer_item.filename,
        }

        tmp_used = False
        downloads_dir = get_downloads_dir()
        if not downloads_dir or not os.path.exists(downloads_dir):
            tmp_used = True
            downloads_dir = tempfile.mkdtemp(prefix="ayon_installer")
            change_permissions_recursive(downloads_dir)

        dist_item = None
        try:
            dist_item = InstallerDistributionItem(
                tmp_used,
                downloads_dir,
                UpdateState.OUTDATED,
                installer_item.checksum,
                installer_item.checksum_algorithm,
                self._dist_factory,
                list(installer_item.sources),
                downloader_data,
                f"Installer {installer_item.version}",
            )

            if (
                platform.system().lower() != "windows"
                and dist_item.is_missing_permissions
            ):
                self._installer_dist_error = (
                    "Your user does not have required permissions to update"
                    " AYON launcher."
                    " Please contact your administrator, or use user"
                    " with permissions."
                )
                return

            for result in dist_item.distribute():
                if result:
                    break

            self._installer_executable = dist_item.executable
            if dist_item.installer_error is not None:
                self._installer_dist_error = dist_item.installer_error

            elif dist_item.state == UpdateState.MISS_SOURCE_FILES:
                self._installer_dist_error = (
                    "Couldn't find valid installer source for required"
                    f" AYON launcher version {installer_item.version}."
                )

            elif not self._installer_executable:
                self._installer_dist_error = (
                    "Couldn't find installed AYON launcher."
                    " Please try to launch AYON manually."
                )

        except Exception:
            self.log.warning(
                "Installer distribution failed do to unknown reasons.",
                exc_info=True
            )
            self._installer_dist_error = (
                f"Distribution of AYON launcher {installer_item.version}"
                " failed with unexpected reason."
            )

        finally:
            if dist_item is not None:
                self._installer_filepath = dist_item.installer_path

            if tmp_used and os.path.exists(downloads_dir):
                shutil.rmtree(downloads_dir)

    @property
    def addons_info(self) -> dict[str, dict[str, Any]]:
        """Server information about available addons.

        Returns:
            dict[str, dict[str, Any]]: Addon info by addon name.

        """
        if self._addons_info is NOT_SET:
            # Use details to get information about client.zip
            server_info = ayon_api.get_addons_info(details=True)
            self._addons_info = server_info["addons"]
        return self._addons_info

    @property
    def addon_items(self) -> dict[str, AddonInfo]:
        """Information about available addons on server.

        Addons may require distribution of files. For those addons will be
        created 'DistributionItem' handling distribution itself.

        Returns:
            dict[str, AddonInfo]: Addon info object by addon name.

        """
        if self._addon_items is NOT_SET:
            addons_info = {}
            for addon in self.addons_info:
                addon_info = AddonInfo.from_dict(addon)
                addons_info[addon_info.name] = addon_info
            self._addon_items = addons_info
        return self._addon_items

    @property
    def dependency_packages_info(self) -> list[dict[str, Any]]:
        """Server information about available dependency packages.

        Notes:
            For testing purposes it is possible to pass dependency packages
                information to '__init__'.

        Returns:
            list[dict[str, Any]]: Dependency packages information.

        """
        if self._dependency_packages_info is NOT_SET:
            self._dependency_packages_info = (
                ayon_api.get_dependency_packages())["packages"]
        return self._dependency_packages_info

    @property
    def dependency_packages_items(self) -> dict[str, DependencyItem]:
        """Dependency packages as objects.

        Returns:
            dict[str, DependencyItem]: Dependency packages as objects by name.

        """
        if self._dependency_packages_items is NOT_SET:
            dependenc_package_items = {}
            for item in self.dependency_packages_info:
                item = DependencyItem.from_dict(item)
                dependenc_package_items[item.filename] = item
            self._dependency_packages_items = dependenc_package_items
        return self._dependency_packages_items

    @property
    def dependency_package_item(self) -> Optional[DependencyItem]:
        """Dependency package item that should be used by bundle.

        Returns:
            Optional[DependencyItem]: None if bundle does not have
                specified dependency package.

        """
        if self._dependency_package_item is NOT_SET:
            dependency_package_item = None
            bundle = self.project_bundle_to_use
            if bundle is not None:
                package_name = bundle.dependency_packages.get(
                    platform.system().lower()
                )
                dependency_package_item = self.dependency_packages_items.get(
                    package_name)
            self._dependency_package_item = dependency_package_item
        return self._dependency_package_item

    def get_addon_dist_items(self) -> list[dict[str, Any]]:
        """Addon distribution items.

        These items describe source files required by addon to be available on
        machine. Each item may have 0-n source information from where can be
        obtained. If file is already available it's state will be 'UPDATED'.

        Example output:
            [
                {
                    "dist_item": DistributionItem,
                    "addon_name": str,
                    "addon_version": str,
                    "addon_item": AddonInfo,
                    "addon_version_item": AddonVersionInfo
                }, {
                    ...
                }
            ]

        Returns:
             list[dict[str, Any]]: Distribution items with addon version item.

        """
        if self._addon_dist_items is NOT_SET:
            self._addon_dist_items = (
                self._prepare_current_addon_dist_items())
        return self._addon_dist_items

    def get_dependency_dist_item(self) -> Optional[DistributionItem]:
        """Dependency package distribution item.

        Item describe source files required by server to be available on
        machine. Item may have 0-n source information from where can be
        obtained. If file is already available it's state will be 'UPDATED'.

        'None' is returned if server does not have defined any dependency
        package.

        Returns:
            Optional[DistributionItem]: Dependency item or None if server
                does not have specified any dependency package.

        """
        if self._dependency_dist_item is NOT_SET:
            self._dependency_dist_item = self._prepare_dependency_progress()
        return self._dependency_dist_item

    def get_dependency_metadata_filepath(self) -> str:
        """Path to distribution metadata file.

        Metadata contain information about distributed packages, used source,
        expected file hash and time when file was distributed.

        Returns:
            str: Path to a file where dependency package metadata are stored.

        """
        return os.path.join(self._dependency_dirpath, "dependency.json")

    def get_addons_metadata_filepath(self) -> str:
        """Path to addons metadata file.

        Metadata contain information about distributed addons, used sources,
        expected file hashes and time when files were distributed.

        Returns:
            str: Path to a file where addons metadata are stored.

        """
        return os.path.join(self._addons_dirpath, "addons.json")

    @staticmethod
    def read_metadata_file(
        filepath: str,
        default_value: Optional[Any] = None,
    ) -> dict[str, Any]:
        """Read json file from path.

        Method creates the file when does not exist with default value.

        Args:
            filepath (str): Path to json file.
            default_value (Union[Dict[str, Any], List[Any], None]): Default
                value if the file is not available (or valid).

        Returns:
            Union[Dict[str, Any], List[Any]]: Value from file.
        """

        if default_value is None:
            default_value = {}

        if not os.path.exists(filepath):
            return default_value

        try:
            with open(filepath, "r") as stream:
                data = json.load(stream)
        except ValueError:
            data = default_value
        return data

    @staticmethod
    def save_metadata_file(filepath: str, data: dict[str, Any]):
        """Store data to json file.

        Method creates the file when does not exist.

        Args:
            filepath (str): Path to json file.
            data (dict[str, Any]): Data to store into file.

        """
        dirpath = os.path.dirname(filepath)
        os.makedirs(dirpath, exist_ok=True)
        with open(filepath, "w") as stream:
            json.dump(data, stream, indent=4)
        change_permissions_recursive(dirpath)

    def get_dependency_metadata(self) -> dict[str, Any]:
        filepath = self.get_dependency_metadata_filepath()
        return self.read_metadata_file(filepath, {})

    def update_dependency_metadata(
        self, package_name: str, data: dict[str, Any]
    ):
        dependency_metadata = self.get_dependency_metadata()
        dependency_metadata[package_name] = data
        filepath = self.get_dependency_metadata_filepath()
        self.save_metadata_file(filepath, dependency_metadata)

    def get_addons_metadata(self) -> dict[str, Any]:
        filepath = self.get_addons_metadata_filepath()
        return self.read_metadata_file(filepath, {})

    def update_addons_metadata(self, addons_information: dict[str, Any]):
        if not addons_information:
            return
        addons_metadata = self.get_addons_metadata()
        for addon_name, version_value in addons_information.items():
            if addon_name not in addons_metadata:
                addons_metadata[addon_name] = {}
            for addon_version, version_data in version_value.items():
                addons_metadata[addon_name][addon_version] = version_data

        filepath = self.get_addons_metadata_filepath()
        self.save_metadata_file(filepath, addons_metadata)

    def finish_distribution(self):
        """Store metadata about distributed items."""
        for tmp_dir in (
            self._dist_download_dirs + self._dist_unzip_dirs
        ):
            if os.path.exists(tmp_dir):
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass

        stored_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # TODO store dependencies info inside dependencies folder instead
        #   of having one file
        # - the file can be used to track progress and find out if other
        #   process is already working on distribution
        dependency_dist_item = self.get_dependency_dist_item()
        if (
            dependency_dist_item is not None
            and dependency_dist_item.need_distribution
            and dependency_dist_item.state == UpdateState.UPDATED
        ):
            package = self.dependency_package_item
            source = dependency_dist_item.used_source
            if source is not None:
                data = {
                    "source": source,
                    "checksum": dependency_dist_item.checksum,
                    "checksum_algorithm": (
                        dependency_dist_item.checksum_algorithm),
                    "distributed_dt": stored_time
                }
                self.update_dependency_metadata(package.filename, data)

        # TODO store addon info inside addon folder instead of having one
        #   of having one file
        # - the file can be used to track progress and find out if other
        #   process is already working on distribution
        addons_info = {}
        for item in self.get_addon_dist_items():
            dist_item = item["dist_item"]
            if (
                not dist_item.need_distribution
                or dist_item.state != UpdateState.UPDATED
            ):
                continue

            source_data = dist_item.used_source
            if not source_data:
                continue

            addon_name = item["addon_name"]
            addon_version = item["addon_version"]
            addons_info.setdefault(addon_name, {})
            addons_info[addon_name][addon_version] = {
                "source": source_data,
                "checksum": dist_item.checksum,
                "checksum_algorithm": dist_item.checksum_algorithm,
                "distributed_dt": stored_time
            }

        self.update_addons_metadata(addons_info)

        _cleanup_dist_download_dirs()
        _cleanup_dist_expire_dirs(self._dist_addons_unzip_temp)
        _cleanup_dist_expire_dirs(self._dist_dep_packages_unzip_temp)

    def get_all_distribution_items(self) -> list[DistributionItem]:
        """Distribution items required by server.

        Items contain dependency package item and all addons that are enabled
        and have distribution requirements.

        Items can be already available on machine.

        Returns:
            list[DistributionItem]: Distribution items required by server.

        """
        output = [
            item["dist_item"]
            for item in self.get_addon_dist_items()
        ]
        dependency_dist_item = self.get_dependency_dist_item()
        if dependency_dist_item is not None:
            output.insert(0, dependency_dist_item)

        return output

    @property
    def need_distribution(self) -> bool:
        """Distribution is needed.

        Returns:
            bool: True if any distribution is needed.

        """
        if self.need_installer_change:
            if self.need_installer_distribution:
                return True
            return False

        for item in self.get_all_distribution_items():
            if item.need_distribution:
                return True
        return False

    @property
    def is_missing_permissions(self):
        # Do not validate installer (launcher) distribution as that is
        #   reported with '_installer_dist_error'
        for item in self.get_all_distribution_items():
            if item.need_distribution and item.is_missing_permissions:
                return True
        return False

    def distribute(self):
        """Distribute all missing items.

        Method will try to distribute all items that are required by server.

        This method does not handle failed items. To validate the result call
        'validate_distribution' when this method finishes.

        """
        if self._dist_started:
            raise RuntimeError("Distribution already started")
        self._dist_started = True

        if self.need_installer_change:
            if self.need_installer_distribution:
                self.distribute_installer()
            return

        dist_items = []
        for dist_item in self.get_all_distribution_items():
            if not dist_item.is_distributed():
                dist_items.append(dist_item)
                _create_dist_expire_file(dist_item.download_dirpath)

        running_items = collections.deque()
        for item in dist_items:
            running_items.append(item.distribute())

        if running_items:
            running_items.append(None)

        try:
            while running_items:
                running_item = running_items.popleft()
                if running_item is None:
                    if running_items:
                        running_items.append(None)
                        time.sleep(0.02)
                    continue

                if not next(running_item):
                    running_items.append(running_item)

        finally:
            self.finish_distribution()

    def validate_distribution(self):
        """Check if all required distribution items are distributed.

        Raises:
            RuntimeError: Any of items is not available.

        """
        invalid = []
        dependency_package = self.get_dependency_dist_item()
        if (
            dependency_package is not None
            and dependency_package.state != UpdateState.UPDATED
        ):
            invalid.append("Dependency package")

        for item in self.get_addon_dist_items():
            dist_item = item["dist_item"]
            if dist_item.state != UpdateState.UPDATED:
                invalid.append(item["addon_name"])

        if not invalid:
            return

        raise RuntimeError("Failed to distribute {}".format(
            ", ".join([f'"{item}"' for item in invalid])
        ))

    def get_sys_paths(self) -> list[str]:
        """Get all paths to python packages that should be added to path.

        These packages will be added only to 'sys.path' and not into
        'PYTHONPATH', so they won't be available in subprocesses.

        Todos:
            This is not yet implemented. The goal is that dependency
                package will contain also 'build' python
                dependencies (OpenTimelineIO, Pillow, etc.).

        Returns:
            list[str]: Paths that should be added to 'sys.path'.

        """
        output = []
        dependency_dist_item = self.get_dependency_dist_item()
        if dependency_dist_item is not None:
            runtime_dir = None
            target_dirpath = dependency_dist_item.target_dirpath
            if target_dirpath:
                runtime_dir = os.path.join(target_dirpath, "runtime")

            if runtime_dir and os.path.exists(runtime_dir):
                output.append(runtime_dir)
        return output

    def get_python_paths(self) -> list[str]:
        """Get all paths to python packages that should be added to python.

        These paths lead to addon directories and python dependencies in
        dependency package.

        Returns:
            List[str]: Paths that should be added to 'sys.path' and
                'PYTHONPATH'.

        """
        output = []
        for item in self.get_addon_dist_items():
            dist_item = item["dist_item"]
            if dist_item.state != UpdateState.UPDATED:
                continue
            target_dirpath = dist_item.target_dirpath
            if target_dirpath and os.path.exists(target_dirpath):
                output.append(target_dirpath)

        output.extend(self._get_dev_sys_paths())

        dependency_dist_item = self.get_dependency_dist_item()
        if dependency_dist_item is not None:
            dependencies_dir = None
            target_dirpath = dependency_dist_item.target_dirpath
            if target_dirpath:
                dependencies_dir = os.path.join(target_dirpath, "dependencies")

            if dependencies_dir and os.path.exists(dependencies_dir):
                output.append(dependencies_dir)
        return output

    def _get_dev_sys_paths(self) -> list[str]:
        output = []
        if not self.use_dev:
            return output

        addon_versions = {}
        dev_addons = {}
        bundle = self.project_bundle_to_use
        if bundle is not None:
            dev_addons = bundle.addons_dev_info
            addon_versions = bundle.addon_versions

        for addon_name, _ in self.addon_items.items():
            addon_version = addon_versions.get(addon_name)
            # Addon is not in bundle -> Skip
            if addon_version is None:
                continue

            dev_addon_info = dev_addons.get(addon_name)
            if dev_addon_info is not None and dev_addon_info.enabled:
                try:
                    output.append(
                        dev_addon_info.path.format(**os.environ)
                    )
                except KeyError:
                    self.log.warning(
                        f"Failed to format path '{dev_addon_info.path}'"
                        f" for addon '{addon_name}'."
                    )

        return output

    def _prepare_bundles(self):
        studio_production_bundle = None
        studio_staging_bundle = None
        studio_dev_bundle = None
        for bundle in self.bundle_items:
            if bundle.is_project_bundle:
                continue

            if bundle.is_production:
                studio_production_bundle = bundle
            if bundle.is_staging:
                studio_staging_bundle = bundle
            if bundle.is_dev and bundle.active_dev_user == self.active_user:
                studio_dev_bundle = bundle
        self._studio_production_bundle = studio_production_bundle
        self._studio_staging_bundle = studio_staging_bundle
        self._studio_dev_bundle = studio_dev_bundle

    def _prepare_current_addon_dist_items(self) -> list[dict[str, Any]]:
        addons_metadata = self.get_addons_metadata()
        output = []
        addon_versions = {}
        dev_addons = {}
        bundle = self.project_bundle_to_use
        if bundle is not None:
            dev_addons = bundle.addons_dev_info
            addon_versions = bundle.addon_versions

        unzip_temp = os.path.join(self._addons_dirpath, ".unzip_temp")
        if not os.path.exists(unzip_temp):
            os.makedirs(unzip_temp)
            change_permissions_recursive(unzip_temp)

        for addon_name, addon_item in self.addon_items.items():
            # Dev mode can redirect addon directory elsewhere
            if self.use_dev:
                dev_addon_info = dev_addons.get(addon_name)
                if dev_addon_info is not None and dev_addon_info.enabled:
                    continue

            addon_version = addon_versions.get(addon_name)
            # Addon is not in bundle -> Skip
            if addon_version is None:
                continue

            addon_version_item = addon_item.versions.get(addon_version)
            # Addon version is not available in addons info
            # - TODO handle this case (raise error, skip, store, report, ...)
            if addon_version_item is None:
                print(
                    f"Version '{addon_version}' of addon '{addon_name}'"
                    " is not available on server."
                )
                continue

            if not addon_version_item.require_distribution:
                continue
            full_name = addon_version_item.full_name
            addon_dest = os.path.join(self._addons_dirpath, full_name)
            self.log.debug(f"Checking {full_name} in {addon_dest}")
            progress_info = _read_progress_file(addon_dest)
            state = UpdateState.OUTDATED
            if progress_info:
                if progress_info.get("state") == DistFileStates.done.value:
                    state = UpdateState.UPDATED
            else:
                addon_in_metadata = (
                    addon_name in addons_metadata
                    and addon_version_item.version in (
                        addons_metadata[addon_name]
                    )
                )
                if addon_in_metadata and os.path.isdir(addon_dest):
                    self.log.debug(
                        f"Addon version folder {addon_dest} already exists."
                    )
                    state = UpdateState.UPDATED
                    # Auto-create addons dist file extracted with old versions
                    _create_progress_file(
                        addon_dest,
                        uuid.uuid4().hex,
                        addon_version_item.checksum,
                        addon_version_item.checksum_algorithm,
                    )

            download_dir = _get_dist_download_dir(uuid.uuid4().hex)
            unzip_dir = os.path.join(unzip_temp, uuid.uuid4().hex)
            self._dist_download_dirs.append(download_dir)
            self._dist_unzip_dirs.append(unzip_dir)
            downloader_data = {
                "type": "addon",
                "name": addon_name,
                "version": addon_version
            }
            dist_item = DistributionItem(
                addon_dest,
                unzip_dir,
                download_dirpath=download_dir,
                state=state,
                checksum=addon_version_item.checksum,
                checksum_algorithm=addon_version_item.checksum_algorithm,
                factory=self._dist_factory,
                sources=list(addon_version_item.sources),
                downloader_data=downloader_data,
                item_label=full_name,
                progress_dir=addon_dest,
                logger=self.log
            )
            output.append({
                "dist_item": dist_item,
                "addon_name": addon_name,
                "addon_version": addon_version,
                "addon_item": addon_item,
                "addon_version_item": addon_version_item,
            })
        return output

    def _prepare_dependency_progress(self) -> Optional[DistributionItem]:
        package = self.dependency_package_item
        if package is None:
            return None

        metadata = self.get_dependency_metadata()
        downloader_data = {
            "type": "dependency_package",
            "name": package.filename,
            "platform": package.platform_name
        }
        package_dir = os.path.join(
            self._dependency_dirpath, package.filename
        )
        # Future compatibility for dependency packages without .zip in dirname
        new_basename = os.path.splitext(package.filename)[0]
        new_package_dir = os.path.join(self._dependency_dirpath, new_basename)

        download_dir = _get_dist_download_dir(uuid.uuid4().hex)
        unzip_dir = os.path.join(self._dependency_dirpath, uuid.uuid4().hex)
        self._dist_download_dirs.append(download_dir)
        self._dist_unzip_dirs.append(unzip_dir)

        self.log.debug(f"Checking {package.filename} in {package_dir}")
        state = UpdateState.OUTDATED
        progress_info = _read_progress_file(package_dir)
        new_progress_info = _read_progress_file(new_package_dir)
        if progress_info:
            if progress_info.get("state") == DistFileStates.done.value:
                state = UpdateState.UPDATED

        elif new_progress_info:
            if new_progress_info.get("state") == DistFileStates.done.value:
                state = UpdateState.UPDATED
                package_dir = new_package_dir

        elif (
            os.path.isdir(package_dir)
            and package.filename in metadata
        ):
            state = UpdateState.UPDATED
            # Autofix dependency packages extracted with old versions
            _create_progress_file(
                package_dir,
                uuid.uuid4().hex,
                package.checksum,
                package.checksum_algorithm,
            )

        return DistributionItem(
            package_dir,
            unzip_dir,
            download_dirpath=download_dir,
            state=state,
            checksum=package.checksum,
            checksum_algorithm=package.checksum_algorithm,
            factory=self._dist_factory,
            sources=package.sources,
            downloader_data=downloader_data,
            item_label=os.path.splitext(package.filename)[0],
            progress_dir=package_dir,
            logger=self.log,
        )

    def _get_project_bundle(self) -> Optional[Bundle]:
        if self._project_bundle is not NOT_SET:
            return self._project_bundle

        # Project bundle is set and is same as studio bundle
        studio_bundle_name = self.studio_bundle_to_use.name
        if self._project_bundle_name == studio_bundle_name:
            self._project_bundle = None
            return None

        if (
            not self._project_bundle_name
            and self._project_name is not NOT_SET
        ):
            project = ayon_api.get_project(self._project_name)
            project_bundles = project["data"].get("bundle", {})
            bundle_name = None
            if self.use_staging:
                bundle_name = project_bundles.get("staging")
            elif not self.use_dev:
                bundle_name = project_bundles.get("production")

            if bundle_name:
                self._project_bundle_name = bundle_name

        if not self._project_bundle_name:
            self._project_bundle = None
            return None

        bundle = next(
            (
                bundle
                for bundle in self.bundle_items
                if bundle.name == self._project_bundle_name
            ),
            None
        )
        if bundle is None:
            raise BundleNotFoundError(self._project_bundle_name)

        if studio_bundle_name:
            key_values = {
                "summary": "true",
                "bundle": studio_bundle_name,
            }
            query = urlencode(key_values)
            response = ayon_api.get(f"settings?{query}")
            # NOTE This does modify the bundle data
            # - should be fine as it really does fill up the project bundle
            for addon in response.data["addons"]:
                addon_name = addon["name"]
                addon_version = addon["version"]
                bundle.addon_versions[addon_name] = addon_version

        self._project_bundle = bundle
        return bundle


def cli(*args):
    raise NotImplementedError
