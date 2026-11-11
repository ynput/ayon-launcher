"""Tests for progress file used as lock when storage is shared."""
import os
import sys
import json
import time
import uuid
import shutil
import zipfile
import threading
import collections

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


def _old_launcher_wait(progress_dir, threshold_time, poll_gap=0.01):
    """Decisions of '_wait_for_other_process' of launcher 1.6.3.

    Older launchers check the file only between their own blocking
    downloads, 'poll_gap' simulates that.

    Returns True when other process finished, False when it took over.
    """
    progress_path = os.path.join(progress_dir, "dist_progress.json")
    started = time.time()
    state = None
    while True:
        if not os.path.exists(progress_path):
            return False
        try:
            with open(progress_path, "r") as stream:
                progress_info = json.loads(stream.read())
        except Exception:
            progress_info = {}
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
        time.sleep(poll_gap)


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


def test_progress_file_is_never_read_partially(tmp_path):
    """Owner updates the file in place, readers always get valid JSON."""
    progress_dir = str(tmp_path / "item")
    progress_id = uuid.uuid4().hex
    info = control._get_progress_info(
        progress_id, None, None, control._get_moving_state(0)
    )
    assert control._create_progress_file_exclusive(progress_dir, info)
    progress_path = os.path.join(progress_dir, "dist_progress.json")
    stop = threading.Event()
    bad_reads = []

    def read_loop():
        while not stop.is_set():
            # Same as older launchers
            with open(progress_path, "r") as stream:
                content = stream.read()
            try:
                state = json.loads(content).get("state")
            except ValueError:
                state = None
            if state is None:
                bad_reads.append(content)

    readers = [threading.Thread(target=read_loop) for _ in range(4)]
    for reader in readers:
        reader.start()
    try:
        for idx in range(1, 500):
            state = control._get_moving_state(idx)
            assert control._update_own_progress_file(
                progress_dir, progress_id, lambda i: i.update(state=state)
            )
        # Shorter content is padded
        assert control._update_own_progress_file(
            progress_dir, progress_id, lambda i: i.update(state="failed")
        )
    finally:
        stop.set()
        for reader in readers:
            reader.join()
    assert bad_reads == []
    assert os.listdir(progress_dir) == [control.DIST_PROGRESS_FILENAME]
    assert control._read_progress_file(progress_dir)["state"] == "failed"
    # File of other process is not changed
    assert not control._update_own_progress_file(
        progress_dir, uuid.uuid4().hex, lambda i: i.update(state="done")
    )


