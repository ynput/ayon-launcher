"""Tests for structured logging in 'ayon_common.logging'.

Vector delivery is tested against a local HTTP stub, no Vector is needed.
"""
import importlib
import io
import json
import logging
import os
import queue
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from logging.handlers import TimedRotatingFileHandler

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

import ayon_common.logging


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
        "AYON_LOG_TO_FILE",
        "AYON_VECTOR_LOG_URL",
        "AYON_LOG_CONSOLE_TIME_FORMAT",
        "AYON_LOG_CONSOLE_STYLE",
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
        ({"AYON_LOG_LEVEL": "10"}, logging.DEBUG),
        ({"AYON_LOG_LEVEL": "warning"}, logging.WARNING),
        ({"AYON_LOG_LEVEL": "bogus"}, logging.INFO),
        ({"AYON_LOG_LEVEL": "0"}, logging.INFO),
        # Does not affect log level, see '--debug' of AYON launcher
        ({"AYON_DEBUG": "1"}, logging.INFO),
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


def test_disabled_level_is_not_processed(logging_module, foreign_handler):
    """Events of disabled level are dropped before processors run."""
    logging_module()
    processed = []

    def _record_method(logger, method_name, event_dict):
        processed.append(method_name)
        return event_dict

    structlog.get_config()["processors"].insert(0, _record_method)
    name = "ayon_common.tests.disabled"
    log = structlog.get_logger(name)

    log.debug("Disabled %s", "debug")
    log.log(logging.DEBUG, "Disabled log")
    # Arguments not matching the message are not formatted either
    log.debug("Data:", [1, 2])
    log.info("Enabled")

    assert processed == ["info"]
    assert foreign_handler.messages == ["Enabled"]

    # Level set on a single logger is respected
    logger = logging.getLogger(name)
    orig_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        log.debug("Enabled %s", "debug")
    finally:
        logger.setLevel(orig_level)

    assert processed == ["info", "debug"]
    assert foreign_handler.messages == ["Enabled", "Enabled debug"]


@pytest.mark.parametrize(
    "message, args, expected",
    [
        # Too few arguments
        ("Loaded %s from %s", ("asset",), "Loaded %s from %s 'asset'"),
        # Arguments passed like to 'print'
        ("Data:", ([1, 2],), "Data: [1, 2]"),
        # Wrong type of argument
        ("Version %d", ("v001",), "Version %d 'v001'"),
    ],
)
def test_mismatched_arguments_do_not_raise(
    logging_module, foreign_handler, message, args, expected
):
    """Logging must not break the caller, arguments are kept in message."""
    logging_module()
    log = structlog.get_logger("ayon_common.tests.bad_args")

    log.info(message, *args)

    assert foreign_handler.messages == [expected]


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
    logging_module, monkeypatch, foreign_handler
):
    """Other handlers may replace 'record.msg', e.g. pyblish does."""
    # Key values are shown only by structlog layout
    monkeypatch.setenv("AYON_LOG_CONSOLE_STYLE", "structlog")
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
    # Other key values are shown only by structlog layout
    monkeypatch.setenv("AYON_LOG_CONSOLE_STYLE", "structlog")
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


@pytest.mark.parametrize(
    "time_format, pattern",
    [
        (None, r"^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} "),
        ("%H:%M:%S.%f", r"^\d{2}:\d{2}:\d{2}\.\d{6} "),
    ],
)
def test_console_timestamp_format(
    logging_module, monkeypatch, foreign_handler, time_format, pattern
):
    if time_format is not None:
        monkeypatch.setenv("AYON_LOG_CONSOLE_TIME_FORMAT", time_format)
    module = logging_module()
    log = structlog.get_logger("ayon_common.tests.console_time")
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    log.info("Timed")
    logging.getLogger("ayon_common.tests.console_time_foreign").info("Foreign")

    lines = stream.getvalue().splitlines()
    assert len(lines) == 2
    for line in lines:
        assert re.match(pattern, line), line

    # JSON output keeps ISO timestamps
    json_formatter = module._EventDictProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    payload = json.loads(json_formatter.format(foreign_handler.records[0]))
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", payload["timestamp"]
    )


