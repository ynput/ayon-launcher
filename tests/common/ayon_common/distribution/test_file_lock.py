"""Tests for distribution lock used when storage is shared by machines."""
import os
import sys
import json
import time
import uuid
import shutil
import socket
import zipfile
import threading
import subprocess

import pytest

ROOT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )
)
COMMON_DIR = os.path.join(ROOT_DIR, "common")
# 'ayon_common' is imported as top level package, same as in 'start.py'
sys.path.insert(0, COMMON_DIR)

from ayon_common.distribution import file_lock  # noqa: E402
from ayon_common.distribution.file_lock import DistributionLock  # noqa: E402
from ayon_common.distribution import control  # noqa: E402
from ayon_common.distribution.control import (  # noqa: E402
    DistributionItem,
    UpdateState,
)
from ayon_common.distribution.downloaders import (  # noqa: E402
    DownloadFactory,
    SourceDownloader,
)
from ayon_common.distribution.data_structures import (  # noqa: E402
    LocalSourceInfo,
    MultiPlatformValue,
    UrlType,
)


def _lock_path(tmp_path) -> str:
    return str(tmp_path / ".dist_locks" / "item.lock")


def _write_foreign_lock(path: str, **kwargs):
    data = {
        "token": uuid.uuid4().hex,
        "hostname": "other-machine",
        "pid": 12345,
        "pid_namespace": None,
        "beat": 0,
        "time": 0,
    }
    data.update(kwargs)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as stream:
        json.dump(data, stream)


def test_lock_is_exclusive(tmp_path):
    path = _lock_path(tmp_path)
    first = DistributionLock(path, stale_timeout=60)
    second = DistributionLock(path, stale_timeout=60)
    assert first.try_acquire()
    try:
        assert not second.try_acquire()
    finally:
        first.release()

    assert not os.path.exists(path)
    assert second.try_acquire()
    second.release()


def test_waiter_gets_lock_after_release(tmp_path):
    path = _lock_path(tmp_path)
    owner = DistributionLock(path, stale_timeout=60)
    assert owner.try_acquire()
    timer = threading.Timer(0.5, owner.release)
    timer.start()

    waiter = DistributionLock(path, stale_timeout=60, poll_interval=0.05)
    started = time.monotonic()
    try:
        assert waiter.acquire(wait_timeout=10)
        assert time.monotonic() - started >= 0.4
    finally:
        timer.join()
        waiter.release()


def test_heartbeat_keeps_lock_alive(tmp_path):
    path = _lock_path(tmp_path)
    owner = DistributionLock(path, stale_timeout=0.8)
    assert owner.try_acquire()
    try:
        waiter = DistributionLock(path, stale_timeout=0.8, poll_interval=0.05)
        # Waits 3x longer than stale timeout but owner is alive
        assert waiter.acquire(wait_timeout=2.5) is False
        assert not waiter.owned
        assert not owner.lost
    finally:
        owner.release()
    assert not os.path.exists(path)


def test_stale_lock_is_taken_over(tmp_path):
    path = _lock_path(tmp_path)
    _write_foreign_lock(path)
    waiter = DistributionLock(path, stale_timeout=0.5, poll_interval=0.05)
    started = time.monotonic()
    try:
        assert waiter.acquire(wait_timeout=10)
        assert time.monotonic() - started >= 0.5
    finally:
        waiter.release()
    assert not os.path.exists(path)


def test_lock_of_dead_local_process_is_taken_over_immediately(tmp_path):
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    path = _lock_path(tmp_path)
    _write_foreign_lock(
        path,
        hostname=socket.gethostname(),
        pid=process.pid,
        pid_namespace=file_lock._get_pid_namespace(),
    )
    waiter = DistributionLock(path, stale_timeout=60)
    started = time.monotonic()
    try:
        assert waiter.acquire(wait_timeout=10)
        assert time.monotonic() - started < 5
    finally:
        waiter.release()


def test_lock_of_running_local_process_is_kept(tmp_path):
    path = _lock_path(tmp_path)
    _write_foreign_lock(
        path,
        hostname=socket.gethostname(),
        # Parent of pytest process is running
        pid=os.getppid(),
        pid_namespace=file_lock._get_pid_namespace(),
    )
    waiter = DistributionLock(path, stale_timeout=60, poll_interval=0.05)
    assert waiter.acquire(wait_timeout=0.5) is False
    assert os.path.exists(path)


def test_release_keeps_lock_taken_over_by_other_process(tmp_path):
    path = _lock_path(tmp_path)
    owner = DistributionLock(path, stale_timeout=0.4)
    assert owner.try_acquire()
    # Other process found the lock stale and took it over
    os.remove(path)
    _write_foreign_lock(path)
    time.sleep(0.3)
    assert owner.lost
    owner.release()
    assert os.path.exists(path)


def test_lock_env_values(monkeypatch):
    env_name = file_lock.LOCK_STALE_TIMEOUT_ENV
    monkeypatch.setenv(env_name, "30")
    assert file_lock.get_lock_stale_timeout() == 30
    for value in ("abc", "-1", "0"):
        monkeypatch.setenv(env_name, value)
        assert (
            file_lock.get_lock_stale_timeout()
            == file_lock.DEFAULT_LOCK_STALE_TIMEOUT
        )

    env_name = file_lock.LOCK_WAIT_TIMEOUT_ENV
    monkeypatch.setenv(env_name, "12.5")
    assert file_lock.get_lock_wait_timeout() == 12.5
    monkeypatch.delenv(env_name)
    assert (
        file_lock.get_lock_wait_timeout()
        == file_lock.DEFAULT_LOCK_WAIT_TIMEOUT
    )


