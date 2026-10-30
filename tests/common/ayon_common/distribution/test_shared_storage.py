"""Tests for distribution into a storage folder shared by processes."""
import os
import sys
import json
import time
import uuid
import shutil
import zipfile
import threading

ROOT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )
)
# 'ayon_common' is imported as top level package, same as in 'start.py'
sys.path.insert(0, os.path.join(ROOT_DIR, "common"))

from ayon_common.distribution import control  # noqa: E402
from ayon_common.distribution.control import (  # noqa: E402
    AYONDistribution,
    DistributionItem,
    DistFileStates,
    UpdateState,
)
from ayon_common.distribution.downloaders import (  # noqa: E402
    DownloadFactory,
    OSDownloader,
    SourceDownloader,
)
from ayon_common.distribution.data_structures import (  # noqa: E402
    LocalSourceInfo,
    MultiPlatformValue,
    UrlType,
)

ADDON_DIRNAME = "my_addon_1.0.0"


class _CopyDownloader(SourceDownloader):
    """Copies zip from 'filesystem' source, optionally slow or failing."""
    delay = 0.0
    fail = False

    @classmethod
    def download(cls, source, destination_dir, data, transfer_progress):
        if cls.fail:
            raise RuntimeError("Download failed")
        time.sleep(cls.delay)
        os.makedirs(destination_dir, exist_ok=True)
        src_path = source["path"]["windows"]
        dst_path = os.path.join(destination_dir, os.path.basename(src_path))
        shutil.copyfile(src_path, dst_path)
        return dst_path

    @classmethod
    def cleanup(cls, source, destination_dir, data):
        pass


def _make_source_zip(tmp_path, files=None) -> str:
    if files is None:
        files = {
            "my_addon/__init__.py": "VALUE = 1\n",
            "my_addon/big.bin": "x" * 2_000_000,
        }
    source_zip = str(tmp_path / f"client_{uuid.uuid4().hex}.zip")
    with zipfile.ZipFile(source_zip, "w") as zip_file:
        for path, content in files.items():
            zip_file.writestr(path, content)
    return source_zip


def _make_dist_item(
    tmp_path, source_zip, downloader=_CopyDownloader
) -> DistributionItem:
    factory = DownloadFactory()
    factory.register_format(UrlType.FILESYSTEM, downloader)
    path = MultiPlatformValue(
        windows=source_zip, linux=source_zip, darwin=source_zip
    )
    addons_dir = tmp_path / "addons"
    target_dir = str(addons_dir / ADDON_DIRNAME)
    process_id = uuid.uuid4().hex
    return DistributionItem(
        target_dir,
        str(addons_dir / ".unzip_temp" / process_id),
        download_dirpath=str(tmp_path / "downloads" / process_id),
        state=UpdateState.OUTDATED,
        checksum=None,
        checksum_algorithm=None,
        factory=factory,
        sources=[LocalSourceInfo(type="filesystem", path=path)],
        downloader_data={
            "type": "addon", "name": "my_addon", "version": "1.0.0"
        },
        item_label=ADDON_DIRNAME,
        progress_dir=target_dir,
    )


def _run(item):
    for result in item.distribute():
        if result:
            break
        time.sleep(0.01)


def test_target_appears_complete(tmp_path):
    """Other processes never see a partially filled target directory."""
    source_zip = _make_source_zip(tmp_path)
    item = _make_dist_item(tmp_path, source_zip)
    _CopyDownloader.delay = 0.2
    _CopyDownloader.fail = False
    stop = threading.Event()
    bad_states = []

    def watch():
        while not stop.is_set():
            if os.path.exists(item.target_dirpath):
                info = control._read_progress_file(item.target_dirpath)
                big_path = os.path.join(
                    item.target_dirpath, "my_addon", "big.bin"
                )
                if (
                    info.get("state") != DistFileStates.done.value
                    or not os.path.isfile(big_path)
                ):
                    bad_states.append(info)

    watcher = threading.Thread(target=watch)
    watcher.start()
    try:
        _run(item)
    finally:
        stop.set()
        watcher.join()

    assert item.state == UpdateState.UPDATED
    assert bad_states == []
    info = control._read_progress_file(item.target_dirpath)
    assert info["state"] == DistFileStates.done.value
    assert info["checksum"]


def test_unfinished_target_is_replaced(tmp_path):
    source_zip = _make_source_zip(tmp_path)
    item = _make_dist_item(tmp_path, source_zip)
    _CopyDownloader.delay = 0.0
    _CopyDownloader.fail = False
    # Leftover of distribution that was interrupted
    os.makedirs(os.path.join(item.target_dirpath, "my_addon"))
    with open(os.path.join(item.target_dirpath, "leftover.txt"), "w"):
        pass
    control._create_progress_file(
        item.target_dirpath, uuid.uuid4().hex, None, None
    )

    _run(item)

    assert item.state == UpdateState.UPDATED
    assert not os.path.exists(
        os.path.join(item.target_dirpath, "leftover.txt")
    )
    assert os.path.isfile(
        os.path.join(item.target_dirpath, "my_addon", "__init__.py")
    )