def test_console_level_colors(logging_module, monkeypatch):
    monkeypatch.setenv("AYON_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    logging_module()
    log = structlog.get_logger("ayon_common.tests.level_colors")
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    log.debug("Debug")
    log.info("Info")
    log.warning("Warning")
    log.error("Error")
    log.critical("Critical")

    lines = stream.getvalue().splitlines()
    for line, (level, color) in zip(lines, [
        ("debug", "245"),
        ("info", "33"),
        ("warning", "220"),
        ("error", "208"),
        ("critical", "196"),
    ]):
        # Level is followed by bold style of structlog
        assert re.search(
            rf"\[\x1b\[38;5;{color}m(\x1b\[1m)?{level}\x1b\[0m\]", line
        ), repr(line)


@pytest.mark.parametrize(
    "env, info, warning, logger_shown, key_values",
    [
        # Key values are never shown, logger name only with DEBUG level
        ({}, r"\[info\]", r"\[warning\]", False, ""),
        (
            {"AYON_LOG_LEVEL": "DEBUG"},
            r"\[info\]",
            r"\[warning\]",
            True,
            "",
        ),
        # Default structlog layout
        (
            {"AYON_LOG_CONSOLE_STYLE": "structlog"},
            r"\[info {5}\]",
            r"\[warning {2}\]",
            True,
            " key=1",
        ),
    ],
)
def test_console_layout(
    logging_module, monkeypatch, env, info, warning, logger_shown, key_values
):
    monkeypatch.setenv("NO_COLOR", "1")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    logging_module()
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    structlog.get_logger("ayon_common.tests.layout").info("Message", key=1)
    logging.getLogger("ayon_common.tests.layout_foreign").warning("Foreign")

    structlog_line, foreign_line = stream.getvalue().splitlines()
    structlog_logger = r" +\[ayon_common\.tests\.layout\]"
    foreign_logger = r" +\[ayon_common\.tests\.layout_foreign\]"
    if not logger_shown:
        structlog_logger = foreign_logger = ""
    assert re.search(
        rf"{info} Message{structlog_logger}{key_values}$",
        structlog_line,
    ), structlog_line
    assert re.search(
        rf"{warning} Foreign{foreign_logger}$",
        foreign_line,
    ), foreign_line


@pytest.mark.parametrize(
    "template, fields, expected",
    [
        ("Loaded {product}", {"product": "modelMain"}, "Loaded modelMain"),
        # Tokens without a field are kept
        ("Loaded {product} {missing}", {"product": "a"}, "Loaded a {missing}"),
        # Fields not used in the template are ignored
        ("Done", {"unused": 1}, "Done"),
        ("{version:03d}", {"version": 3}, "003"),
        # Value not matching format spec is rendered by 'str'
        ("{version:03d} {name}", {"version": "v3", "name": "a"}, "v3 a"),
        # Missing field is kept with its conversion and format spec
        ("{missing!r:>5} {name}", {"name": "a"}, "{missing!r:>5} a"),
        ("[{name:>5}][{name:<5}]", {"name": "ab"}, "[   ab][ab   ]"),
        ("{name!r} {name!s} {name!a}", {"name": "é"}, "'é' é '\\xe9'"),
        ("{{name}} {name}", {"name": "ab"}, "{name} ab"),
        # Only fields looked up by name are rendered
        (
            "{0} {} {name.upper} {data[key]} {name}",
            {"name": "ab", "data": {"key": 1}},
            "{0} {} {name.upper} {data[key]} ab",
        ),
        # Not valid format strings, kept as they are
        ("Unclosed {name", {"name": "ab"}, "Unclosed {name"),
        ("Single } {name}", {"name": "ab"}, "Single } {name}"),
        # Without fields escaped braces are kept
        ("{{literal}}", {}, "{{literal}}"),
    ],
)
def test_render_message_template(logging_module, template, fields, expected):
    module = logging_module()

    assert module.render_message_template(template, fields) == expected


def test_message_template(logging_module, monkeypatch, foreign_handler):
    """Message is rendered from template, JSON keeps the template."""
    monkeypatch.setenv("NO_COLOR", "1")
    module = logging_module()
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)
    log = structlog.get_logger("ayon_common.tests.template")

    log.info(
        "Published {product} v{version:03d} {missing}",
        product="modelMain",
        version=3,
    )
    # Not templates
    log.info("Plain {{braces}}")
    log.info("Loaded %s {product}", "a", product="b")

    assert foreign_handler.messages == [
        "Published modelMain v003 {missing}",
        "Plain {{braces}}",
        "Loaded a {product}",
    ]
    lines = stream.getvalue().splitlines()
    assert lines[0].endswith("[info] Published modelMain v003 {missing}")
    assert "message_template" not in stream.getvalue()

    json_formatter = module._EventDictProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    payloads = [
        json.loads(json_formatter.format(record))
        for record in foreign_handler.records
    ]
    assert payloads[0]["event"] == "Published modelMain v003 {missing}"
    assert payloads[0]["message_template"] == (
        "Published {product} v{version:03d} {missing}"
    )
    assert payloads[0]["product"] == "modelMain"
    assert payloads[0]["version"] == 3
    assert "message_template" not in payloads[1]
    assert "message_template" not in payloads[2]