_CONTEND_SCRIPT = """
import os, sys, time
sys.path.insert(0, sys.argv[1])
from ayon_common.distribution.file_lock import DistributionLock

lock_path, target, counter_path, start_at = sys.argv[2:6]
time.sleep(max(0.0, float(start_at) - time.time()))
lock = DistributionLock(lock_path, stale_timeout=30, poll_interval=0.05)
assert lock.acquire(wait_timeout=60)
try:
    if not os.path.exists(target):
        with open(counter_path, "a") as stream:
            stream.write("x")
        time.sleep(0.5)
        os.makedirs(target)
finally:
    lock.release()
"""


def test_many_processes_do_the_work_once(tmp_path):
    lock_path = _lock_path(tmp_path)
    target = str(tmp_path / "target")
    counter_path = str(tmp_path / "counter.txt")
    # All processes try to take the lock at the same moment
    start_at = str(time.time() + 3)
    processes = [
        subprocess.Popen([
            sys.executable, "-c", _CONTEND_SCRIPT,
            COMMON_DIR, lock_path, target, counter_path, start_at,
        ])
        for _ in range(8)
    ]
    codes = [process.wait(timeout=120) for process in processes]
    assert codes == [0] * 8
    with open(counter_path) as stream:
        assert stream.read() == "x"
    assert os.path.isdir(target)
    assert not os.path.exists(lock_path)


def test_progress_file_is_never_read_partially(tmp_path):
    progress_dir = str(tmp_path / "item")
    control._store_progress_file(progress_dir, {"state": "moving"})
    stop = threading.Event()
    bad_reads = []

    def read_loop():
        while not stop.is_set():
            info = control._read_progress_file(progress_dir)
            if "state" not in info:
                bad_reads.append(info)
            time.sleep(0.002)

    readers = [threading.Thread(target=read_loop) for _ in range(4)]
    for reader in readers:
        reader.start()
    try:
        for idx in range(200):
            control._store_progress_file(
                progress_dir,
                {"state": "moving", "idx": idx, "pad": "x" * 4000},
            )
    finally:
        stop.set()
        for reader in readers:
            reader.join()
    assert bad_reads == []
    leftovers = [
        name for name in os.listdir(progress_dir)
        if name != control.DIST_PROGRESS_FILENAME
    ]
    assert leftovers == []


class _CountingDownloader(SourceDownloader):
    """Copies zip from 'filesystem' source slowly and counts downloads."""
    downloads = []

    @classmethod
    def download(cls, source, destination_dir, data, transfer_progress):
        cls.downloads.append(destination_dir)
        time.sleep(1.0)
        os.makedirs(destination_dir, exist_ok=True)
        src_path = source["path"]["windows"]
        dst_path = os.path.join(destination_dir, os.path.basename(src_path))
        shutil.copyfile(src_path, dst_path)
        return dst_path

    @classmethod
    def cleanup(cls, source, destination_dir, data):
        pass


def _make_dist_item(tmp_path, source_zip, target_dir) -> DistributionItem:
    factory = DownloadFactory()
    factory.register_format(UrlType.FILESYSTEM, _CountingDownloader)
    path = MultiPlatformValue(
        windows=source_zip, linux=source_zip, darwin=source_zip
    )
    process_id = uuid.uuid4().hex
    return DistributionItem(
        target_dir,
        str(tmp_path / "addons" / ".unzip_temp" / process_id),
        download_dirpath=str(tmp_path / "downloads" / process_id),
        state=UpdateState.OUTDATED,
        checksum=None,
        checksum_algorithm=None,
        factory=factory,
        sources=[LocalSourceInfo(type="filesystem", path=path)],
        downloader_data={
            "type": "addon", "name": "my_addon", "version": "1.0.0"
        },
        item_label="my_addon_1.0.0",
        progress_dir=target_dir,
    )


@pytest.mark.parametrize("workers", [2, 4])
def test_parallel_distribution_downloads_once(tmp_path, workers):
    source_zip = str(tmp_path / "client.zip")
    with zipfile.ZipFile(source_zip, "w") as zip_file:
        zip_file.writestr("my_addon/__init__.py", "VALUE = 1\n")
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    _CountingDownloader.downloads = []

    items = [
        _make_dist_item(tmp_path, source_zip, target_dir)
        for _ in range(workers)
    ]

    def run(item):
        for result in item.distribute():
            if result:
                break
            time.sleep(0.02)

    threads = [threading.Thread(target=run, args=(item,)) for item in items]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert [item.state for item in items] == [UpdateState.UPDATED] * workers
    assert len(_CountingDownloader.downloads) == 1
    assert os.path.isfile(
        os.path.join(target_dir, "my_addon", "__init__.py")
    )
    progress = control._read_progress_file(target_dir)
    assert progress["state"] == control.DistFileStates.done.value
    lock_path = control._get_dist_lock_path(target_dir)
    assert not os.path.exists(lock_path)