def test_heartbeat_changes_state(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False
    try:
        seen_states = []
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and len(set(seen_states)) < 4:
            info = control._read_progress_file(target_dir)
            seen_states.append(info["state"])
            time.sleep(0.01)
    finally:
        item._set_progress_state(DistFileStates.done)

    # Every heartbeat writes new state, older launchers see a change
    assert len(set(seen_states)) >= 4
    assert all(state.startswith("moving ") for state in seen_states)
    info = control._read_progress_file(target_dir)
    assert info["state"] == "done"
    assert info["hostname"]


def test_claim_of_own_progress_file_does_not_wait(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False
    try:
        started = time.monotonic()
        assert _claim(item) is False
        assert time.monotonic() - started < 0.5
    finally:
        item._set_progress_state(DistFileStates.failed)


@pytest.mark.parametrize("poll_gap", [0.01, 1.2])
def test_old_launcher_waits_for_new_launcher(tmp_path, monkeypatch, poll_gap):
    """Old launcher waits past its threshold while heartbeat runs.

    Also when it checks the file less often than its threshold, because
    it downloads other items meanwhile.
    """
    # Real values 20s threshold and 5s heartbeat, scaled by 1/20
    monkeypatch.setattr(control, "DIST_HEARTBEAT_INTERVAL", 0.25)
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False

    def finish_later():
        time.sleep(3.0)
        item._set_progress_state(DistFileStates.done)

    thread = threading.Thread(target=finish_later)
    thread.start()
    try:
        assert _old_launcher_wait(
            target_dir, threshold_time=1.0, poll_gap=poll_gap
        ) is True
    finally:
        thread.join()


def test_new_launcher_waits_for_old_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "MOVE_WAIT_TRESHOLD_TIME", 10)
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
    monkeypatch.setattr(control, "MOVE_WAIT_TRESHOLD_TIME", 0.3)
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


def test_displaced_owner_waits_instead_of_publishing(tmp_path, monkeypatch):
    """Older launcher overwrites the file, e.g. both started at once."""
    monkeypatch.setattr(control, "MOVE_WAIT_TRESHOLD_TIME", 10)
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    init_path = os.path.join(target_dir, "my_addon", "__init__.py")
    _CountingDownloader.downloads = []
    item = _make_dist_item(tmp_path, target_dir)
    thread = threading.Thread(target=_distribute, args=(item, ))
    thread.start()
    try:
        # Old launcher takes over while this one downloads
        time.sleep(0.3)
        _write_old_launcher_file(target_dir)
        time.sleep(1.5)
        # Nothing was moved to target directory
        assert os.listdir(target_dir) == ["dist_progress.json"]
        # Old launcher finishes
        os.makedirs(os.path.dirname(init_path))
        with open(init_path, "w") as stream:
            stream.write("VALUE = 2\n")
        _write_old_launcher_file(target_dir, state="done")
    finally:
        thread.join(timeout=30)

    assert item.state == UpdateState.UPDATED
    with open(init_path, "r") as stream:
        assert stream.read() == "VALUE = 2\n"


def test_failed_distribution_releases_progress_file(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)

    class _FailingDownloader(_CountingDownloader):
        @classmethod
        def download(cls, *args, **kwargs):
            raise RuntimeError("Download failed")

    item.factory.register_format(UrlType.FILESYSTEM, _FailingDownloader)
    _distribute(item)
    assert item.state == UpdateState.UPDATE_FAILED
    assert not os.path.exists(target_dir)

    other = _make_dist_item(tmp_path, target_dir)
    started = time.monotonic()
    assert _claim(other) is False
    assert time.monotonic() - started < 0.5
    other._set_progress_state(DistFileStates.failed)


def test_items_finish_one_by_one(tmp_path):
    """Item is finished before the next item is downloaded."""
    targets = [
        str(tmp_path / "addons" / f"addon_{idx}_1.0.0") for idx in range(3)
    ]
    seen_states = []

    class _Downloader(_CountingDownloader):
        delay = 0.1

        @classmethod
        def download(cls, *args, **kwargs):
            # 'moving' without heartbeat counter
            seen_states.append([
                (control._read_progress_file(target).get("state") or " ")
                .split(" ")[0] or None
                for target in targets
            ])
            return super().download(*args, **kwargs)

    items = [_make_dist_item(tmp_path, target) for target in targets]
    for item in items:
        item.factory.register_format(UrlType.FILESYSTEM, _Downloader)

    # Same loop as 'AYONDistribution.distribute'
    running = collections.deque(item.distribute() for item in items)
    while running:
        generator = running.popleft()
        if not next(generator):
            running.append(generator)

    assert [item.state for item in items] == [UpdateState.UPDATED] * 3
    assert seen_states == [
        ["moving", None, None],
        ["done", "moving", None],
        ["done", "done", "moving"],
    ]


def test_claim_when_directory_was_removed(tmp_path, monkeypatch):
    """Failed owner removes the directory right before the file is created."""
    monkeypatch.setattr(control, "_makedirs_shared", lambda path: None)
    progress_dir = str(tmp_path / "removed")
    assert not control._create_progress_file_exclusive(
        progress_dir, {"state": "moving"}
    )


def test_autofix_does_not_mark_claimed_directory(tmp_path):
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    item = _make_dist_item(tmp_path, target_dir)
    assert _claim(item) is False
    try:
        # Directory of other process that just started is not distributed
        assert not control._has_dist_content(target_dir)
        # Autofix does not overwrite progress file of other process
        assert not control._create_progress_file(
            target_dir, uuid.uuid4().hex, None, None, DistFileStates.done
        )
        assert item._owns_progress_file()
    finally:
        item._set_progress_state(DistFileStates.failed)

    os.makedirs(os.path.join(target_dir, "my_addon"))
    assert control._has_dist_content(target_dir)


def test_max_wait_counts_from_owner_change(tmp_path, monkeypatch):
    """Live owner is taken over after max wait, each owner gets full time."""
    monkeypatch.setattr(control, "DIST_MAX_WAIT_TIME", 1.0)
    target_dir = str(tmp_path / "addons" / "my_addon_1.0.0")
    owner = _make_dist_item(tmp_path, target_dir)
    assert _claim(owner) is False
    waiters = [_make_dist_item(tmp_path, target_dir) for _ in range(2)]
    claims = [waiter._claim_progress_file() for waiter in waiters]
    claimed_at = {}
    started = time.monotonic()
    try:
        while len(claimed_at) < 2 and time.monotonic() - started < 10:
            for idx, claim in enumerate(claims):
                if idx not in claimed_at and next(claim) is False:
                    claimed_at[idx] = time.monotonic() - started
            time.sleep(0.01)
    finally:
        for item in [owner] + waiters:
            item._stop_heartbeat()

    first, second = sorted(claimed_at.values())
    assert first >= 1.0
    # Second waiter did not take over the fresh claim of the first one
    assert second - first >= 1.0