def test_console_span_message_has_duration(
    logging_module, monkeypatch, foreign_handler
):
    """Console message of span contains duration, JSON event does not."""
    monkeypatch.setenv("NO_COLOR", "1")
    module = logging_module()
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stream)

    with module.log_span("tests.span", other="hidden-value"):
        pass

    output = stream.getvalue()
    assert re.search(r"\[info\] tests\.span \(duration \d+\.\d{2}s\)$", output)
    # Key values are hidden
    for value in ("hidden-value", "duration_ms", "status"):
        assert value not in output

    json_formatter = module._EventDictProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )
    span_record = next(
        record for record in foreign_handler.records
        if record.name == module.SPAN_LOGGER_NAME
    )
    payload = json.loads(json_formatter.format(span_record))
    assert payload["event"] == "tests.span"
    assert isinstance(payload["duration_ms"], float)


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, "ayon"),
        ("structlog", "structlog"),
        (" StructLog ", "structlog"),
        ("bogus", "ayon"),
    ],
)
def test_console_style_from_env(logging_module, monkeypatch, value, expected):
    module = logging_module()
    if value is not None:
        monkeypatch.setenv("AYON_LOG_CONSOLE_STYLE", value)

    assert module.get_console_style_from_env() == expected


def test_console_time_format_from_env(logging_module, monkeypatch):
    module = logging_module()

    assert (
        module.get_console_time_format_from_env()
        == module.DEFAULT_CONSOLE_TIME_FORMAT
    )
    monkeypatch.setenv("AYON_LOG_CONSOLE_TIME_FORMAT", "%H:%M")
    assert module.get_console_time_format_from_env() == "%H:%M"


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

    monkeypatch.setenv("AYON_LOG_TO_FILE", "1")
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


def test_log_file_failure_does_not_break_logging(
    logging_module, monkeypatch, tmp_path, foreign_handler
):
    not_a_dir = tmp_path / "not_a_dir"
    not_a_dir.write_text("")
    monkeypatch.setenv("AYON_LOG_TO_FILE", "1")
    monkeypatch.setattr(
        "ayon_common.utils.get_launcher_local_dir",
        lambda *args, **kwargs: str(not_a_dir.joinpath(*args)),
    )

    module = logging_module()
    structlog.get_logger("ayon_common.tests.file").info("Still logged")

    handler_types = [type(handler) for handler in logging.getLogger().handlers]
    assert TimedRotatingFileHandler not in handler_types
    assert module._StderrHandler in handler_types
    assert any(
        message.startswith("Failed to create AYON log file")
        for message in foreign_handler.messages
    )
    assert "Still logged" in foreign_handler.messages


def test_vector_failure_does_not_break_logging(
    logging_module, monkeypatch, foreign_handler
):
    monkeypatch.setenv("AYON_VECTOR_LOG_URL", "http://127.0.0.1:1/")

    def _raise(*args, **kwargs):
        raise RuntimeError("Can't create session")

    monkeypatch.setattr("requests.Session", _raise)

    module = logging_module()
    structlog.get_logger("ayon_common.tests.vector").info("Still logged")

    handler_types = [type(handler) for handler in logging.getLogger().handlers]
    assert module._DroppingQueueHandler not in handler_types
    assert module._logging_state.vector_sender is None
    assert any(
        message.startswith("Failed to start sending of logs to Vector")
        for message in foreign_handler.messages
    )
    assert "Still logged" in foreign_handler.messages


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


def test_vector_sender_does_not_retry_unreachable_endpoint(logging_module):
    """Each attempt to connect waits for the timeout again."""
    module = logging_module()
    url = "http://127.0.0.1:1/"
    sender = module.VectorHTTPSender(url, queue.Queue())

    retries = sender._session.get_adapter(url).max_retries

    assert retries.connect == 0
    assert retries.read == 0
    # Temporary error responses of reachable endpoint are still retried
    assert retries.total == 2
    assert 503 in retries.status_forcelist


def test_vector_sender_stop_gives_up_after_failed_request(
    logging_module, monkeypatch
):
    """Unreachable endpoint must not delay exit of the process."""
    module = logging_module()
    log_queue = queue.Queue()
    sender = module.VectorHTTPSender(
        "http://127.0.0.1:1/",
        log_queue,
        batch_size=1,
        flush_interval=5.0,
        failure_threshold=100,
    )
    request_started = threading.Event()
    release_request = threading.Event()
    requests_count = []

    def _post(*args, **kwargs):
        requests_count.append(1)
        request_started.set()
        release_request.wait(5.0)
        raise ConnectionError("Endpoint is unreachable")

    monkeypatch.setattr(sender._session, "post", _post)
    for idx in range(5):
        log_queue.put(json.dumps({"event": str(idx)}))
    sender.start()
    assert request_started.wait(5.0)

    # 'stop' is called on exit while the first request is in progress
    stop_thread = threading.Thread(target=sender.stop)
    stop_thread.start()
    deadline = time.monotonic() + 5.0
    while not sender._stopping and time.monotonic() < deadline:
        time.sleep(0.01)
    release_request.set()
    stop_thread.join(5.0)

    assert not stop_thread.is_alive()
    # Remaining 4 batches were dropped without a request
    assert len(requests_count) == 1
    assert log_queue.empty()


