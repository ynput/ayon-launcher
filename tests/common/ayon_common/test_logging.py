"""Tests for structured logging in 'ayon_common.logging'.

Vector delivery is tested against a local HTTP stub, no Vector is needed.
"""
import importlib
import io
import json
import logging
import os
import queue
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import structlog

# 'ayon_common' is imported as top level package, same as in 'start.py'
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        ),
        "common",
    ),
)

import ayon_common.logging  # noqa: E402


@pytest.fixture
def logging_module(monkeypatch):
    """Freshly imported 'ayon_common.logging' with clean logging state.

    Environment variables are read on import, set them with 'monkeypatch'
    before calling the returned function.
    """
    root = logging.getLogger()
    orig_root_handlers = list(root.handlers)
    orig_root_level = root.level
    for key in (
        "AYON_LOG_LEVEL",
        "AYON_DEBUG",
        "AYON_LOG_FILE",
        "AYON_VECTOR_LOG_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    def _reset_structlog():
        structlog.reset_defaults()
        structlog.contextvars.clear_contextvars()

    def _load():
        _reset_structlog()
        module = importlib.reload(ayon_common.logging)
        module.configure_logging()
        return module

    yield _load

    for handler in list(root.handlers):
        if handler not in orig_root_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(orig_root_level)
    monkeypatch.undo()
    _reset_structlog()
    importlib.reload(ayon_common.logging)


class _ListHandler(logging.Handler):
    """Plain stdlib handler like the publish report handler."""

    def __init__(self):
        super().__init__()
        self.messages = []
        self.records = []

    def emit(self, record):
        self.records.append(record)
        self.messages.append(record.getMessage())


@pytest.fixture
def foreign_handler():
    handler = _ListHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    yield handler
    root.removeHandler(handler)


@pytest.mark.parametrize(
    "env, expected",
    [
        ({}, logging.INFO),
        ({"AYON_DEBUG": "1"}, logging.DEBUG),
        ({"AYON_LOG_LEVEL": "10"}, logging.DEBUG),
        ({"AYON_LOG_LEVEL": "warning"}, logging.WARNING),
        ({"AYON_LOG_LEVEL": "bogus", "AYON_DEBUG": "1"}, logging.DEBUG),
        ({"AYON_LOG_LEVEL": "0"}, logging.INFO),
        ({"AYON_DEBUG": "yes"}, logging.INFO),
    ],
)
def test_log_level_from_env(logging_module, monkeypatch, env, expected):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    logging_module()

    assert logging.getLogger().level == expected


def test_positional_arguments_are_formatted(logging_module, foreign_handler):
    logging_module()
    log = structlog.get_logger("ayon_common.tests.args")

    log.info("Loaded %s from %s", "asset", "disk")

    assert foreign_handler.messages == ["Loaded asset from disk"]


def test_foreign_handlers_get_plain_message(logging_module, foreign_handler):
    logging_module()
    log = structlog.get_logger("ayon_common.tests.foreign")

    log.info("Plain message", product="renderMain")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("Failed")

    assert foreign_handler.messages == ["Plain message", "Failed"]
    assert foreign_handler.records[1].exc_info[0] is ValueError


def test_console_formatter_ignores_mutated_record_msg(
    logging_module, foreign_handler
):
    """Other handlers may replace 'record.msg', e.g. pyblish does."""
    module = logging_module()
    log = structlog.get_logger("ayon_common.tests.mutated")
    handler = next(
        h for h in logging.getLogger().handlers
        if isinstance(h, module._StderrHandler)
    )

    log.info("Original", key="value")
    record = foreign_handler.records[0]
    record.msg = "Mutated"

    output = handler.format(record)
    assert "Original" in output
    assert "key" in output


def test_foreign_processor_formatter_formats_records(
    logging_module, foreign_handler
):
    """Other tools in the process may use plain 'ProcessorFormatter'."""
    logging_module()
    log = structlog.get_logger("ayon_common.tests.foreign_structlog")
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer()
    )

    log.info("Loaded %s", "asset")

    payload = json.loads(formatter.format(foreign_handler.records[0]))
    assert payload["event"] == "Loaded asset"


