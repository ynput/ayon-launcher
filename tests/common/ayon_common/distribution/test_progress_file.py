"""Tests for progress file used as lock when storage is shared."""
import os
import sys
import json
import time
import uuid
import shutil
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

from ayon_common.distribution import control  # noqa: E402
from ayon_common.distribution.control import (  # noqa: E402
    DistFileStates,
    DistributionItem,
    DistributionProgressInterupted,
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


@pytest.fixture(autouse=True)
def fast_timing(monkeypatch):
    monkeypatch.setattr(control, "DIST_HEARTBEAT_INTERVAL", 0.05)
    monkeypatch.setattr(control, "DIST_POLL_INTERVAL", 0.02)


class _CountingDownloader(SourceDownloader):
    """Copies zip from 'filesystem' source slowly and counts downloads."""
    downloads = []
    delay = 1.0

    @classmethod
    def download(cls, source, destination_dir, data, transfer_progress):
        cls.downloads.append(destination_dir)
        time.sleep(cls.delay)
        os.makedirs(destination_dir, exist_ok=True)
        src_path = source["path"]["windows"]
        dst_path = os.path.join(destination_dir, os.path.basename(src_path))
        shutil.copyfile(src_path, dst_path)
        return dst_path

    @classmethod
    def cleanup(cls, source, destination_dir, data):
        pass


def _make_dist_item(tmp_path, target_dir) -> DistributionItem:
    source_zip = str(tmp_path / "client.zip")
    if not os.path.exists(source_zip):
        with zipfile.ZipFile(source_zip, "w") as zip_file:
            zip_file.writestr("my_addon/__init__.py", "VALUE = 1\n")

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


def _distribute(item):
    for result in item.distribute():
        if result:
            break
        time.sleep(0.02)


def _claim(item, timeout=30.0):
    """Wait for progress file, True if other process distributed item."""
    started = time.monotonic()
    for result in item._claim_progress_file():
        if result is not None:
            return result
        assert time.monotonic() - started < timeout, "Timed out"
        time.sleep(0.01)


def _write_old_launcher_file(target_dir, state="moving"):
    """Progress file as written by launchers without this change."""
    os.makedirs(target_dir, exist_ok=True)
    data = {
        "state": state,
        "progress_id": uuid.uuid4().hex,
        "checksum": None,
        "checksum_algorithm": None,
        "dist_started": "2026-01-01 00:00:00",
    }
    with open(os.path.join(target_dir, "dist_progress.json"), "w") as f:
        json.dump(data, f)


def _old_launcher_wait(progress_dir, threshold_time):
    """Copy of '_wait_for_other_process' from older launchers.

    Returns True when other process finished, False when it took over.
    """
    progress_path = os.path.join(progress_dir, "dist_progress.json")
    started = time.time()
    state = None
    while True:
        if not os.path.exists(progress_path):
            return False
        progress_info = control._read_progress_file(progress_dir)
        current_state = progress_info.get("state")
        if current_state is None:
            return False
        if current_state == "done":
            return True
        if current_state == "failed":
            return False
        if current_state != state:
            started = time.time()
            state = current_state
        if (time.time() - started) > threshold_time:
            return False
        time.sleep(0.01)


@pytest.mark.parametrize("workers", [2, 4])
def test_parallel_distribution_downloads_once(tmp_path, workers):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    _CountingDownloader.downloads = []
    items = [_make_dist_item(tmp_path, target_dir) for _ in range(workers)]

    threads = [
        threading.Thread(target=_distribute, args=(item, ))
        for item in items
    ]
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
    assert progress["state"] == DistFileStates.done.value


_CONTEND_SCRIPT = """
import sys, time
sys.path.insert(0, sys.argv[1])
from ayon_common.distribution import control

progress_dir, start_at = sys.argv[2:4]
time.sleep(max(0.0, float(start_at) - time.time()))
created = control._create_progress_file_exclusive(
    progress_dir, {"state": "moving"}
)
print("created" if created else "exists")
"""


def test_only_one_process_creates_progress_file(tmp_path):
    progress_dir = str(tmp_path / "item")
    # All processes try to create the file at the same moment
    start_at = str(time.time() + 3)
    processes = [
        subprocess.Popen(
            [
                sys.executable, "-c", _CONTEND_SCRIPT,
                COMMON_DIR, progress_dir, start_at,
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    outputs = [
        process.communicate(timeout=60)[0].strip()
        for process in processes
    ]
    assert sorted(outputs) == ["created"] + ["exists"] * 7


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


def test_heartbeat_changes_state_and_counter(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False
    try:
        seen_states = set()
        beats = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(seen_states) < 2:
            info = control._read_progress_file(target_dir)
            seen_states.add(info["state"])
            beats.append(info["heartbeat"])
            time.sleep(0.01)
    finally:
        item._set_progress_state(DistFileStates.done)

    assert seen_states == {"moving", "distributing"}
    assert max(beats) > 0
    info = control._read_progress_file(target_dir)
    assert info["state"] == "done"
    assert info["hostname"] and info["pid"] == os.getpid()


def test_old_launcher_waits_for_new_launcher(tmp_path):
    """Old launcher waits past its threshold while heartbeat runs."""
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False

    def finish_later():
        time.sleep(1.0)
        item._set_progress_state(DistFileStates.done)

    thread = threading.Thread(target=finish_later)
    thread.start()
    try:
        # Threshold is 20s in old launchers, heartbeat is scaled down
        #   in this test the same way
        assert _old_launcher_wait(target_dir, threshold_time=0.3) is True
    finally:
        thread.join()


def test_new_launcher_waits_for_old_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv(control.DIST_STALE_TIMEOUT_ENV, "10")
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    _write_old_launcher_file(target_dir)
    item = _make_dist_item(tmp_path, target_dir)

    def finish_later():
        time.sleep(0.5)
        _write_old_launcher_file(target_dir, state="done")

    thread = threading.Thread(target=finish_later)
    thread.start()
    try:
        assert _claim(item) is True
    finally:
        thread.join()


def test_stale_progress_file_is_taken_over(tmp_path, monkeypatch):
    monkeypatch.setenv(control.DIST_STALE_TIMEOUT_ENV, "0.3")
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    _write_old_launcher_file(target_dir)
    item = _make_dist_item(tmp_path, target_dir)

    started = time.monotonic()
    assert _claim(item) is False
    try:
        assert time.monotonic() - started >= 0.3
        assert item._owns_progress_file()
    finally:
        item._set_progress_state(DistFileStates.failed)


def test_failed_progress_file_is_taken_over_right_away(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    _write_old_launcher_file(target_dir, state="failed")
    item = _make_dist_item(tmp_path, target_dir)

    started = time.monotonic()
    assert _claim(item) is False
    try:
        assert time.monotonic() - started < 2
        assert item._owns_progress_file()
    finally:
        item._set_progress_state(DistFileStates.failed)


def test_progress_file_of_dead_local_process_is_taken_over(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    process = subprocess.Popen([sys.executable, "-c", "pass"])
    process.wait()
    info = control._get_progress_info(
        uuid.uuid4().hex, None, None, DistFileStates.moving
    )
    info["pid"] = process.pid
    assert control._create_progress_file_exclusive(target_dir, info)
    item = _make_dist_item(tmp_path, target_dir)

    started = time.monotonic()
    assert _claim(item) is False
    try:
        assert time.monotonic() - started < 2
    finally:
        item._set_progress_state(DistFileStates.failed)


def test_taken_over_progress_file_interrupts_owner(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False

    # Old launcher overwrites the file after its 20s threshold
    _write_old_launcher_file(target_dir)
    time.sleep(0.2)
    # Heartbeat did not write over the other process' file
    assert not item._owns_progress_file()
    with pytest.raises(DistributionProgressInterupted):
        item._set_progress_state(DistFileStates.done)


def test_failed_distribution_keeps_work_of_other_process(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False
    _write_old_launcher_file(target_dir)
    item._stop_heartbeat()

    item.state = UpdateState.UPDATE_FAILED
    item._post_distribute()

    assert os.path.isfile(os.path.join(target_dir, "dist_progress.json"))