def test_rate_limited_logger_accepts_arguments(logging_module, monkeypatch):
    module = logging_module()
    # Monotonic clock shortly after boot, e.g. on a fresh CI machine
    monkeypatch.setattr(module.time, "monotonic", lambda: 5.0)
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


def _span_events(module, handler):
    return [
        getattr(record, module._EVENT_DICT_ATTR)[2]
        for record in handler.records
        if record.name == module.SPAN_LOGGER_NAME
    ]


def test_log_span_nesting(logging_module, foreign_handler):
    module = logging_module()
    log = structlog.get_logger("ayon_common.tests.span")

    with module.log_span("tests.outer", key="value") as outer:
        with module.log_span("tests.inner") as inner:
            log.info("Inside")

    inside = getattr(foreign_handler.records[0], module._EVENT_DICT_ATTR)[2]
    assert inside["trace_id"] == outer.trace_id
    assert inside["span_id"] == inner.span_id

    inner_event, outer_event = _span_events(module, foreign_handler)
    assert inner_event["event"] == "tests.inner"
    assert inner_event["trace_id"] == outer.trace_id
    assert inner_event["parent_span_id"] == outer.span_id
    assert outer_event["event"] == "tests.outer"
    assert outer_event["key"] == "value"
    assert outer_event["status"] == "ok"
    assert "parent_span_id" not in outer_event
    assert isinstance(outer_event["duration_ms"], float)

    # Ids are not bound once spans ended
    log.info("Outside")
    outside = getattr(foreign_handler.records[-1], module._EVENT_DICT_ATTR)[2]
    assert "trace_id" not in outside


def test_log_span_finish_before_end(logging_module, foreign_handler):
    """Span can end before its block, e.g. before logging is released."""
    module = logging_module()
    start = time.perf_counter() - 1.0

    with pytest.raises(SystemExit):
        with module.log_span("tests.root", start=start) as span:
            span.set(mode="cli")
            span.finish()
            sys.exit(1)

    (event,) = _span_events(module, foreign_handler)
    assert event["status"] == "ok"
    assert event["mode"] == "cli"
    assert event["duration_ms"] >= 1000


def test_log_span_finish_ends_nested_spans(logging_module, foreign_handler):
    """Nested spans still open end before the finished span."""
    module = logging_module()
    log = structlog.get_logger("ayon_common.tests.span_nested")

    with pytest.raises(SystemExit):
        with module.log_span("tests.root") as root:
            with module.log_span("tests.outer") as outer:
                with module.log_span("tests.inner"):
                    root.finish()
                    log.info("After finish")
                    sys.exit(3)

    events = _span_events(module, foreign_handler)
    assert [event["event"] for event in events] == [
        "tests.inner", "tests.outer", "tests.root"
    ]
    assert [event["status"] for event in events] == ["ok", "ok", "ok"]
    assert events[0]["parent_span_id"] == outer.span_id
    assert events[1]["parent_span_id"] == root.span_id
    # Context of finished spans is not bound anymore
    after = next(
        getattr(record, module._EVENT_DICT_ATTR)[2]
        for record in foreign_handler.records
        if record.getMessage() == "After finish"
    )
    assert "trace_id" not in after


@pytest.mark.parametrize(
    "exception, status, extra",
    [
        (SystemExit(0), "ok", {"exit_code": 0}),
        (SystemExit(None), "ok", {"exit_code": 0}),
        (SystemExit(2), "error", {"exit_code": 2}),
        (SystemExit("Failed"), "error", {"exit_code": 1}),
        (ValueError("boom"), "error", {"error_type": "ValueError"}),
    ],
)
def test_log_span_status(
    logging_module, foreign_handler, exception, status, extra
):
    module = logging_module()

    with pytest.raises(type(exception)):
        with module.log_span("tests.status"):
            raise exception

    (event,) = _span_events(module, foreign_handler)
    assert event["status"] == status
    for key, value in extra.items():
        assert event[key] == value


class _BrokenStream:
    """Stream which fails on every write, like some host streams do."""

    def write(self, _text):
        raise SystemError("<built-in function write> returned a result")

    def flush(self):
        pass


def test_console_does_not_raise_on_broken_stream(logging_module, monkeypatch):
    """A failing stream must not break the code that is logging."""
    logging_module()
    log = structlog.get_logger("ayon_common.tests.broken_stream")

    stream = _BrokenStream()
    # Standard streams are replaced too, so neither printing nor the
    # 'handleError' report to 'sys.stderr' can succeed.
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)

    log.info("message %s", "value")
    try:
        raise ValueError("boom")
    except ValueError:
        log.exception("failed")