def test_session_id_in_records_of_all_threads(
    logging_module, monkeypatch, foreign_handler
):
    monkeypatch.setenv("AYON_SESSION_ID", "root-id:child")
    module = logging_module()
    log = structlog.get_logger("ayon_common.tests.session")

    log.info("Main thread")
    thread = threading.Thread(target=lambda: log.info("Other thread"))
    thread.start()
    thread.join()

    session_ids = [
        getattr(record, module._EVENT_DICT_ATTR)[2].get("session_id")
        for record in foreign_handler.records
    ]
    assert session_ids == ["root-id:child", "root-id:child"]


def test_console_hides_context_ids(logging_module, monkeypatch):
    monkeypatch.setenv("AYON_SESSION_ID", "session-value")
    logging_module()
    log = structlog.get_logger("ayon_common.tests.console_ids")
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    structlog.contextvars.bind_contextvars(
        trace_id="trace-value", span_id="span-value"
    )
    try:
        log.info("With ids", parent_span_id="parent-value")
    finally:
        structlog.contextvars.clear_contextvars()

    output = stream.getvalue()
    assert "With ids" in output
    for value in (
        "session-value", "trace-value", "span-value", "parent-value"
    ):
        assert value not in output


def test_console_handler_uses_current_stderr(logging_module, monkeypatch):
    logging_module()
    log = structlog.get_logger("ayon_common.tests.stderr")

    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    log.info("To replaced stderr")
    assert "To replaced stderr" in stream.getvalue()

    # GUI processes may not have stderr at all
    monkeypatch.setattr(sys, "stderr", None)
    log.info("No crash")


def test_log_file_per_process_and_cleanup(
    logging_module, monkeypatch, tmp_path
):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    old_file = logs_dir / "ayon_20200101-000000_1.ndjson"
    old_rotated = logs_dir / "ayon_20200101-000000_1.ndjson.2020-01-01"
    other_file = logs_dir / "other.txt"
    for path in (old_file, old_rotated, other_file):
        path.write_text("")
        old_time = time.time() - (3 * 24 * 60 * 60)
        os.utime(path, (old_time, old_time))

    monkeypatch.setenv("AYON_LOG_FILE", "1")
    monkeypatch.setenv("AYON_LOG_RETENTION_DAYS", "2")
    monkeypatch.setattr(
        "ayon_common.utils.get_launcher_local_dir",
        lambda *args, **kwargs: str(tmp_path.joinpath(*args)),
    )
    logging_module()
    structlog.get_logger("ayon_common.tests.file").info("To file")
    for handler in logging.getLogger().handlers:
        handler.flush()

    remaining = sorted(path.name for path in logs_dir.iterdir())
    assert "other.txt" in remaining
    assert old_file.name not in remaining
    assert old_rotated.name not in remaining
    own_files = [
        name for name in remaining
        if name.endswith(f"_{os.getpid()}.ndjson")
    ]
    assert len(own_files) == 1
    records = [
        json.loads(line)
        for line in (logs_dir / own_files[0]).read_text().splitlines()
    ]
    assert [r["event"] for r in records] == ["To file"]


def test_vector_queue_renders_in_logging_thread(logging_module):
    module = logging_module()
    log_queue = queue.Queue()
    handler = module._DroppingQueueHandler(log_queue)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processors=[structlog.processors.JSONRenderer()],
        )
    )
    logger = logging.getLogger("ayon_common.tests.vector_queue")
    logger.addHandler(handler)
    logger.propagate = False
    vector_logger = logging.getLogger(module._VECTOR_LOGGER_NAME)
    try:
        data = {"frame": 1}
        logger.warning("Data %s", data)
        # Mutation after logging must not change the queued record
        data["frame"] = 2
        # Vector delivery problems are not sent to Vector
        vector_logger.addHandler(handler)
        vector_logger.warning("Skipped")
    finally:
        logger.removeHandler(handler)
        vector_logger.removeHandler(handler)

    queued = [log_queue.get_nowait() for _ in range(log_queue.qsize())]
    assert len(queued) == 1
    assert json.loads(queued[0])["event"] == "Data {'frame': 1}"


def test_vector_queue_drops_when_full(logging_module):
    module = logging_module()
    log_queue = queue.Queue(maxsize=1)
    handler = module._DroppingQueueHandler(log_queue)
    logger = logging.getLogger("ayon_common.tests.vector_full")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        logger.warning("First")
        logger.warning("Dropped")
    finally:
        logger.removeHandler(handler)
    assert log_queue.qsize() == 1


