"""Tests for distribution into a storage folder shared by processes."""
import os
import sys
import json
import time
import uuid
import shutil
import zipfile
import threading

import pytest

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


def test_cleanup_keeps_dirs_of_other_processes(tmp_path):
    temp_dir = str(tmp_path / ".unzip_temp")

    def make(name, expiration=None, age=None):
        path = os.path.join(temp_dir, name)
        os.makedirs(path)
        if expiration is not None:
            with open(
                os.path.join(path, "download_info.json"), "w"
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


def test_metadata_file_is_never_read_partially(tmp_path):
    filepath = str(tmp_path / "addons" / "addons.json")
    data = {f"addon_{idx}": {"1.0.0": {"pad": "x" * 200}} for idx in range(50)}
    AYONDistribution.save_metadata_file(filepath, data)
    stop = threading.Event()
    bad_reads = []

    def read_loop():
        while not stop.is_set():
            if AYONDistribution.read_metadata_file(filepath, None) != data:
                bad_reads.append(1)
            time.sleep(0.001)

    readers = [threading.Thread(target=read_loop) for _ in range(4)]
    for reader in readers:
        reader.start()
    try:
        for _ in range(200):
            AYONDistribution.save_metadata_file(filepath, data)
    finally:
        stop.set()
        for reader in readers:
            reader.join()
    assert bad_reads == []
    assert os.listdir(os.path.dirname(filepath)) == ["addons.json"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions")
def test_shared_dirs_are_writable_by_other_users(tmp_path):
    old_umask = os.umask(0o022)
    try:
        filepath = str(tmp_path / "addons" / "addons.json")
        AYONDistribution.save_metadata_file(filepath, {})

        source_zip = _make_source_zip(tmp_path)
        item = _make_dist_item(tmp_path, source_zip)
        # Like dependency packages, the parent does not exist yet
        item.unzip_temp_dir = str(tmp_path / "deps" / "x")
        _run(item)
    finally:
        os.umask(old_umask)

    assert item.state == UpdateState.UPDATED
    for path in (
        tmp_path / "addons",
        tmp_path / "deps",
        tmp_path / "addons" / ADDON_DIRNAME,
    ):
        assert os.stat(path).st_mode & 0o777 == 0o777, path