def test_target_published_by_other_process_is_kept(tmp_path):
    """Process that lost the race uses the other process' result."""
    source_zip = _make_source_zip(tmp_path)
    item = _make_dist_item(tmp_path, source_zip)
    other_dir = str(tmp_path / "other")
    os.makedirs(os.path.join(other_dir, "my_addon"))
    with open(os.path.join(other_dir, "my_addon", "other.py"), "w"):
        pass
    control._create_progress_file(
        other_dir, uuid.uuid4().hex, None, None, state=DistFileStates.done
    )
    os.makedirs(os.path.dirname(item.target_dirpath), exist_ok=True)

    published = []

    class _Downloader(_CopyDownloader):
        @classmethod
        def download(cls, *args, **kwargs):
            output = super().download(*args, **kwargs)
            # Other process publishes while this one downloads
            os.rename(other_dir, item.target_dirpath)
            published.append(True)
            return output

    item.factory.register_format(UrlType.FILESYSTEM, _Downloader)
    _run(item)

    assert published
    assert item.state == UpdateState.UPDATED
    assert os.path.isfile(
        os.path.join(item.target_dirpath, "my_addon", "other.py")
    )


def test_failed_distribution_keeps_target(tmp_path):
    source_zip = _make_source_zip(tmp_path)
    item = _make_dist_item(tmp_path, source_zip)
    _CopyDownloader.delay = 0.0
    _CopyDownloader.fail = True
    os.makedirs(item.target_dirpath)
    marker = os.path.join(item.target_dirpath, "in_use.txt")
    with open(marker, "w"):
        pass
    try:
        _run(item)
    finally:
        _CopyDownloader.fail = False

    assert item.state == UpdateState.UPDATE_FAILED
    assert os.path.exists(marker)


def test_cleanup_keeps_dirs_of_other_processes(tmp_path):
    temp_dir = str(tmp_path / ".unzip_temp")

    def make(name, expiration=None, age=None):
        path = os.path.join(temp_dir, name)
        os.makedirs(path)
        if expiration is not None:
            with open(
                os.path.join(path, control.DIST_EXPIRE_FILENAME), "w"
            ) as stream:
                json.dump({"expiration_time": expiration}, stream)
        if age is not None:
            mtime = time.time() - age
            os.utime(path, (mtime, mtime))
        return path

    in_progress = make("in_progress", expiration=time.time() + 3600)
    just_created = make("just_created")
    expired = make("expired", expiration=time.time() - 1)
    expired_int = make("expired_int", expiration=int(time.time()) - 1)
    old_unmarked = make("old_unmarked", age=2 * 24 * 60 * 60)

    control._cleanup_dist_expire_dirs(temp_dir)

    assert os.path.exists(in_progress)
    assert os.path.exists(just_created)
    assert not os.path.exists(expired)
    assert not os.path.exists(expired_int)
    assert not os.path.exists(old_unmarked)


def test_unzip_temp_dir_has_expire_file_during_extraction(tmp_path):
    source_zip = _make_source_zip(tmp_path)
    item = _make_dist_item(tmp_path, source_zip)
    seen = []

    class _Downloader(_CopyDownloader):
        @classmethod
        def unzip(cls, filepath, destination_dir):
            seen.append(control._dist_expire_file_expired(
                item.unzip_temp_dir
            ))
            super().unzip(filepath, destination_dir)

    item.factory.register_format(UrlType.FILESYSTEM, _Downloader)
    _run(item)
    assert item.state == UpdateState.UPDATED
    assert seen == [False]


def test_filesystem_source_is_not_removed(tmp_path):
    source_zip = _make_source_zip(tmp_path)
    item = _make_dist_item(tmp_path, source_zip, downloader=OSDownloader)
    _run(item)
    assert item.state == UpdateState.UPDATED
    assert os.path.exists(source_zip)


def test_metadata_updates_are_not_lost(tmp_path):
    addons_dir = str(tmp_path / "addons")
    distributions = [
        AYONDistribution(
            addon_dirpath=addons_dir,
            dependency_dirpath=str(tmp_path / "deps"),
            dist_factory=DownloadFactory(),
            skip_installer_dist=True,
        )
        for _ in range(8)
    ]

    def update(idx, distribution):
        for version in range(10):
            distribution.update_addons_metadata(
                {f"addon_{idx}": {f"1.0.{version}": {"checksum": "x"}}}
            )

    threads = [
        threading.Thread(target=update, args=(idx, distribution))
        for idx, distribution in enumerate(distributions)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    metadata = distributions[0].get_addons_metadata()
    assert sorted(metadata) == [f"addon_{idx}" for idx in range(8)]
    for versions in metadata.values():
        assert len(versions) == 10