class _StubVector:
    """Local HTTP endpoint collecting posted JSON bodies."""

    def __init__(self, status=200):
        self.bodies = []
        stub = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                stub.bodies.append(json.loads(self.rfile.read(length)))
                self.send_response(status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), _Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}/"
        threading.Thread(
            target=self._server.serve_forever, daemon=True
        ).start()

    def close(self):
        self._server.shutdown()
        self._server.server_close()


def test_vector_sender_sends_batches(logging_module):
    module = logging_module()
    stub = _StubVector()
    log_queue = queue.Queue()
    sender = module.VectorHTTPSender(
        stub.url, log_queue, batch_size=10, flush_interval=5.0
    )
    try:
        for idx in range(25):
            log_queue.put(json.dumps({"event": str(idx)}))
        sender.start()
        # Stop sends what remains in the queue without waiting for
        #   the flush interval.
        sender.stop()
    finally:
        stub.close()

    assert [len(body) for body in stub.bodies] == [10, 10, 5]
    events = [item["event"] for body in stub.bodies for item in body]
    assert events == [str(idx) for idx in range(25)]


def test_vector_sender_survives_failures(logging_module):
    """Failures open the circuit and never kill the sender thread."""
    module = logging_module()
    module._vector_warn_logger._interval = 0
    stub = _StubVector(status=400)
    log_queue = queue.Queue()
    sender = module.VectorHTTPSender(
        stub.url,
        log_queue,
        batch_size=1,
        flush_interval=0.01,
        failure_threshold=2,
        cooldown=60.0,
    )
    try:
        sender.start()
        for idx in range(5):
            log_queue.put(json.dumps({"event": str(idx)}))
        deadline = time.monotonic() + 5.0
        while not log_queue.empty() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(0.1)
        thread = sender._thread
        assert thread is not None and thread.is_alive()
    finally:
        sender.stop()
        stub.close()

    # Circuit opened after 2 failed requests, the rest was dropped
    assert len(stub.bodies) == 2


def test_rate_limited_logger_accepts_arguments(logging_module):
    module = logging_module()
    handler = _ListHandler()
    logger = logging.getLogger("ayon_common.tests.rate_limited")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        rate_limited = module._RateLimitedLogger(logger, interval=60.0)
        rate_limited.warning("Paused for %s seconds.", 30.0)
        rate_limited.warning("Suppressed %s", 1)
    finally:
        logger.removeHandler(handler)

    assert handler.messages == ["Paused for 30.0 seconds."]


def test_vector_sender_request_stop_does_not_wait(logging_module):
    module = logging_module()
    stub = _StubVector()
    log_queue = queue.Queue()
    sender = module.VectorHTTPSender(
        stub.url, log_queue, batch_size=10, flush_interval=5.0
    )
    try:
        for idx in range(5):
            log_queue.put(json.dumps({"event": str(idx)}))
        sender.start()
        thread = sender._thread
        sender.request_stop()
        # Queued records are sent in the background, then thread ends
        thread.join(5.0)
        assert not thread.is_alive()
        # 'stop' at exit does not wait for a finished thread
        start = time.monotonic()
        sender.stop()
        assert time.monotonic() - start < 1.0
    finally:
        stub.close()

    events = [item["event"] for body in stub.bodies for item in body]
    assert events == [str(idx) for idx in range(5)]


def test_release_logging_restores_logging(logging_module, monkeypatch):
    """'ayon_core' configures logging after launcher released it."""
    monkeypatch.setenv("AYON_LOG_LEVEL", "DEBUG")
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    orig_handlers = list(root.handlers)
    noisy_logger = logging.getLogger("urllib3")
    orig_noisy_level = noisy_logger.level

    module = logging_module()
    assert root.level == logging.DEBUG
    assert noisy_logger.level == logging.WARNING
    assert len(root.handlers) > len(orig_handlers)
    assert structlog.is_configured()

    module.release_logging()

    assert root.level == logging.WARNING
    assert noisy_logger.level == orig_noisy_level
    assert root.handlers == orig_handlers
    assert not structlog.is_configured()
    # Repeated release does nothing
    module.release_logging()
    assert root.handlers == orig_handlers


def test_release_logging_without_configuration(logging_module):
    """Nothing to release when logging was configured by other package."""
    module = logging_module()
    module.release_logging()
    root_handlers = list(logging.getLogger().handlers)

    structlog.configure()
    module.configure_logging()
    module.release_logging()

    assert logging.getLogger().handlers == root_handlers
    assert structlog.is_configured()
