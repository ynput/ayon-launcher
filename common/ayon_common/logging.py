"""Logging setup for AYON common package.

Three opt-in observability levels are supported, additive to each other:
    1. Console (default) - human readable output to stderr. Always on.
    2. NDJSON file - one JSON object per line, written to a local log
        file with retention. Enabled with 'AYON_LOG_FILE=1'.
    3. Vector - forward JSON logs to a Vector HTTP source. Enabled by
        setting 'AYON_VECTOR_LOG_URL'.
"""
import atexit
import datetime
import functools
import logging
import os
import queue
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from logging.handlers import QueueHandler, TimedRotatingFileHandler
from typing import Any, TextIO

import requests
import requests.adapters
import structlog
import urllib3.util

from ayon_common.utils import IS_BUILT_APPLICATION, get_launcher_local_dir

VECTOR_LOG_URL = os.getenv("AYON_VECTOR_LOG_URL")
LOG_FILE_ENABLED = os.getenv("AYON_LOG_FILE") == "1"
try:
    LOG_FILE_RETENTION_DAYS = max(
        1, int(os.getenv("AYON_LOG_RETENTION_DAYS", "1"))
    )
except ValueError:
    LOG_FILE_RETENTION_DAYS = 1
# Each process writes its own file, see '_get_log_file_path'
LOG_FILE_PREFIX = "ayon_"
LOG_FILE_EXT = ".ndjson"

# Max records buffered for Vector delivery. Beyond this, new records are
# dropped rather than growing memory unbounded during an outage.
VECTOR_QUEUE_MAX_SIZE = 10_000
# Max records sent to Vector in one request.
VECTOR_BATCH_SIZE = 500
# Max seconds a record waits for more records to be batched with it.
VECTOR_FLUSH_INTERVAL = 1.0
# Consecutive send failures after which the circuit opens (stop trying
# HTTP calls for a while, just drop records fast).
VECTOR_FAILURE_THRESHOLD = 5
# How long the circuit stays open once tripped.
VECTOR_CIRCUIT_COOLDOWN = 30.0
# Minimum time between "records are being dropped" warnings, to avoid
# flooding the console/log file during a prolonged outage.
VECTOR_WARN_INTERVAL = 30.0
# Logger for problems of Vector delivery. Its records are not sent to
# Vector, see '_DroppingQueueHandler'.
_VECTOR_LOGGER_NAME = "ayon.vector_log"

# Record attribute holding the structlog logger, method name and event
#   dict, see '_render_for_stdlib' and '_EventDictProcessorFormatter'.
# - must not be '_logger' and '_name' used by 'wrap_for_formatter', plain
#   'ProcessorFormatter' would expect the event dict in 'record.msg'
_EVENT_DICT_ATTR = "_ayon_event_dict"


def get_log_level_from_env() -> int:
    """Resolve the AYON log level from environment variables.

    'AYON_LOG_LEVEL' has precedence and accepts a numeric ('10') or
    a named ('DEBUG') level. When it is not set, or is invalid,
    'AYON_DEBUG' greater than 0 enables DEBUG. Defaults to INFO.

    Returns:
        int: Log level.

    """
    log_level = os.getenv("AYON_LOG_LEVEL", "").strip()
    if log_level:
        if log_level.isdigit():
            level = int(log_level)
        else:
            level = logging.getLevelNamesMapping().get(log_level.upper(), 0)
        if level > 0:
            return level

    try:
        if int(os.getenv("AYON_DEBUG", "0")) > 0:
            return logging.DEBUG
    except ValueError:
        pass
    return logging.INFO


def _render_for_stdlib(
        logger: logging.Logger,
        method_name: str,
        event_dict: dict) -> tuple[tuple[str], dict[str, Any]]:
    """Last structlog processor handing the event over to stdlib logging.

    Unlike 'ProcessorFormatter.wrap_for_formatter', which stores the event
    dict in 'record.msg', the record keeps a plain string message. Handlers
    not using these formatters (e.g. 'ayon_core' publish report, pyblish)
    show the message instead of a dict repr. The event dict is attached
    to the record for '_EventDictProcessorFormatter'.

    Args:
        logger (logging.Logger): The logger instance.
        method_name (str): The logging method name (e.g., 'info', 'error').
        event_dict (dict): The structlog event dictionary.

    Returns:
        tuple[tuple[str], dict[str, Any]]: Arguments and keyword arguments
        for the stdlib logger.

    """
    kwargs: dict[str, Any] = {
        "extra": {
            _EVENT_DICT_ATTR: (logger, method_name, event_dict),
        }
    }
    exc_info = event_dict.get("exc_info")
    if exc_info:
        # Let foreign handlers show the traceback too
        kwargs["exc_info"] = exc_info
    return (str(event_dict.get("event", "")),), kwargs


class _EventDictProcessorFormatter(structlog.stdlib.ProcessorFormatter):
    """ProcessorFormatter reading the event dict from the record.

    Counterpart of '_render_for_stdlib'. Other handlers may modify
    'record.msg' (pyblish does), the event dict is not affected.
    Records from 'wrap_for_formatter' and foreign stdlib records are
    processed as by 'ProcessorFormatter'.
    """

    def format(self, record: logging.LogRecord) -> str:
        structlog_data = getattr(record, _EVENT_DICT_ATTR, None)
        if structlog_data is not None:
            logger, method_name, event_dict = structlog_data
            # Attributes are set only on the copy, see '_EVENT_DICT_ATTR'
            record = logging.makeLogRecord(record.__dict__)
            record._logger = logger
            record._name = method_name
            record.msg = event_dict
            record.args = ()
        return super().format(record)


def _get_log_file_path(log_dir: str) -> str:
    """Log file path unique for the current process.

    Multiple AYON processes (tray, hosts, publish jobs) log at the same
    time. They must not share one file: writes would interleave and
    rotation of a shared file fails on Windows when another process has
    the file open.
    """
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(
        log_dir,
        f"{LOG_FILE_PREFIX}{timestamp}_{os.getpid()}{LOG_FILE_EXT}"
    )


def _remove_old_log_files(log_dir: str, retention_days: int) -> None:
    """Remove AYON log files not modified within retention period.

    Includes files of other processes, and rotated files of this one.
    """
    threshold = time.time() - (retention_days * 24 * 60 * 60)
    try:
        filenames = os.listdir(log_dir)
    except OSError:
        return
    for filename in filenames:
        if (
            not filename.startswith(LOG_FILE_PREFIX)
            or LOG_FILE_EXT not in filename
        ):
            continue
        path = os.path.join(log_dir, filename)
        try:
            if os.path.getmtime(path) < threshold:
                os.remove(path)
        except OSError:
            # Removed meanwhile or still open by other process on Windows
            pass


class _RateLimitedLogger:
    """Log a warning at most once per 'interval' seconds.

    Used in logging to vector to prevent flooding the log
    with repeated warnings when there is vector delivery failure.

    """
    def __init__(self, logger: logging.Logger, interval: float):
        self._logger = logger
        self._interval = interval
        self._last_emit = 0.0

    def warning(self, msg: str, *args: Any) -> None:
        """Log a warning message if the rate limit allows.

        Args:
            msg (str): The warning message.
            *args (Any): Positional arguments for the log message.

        Returns:
            None

        """
        now = time.monotonic()
        if now - self._last_emit < self._interval:
            return
        self._last_emit = now
        # Only positional arguments - the wrapped logger is a plain
        #   stdlib logger which raises 'TypeError' on unknown kwargs.
        self._logger.warning(msg, *args)


_vector_warn_logger = _RateLimitedLogger(
    logging.getLogger(_VECTOR_LOGGER_NAME), VECTOR_WARN_INTERVAL
)


class _DroppingQueueHandler(QueueHandler):
    """QueueHandler rendering records for Vector, dropping on overflow.

    Records are rendered with the handler's formatter in the logging
    thread and the resulting JSON string is queued. Rendering in the
    sender thread instead would race with other handlers mutating the
    shared record (e.g. pyblish's 'MessageHandler' replaces 'record.msg')
    and with later changes of mutable log arguments.

    Records about Vector delivery itself are not queued, they would only
    add load to an endpoint that is already failing.
    """

    def __init__(self, log_queue: queue.Queue):
        super().__init__(log_queue)
        self.addFilter(lambda record: record.name != _VECTOR_LOGGER_NAME)

    def prepare(self, record: logging.LogRecord) -> str:
        return self.format(record)

    def enqueue(self, record: logging.LogRecord) -> None:
        # Base implementation already uses 'put_nowait', but does not
        # handle a bounded queue being full - drop the record instead of
        # raising, so a Vector outage cannot backpressure the app or
        # grow memory without bound.
        try:
            self.queue.put_nowait(record)
        except queue.Full:
            _vector_warn_logger.warning(
                "Vector log queue is full, dropping log records."
            )


class VectorHTTPSender:
    """Send rendered log records from a queue to a Vector HTTP source.

    This is here so we can use Vector for log aggregation
    earlier before ayon-core and ayon-vector are started.

    A daemon thread collects up to 'batch_size' records, or what arrived
    within 'flush_interval' seconds, and sends them as one JSON array per
    request. Vector's 'json' decoding creates one event per array item.

    A circuit breaker stops sending for 'cooldown' seconds after
    'failure_threshold' consecutive failed requests. Records are dropped
    meanwhile so a dead endpoint cannot slow down the process.
    """

    _stop_sentinel = object()

    def __init__(
        self,
        url: str,
        log_queue: queue.Queue[str | None],
        batch_size: int = VECTOR_BATCH_SIZE,
        flush_interval: float = VECTOR_FLUSH_INTERVAL,
        failure_threshold: int = VECTOR_FAILURE_THRESHOLD,
        cooldown: float = VECTOR_CIRCUIT_COOLDOWN,
    ):
        self._url = url
        self._queue = log_queue
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        self._thread: threading.Thread | None = None
        # Reuse a single session so repeated POSTs reuse pooled
        # connections instead of opening a new one per request.
        self._session = requests.Session()
        retry = urllib3.util.Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=(502, 503, 504),
            allowed_methods=("POST",),
        )
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1, pool_maxsize=1, max_retries=retry
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="AYONVectorSender", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Send records remaining in the queue and stop the thread."""
        if self._thread is None:
            return
        # Thread may already be finished, see 'request_stop'
        if self._thread.is_alive():
            try:
                self._queue.put(None, timeout=timeout)
            except queue.Full:
                pass
            self._thread.join(timeout)
        self._thread = None
        self._session.close()

    def request_stop(self) -> None:
        """Stop the thread once records in the queue are sent.

        Does not wait for the thread. 'stop' registered at exit still
        waits for records which were not sent yet.
        """
        if self._thread is None:
            return
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            # Thread runs until exit, 'stop' handles it
            pass

    def _run(self) -> None:
        stop = False
        while not stop:
            item = self._queue.get()
            if item is None:
                break
            batch = [item]
            deadline = time.monotonic() + self._flush_interval
            while len(batch) < self._batch_size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    item = self._queue.get(timeout=remaining)
                except queue.Empty:
                    break
                if item is None:
                    stop = True
                    break
                batch.append(item)
            self._send(batch)

    def _send(self, batch: list[str]) -> None:
        now = time.monotonic()
        if now < self._circuit_open_until:
            # Circuit is open - skip the HTTP attempt entirely so a dead
            # Vector endpoint cannot slow down the sender thread.
            return
        try:
            response = self._session.post(
                self._url,
                data="[{}]".format(",".join(batch)).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                # (connect timeout, read timeout) - a slow-but-alive
                # endpoint should not stall as long as a dead one.
                timeout=(0.3, 2.0),
            )
            response.raise_for_status()
        except Exception:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._circuit_open_until = now + self._cooldown
                self._consecutive_failures = 0
                _vector_warn_logger.warning(
                    "Vector endpoint unreachable, pausing log delivery"
                    " for %s seconds.",
                    self._cooldown,
                )
            else:
                # Rate-limit warnings in case of Vector outage.
                _vector_warn_logger.warning(
                    "Failed to send %s log records to Vector.", len(batch)
                )
        else:
            self._consecutive_failures = 0


def _get_console_exception_formatter(
        colors: bool) -> structlog.types.ExceptionRenderer:
    """Exception formatter for console output.

    Rich tracebacks are used only when running from sources. Builds use
    plain tracebacks. Locals are never shown, they may hold large or
    sensitive values (e.g. credentials).

    Args:
        colors (bool): Console output uses colors.

    Returns:
        structlog.types.ExceptionRenderer: Exception formatter.

    """
    if not IS_BUILT_APPLICATION:
        try:
            import rich  # noqa: F401
        except ImportError:
            pass
        else:
            return structlog.dev.RichTracebackFormatter(
                color_system="truecolor" if colors else None,  # ty: ignore[invalid-argument-type]
                show_locals=False,
            )
    return structlog.dev.plain_traceback


class _ConsoleRenderer(structlog.dev.ConsoleRenderer):
    """ConsoleRenderer not initializing colorama on Windows.

    'colorama.init()' replaces 'sys.stdout' and 'sys.stderr' of the whole
    process, which breaks processes redirecting them. Whether the stream
    supports colors is resolved by '_StderrHandler' instead.
    """

    @classmethod
    def get_default_column_styles(cls, colors, force_colors=False):
        if colors:
            return structlog.dev._colorful_styles
        return structlog.dev._plain_styles


# Console mode flag enabling ANSI escape sequences on Windows
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


@functools.lru_cache(maxsize=None)
def _enable_windows_ansi(fileno: int) -> bool:
    """Enable ANSI escape sequences in Windows console of 'fileno'.

    Returns:
        bool: The console supports ANSI escape sequences.

    """
    try:
        import ctypes
        import msvcrt

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = msvcrt.get_osfhandle(fileno)  # type: ignore[attr-defined]
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(kernel32.SetConsoleMode(
            handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
        ))
    except Exception:  # noqa: BLE001
        return False


def _stream_supports_colors(stream: TextIO) -> bool:
    """Stream is a terminal able to show ANSI colors.

    'NO_COLOR' and 'FORCE_COLOR' environment variables have precedence,
    see https://no-color.org and https://force-color.org.
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    try:
        if not stream.isatty():
            return False
        if sys.platform == "win32":
            return _enable_windows_ansi(stream.fileno())
    except (AttributeError, ValueError, OSError):
        # Replaced streams may not implement 'isatty' or 'fileno'
        return False
    return os.environ.get("TERM") != "dumb"


class _StderrHandler(logging.StreamHandler):
    """StreamHandler writing to the current 'sys.stderr'.

    AYON tools replace 'sys.stderr' after logging is configured.
    'logging.StreamHandler' would keep writing to the stream it received
    on creation. Same approach as stdlib 'logging._StderrHandler'.

    Logs go to stderr so stdout of AYON launcher commands stays usable
    for their output.

    Records are formatted with 'color_formatter' when the current stream
    supports colors, otherwise with the handler's formatter.
    """

    def __init__(
        self,
        level: int = logging.NOTSET,
        color_formatter: logging.Formatter | None = None,
    ):
        logging.Handler.__init__(self, level)
        self.color_formatter = color_formatter

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    def format(self, record: logging.LogRecord) -> str:
        if (
            self.color_formatter is not None
            and _stream_supports_colors(sys.stderr)
        ):
            return self.color_formatter.format(record)
        return super().format(record)

    def emit(self, record: logging.LogRecord) -> None:
        stream = sys.stderr
        # 'sys.stderr' is None in GUI processes without console
        if stream is None:
            return
        try:
            msg = self.format(record) + self.terminator
            try:
                stream.write(msg)
            except UnicodeEncodeError:
                # Stream encoding can't represent some characters, e.g.
                #   non-latin names on a 'cp1252' Windows console.
                encoding = getattr(stream, "encoding", None) or "ascii"
                stream.write(
                    msg.encode(encoding, "backslashreplace").decode(encoding)
                )
            self.flush()
        except RecursionError:
            raise
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def formatTime(  # noqa: N802
            self,
            record: logging.LogRecord,
            datefmt: str | None = None) -> str:
        return (
            datetime.datetime.fromtimestamp(record.created)
            .astimezone(datetime.timezone.utc)
            .isoformat(timespec="milliseconds")
        )


@dataclass
class _LoggingState:
    """What 'configure_logging' changed, to undo it in 'release_logging'."""

    root_level: int
    handlers: list[logging.Handler] = field(default_factory=list)
    logger_levels: dict[str, int] = field(default_factory=dict)
    vector_sender: VectorHTTPSender | None = None


_logging_state: _LoggingState | None = None


def configure_logging() -> None:
    """Set up logging for AYON common package.

    Sets up structlog with a console renderer
    and a JSON renderer for sending logs to Vector.

    Safe to call multiple times, and safe even if another package (e.g.
    'ayon_core') configures logging first - only the first call in the
    process has any effect, to avoid attaching duplicate handlers.

    """
    global _logging_state

    # 'structlog.is_configured()' is process-wide, so it also guards
    # against other packages (e.g. 'ayon_core') configuring logging first.
    if structlog.is_configured():
        return
    # Configure structlog
    def _add_site_id(logger, method_name, event_dict):
        event_dict.setdefault(
            "site_id", os.environ.get("AYON_SITE_ID", "unknown")
        )
        return event_dict

    def _add_session_id(logger, method_name, event_dict):
        # Read on each record, context variables bound in the main thread
        #   would not be available in other threads.
        session_id = os.environ.get("AYON_SESSION_ID")
        if session_id:
            event_dict.setdefault("session_id", session_id)
        return event_dict

    def _drop_log_context(logger, method_name, event_dict):
        # Keep context fields in JSON sent to Vector but not in console
        # output - full ids make console output hard to read. Trace and
        # span ids are added by 'ayon_core.lib.log_span'.
        for key in (
            "site_id",
            "session_id",
            "trace_id",
            "span_id",
            "parent_span_id",
        ):
            event_dict.pop(key, None)
        return event_dict

    shared_processors: list[Callable] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_site_id,
        _add_session_id,
    ]

    structlog.configure(
        processors=shared_processors + [
            # Support '%s' style arguments, e.g.
            #   'log.info("Loaded %s", name)'. Records from plain
            #   stdlib loggers are already formatted by
            #   'ProcessorFormatter' via 'record.getMessage()'.
            structlog.stdlib.PositionalArgumentsFormatter(),
            # Hand over to standard logging, rendered by formatters
            _render_for_stdlib,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    def _create_console_formatter(colors: bool) -> logging.Formatter:
        return _EventDictProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _drop_log_context,
                _ConsoleRenderer(
                    colors=colors,
                    exception_formatter=(
                        _get_console_exception_formatter(colors)
                    ),
                ),
            ],
        )

    json_formatter = _EventDictProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = _StderrHandler(
        color_formatter=_create_console_formatter(colors=True)
    )
    handler.setFormatter(_create_console_formatter(colors=False))

    if LOG_FILE_ENABLED:
        log_dir = get_launcher_local_dir("logs", create=True)
        _remove_old_log_files(log_dir, LOG_FILE_RETENTION_DAYS)
        file_handler = TimedRotatingFileHandler(
            _get_log_file_path(log_dir),
            when="midnight",
            backupCount=LOG_FILE_RETENTION_DAYS,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)

    if VECTOR_LOG_URL:
        # Send logs to Vector asynchronously so HTTP calls
        # don't block the app.
        # Queue is bounded so a Vector outage drops records instead of
        # growing memory without bound.
        log_queue: queue.Queue = queue.Queue(VECTOR_QUEUE_MAX_SIZE)
        queue_handler = _DroppingQueueHandler(log_queue)
        queue_handler.setFormatter(json_formatter)
        vector_sender = VectorHTTPSender(VECTOR_LOG_URL, log_queue)
        vector_sender.start()
        # The sender thread is a daemon thread, it would be killed on
        # interpreter exit with records still in the queue. Stopping it
        # at exit delivers the queued records first.
        atexit.register(vector_sender.stop)

    log_level = get_log_level_from_env()
    root_logger = logging.getLogger()
    state = _LoggingState(root_level=root_logger.level)
    # Set level first, root logger default WARNING would drop INFO below
    root_logger.setLevel(log_level)
    root_logger.addHandler(handler)
    state.handlers.append(handler)
    if LOG_FILE_ENABLED:
        root_logger.addHandler(file_handler)
        state.handlers.append(file_handler)
    if VECTOR_LOG_URL:
        root_logger.info(
            "Vector logging enabled",
            extra={"vector_log_url": VECTOR_LOG_URL},
        )
        root_logger.addHandler(queue_handler)
        state.handlers.append(queue_handler)
        state.vector_sender = vector_sender

    if log_level < logging.INFO:
        # force silence for some very noisy loggers
        for name in ("urllib3", "requests", "GlobalServerAPI"):
            logger = logging.getLogger(name)
            state.logger_levels[name] = logger.level
            logger.setLevel(logging.WARNING)

    _logging_state = state


def release_logging() -> None:
    """Undo 'configure_logging' before control is passed to 'ayon_core'.

    Logging of the launcher process belongs to 'ayon_core' once it is
    started, it configures logging for its own needs. Handlers added by
    'configure_logging' are removed, levels of the root logger and of
    silenced loggers are restored and structlog configuration is reset.

    Records already queued for Vector are sent in the background, the
    sender thread stops afterwards. Does nothing if 'configure_logging'
    did not configure logging.
    """
    global _logging_state

    state = _logging_state
    if state is None:
        return
    _logging_state = None

    root_logger = logging.getLogger()
    for handler in state.handlers:
        root_logger.removeHandler(handler)
        handler.close()
    root_logger.setLevel(state.root_level)
    for name, level in state.logger_levels.items():
        logging.getLogger(name).setLevel(level)

    if state.vector_sender is not None:
        state.vector_sender.request_stop()

    structlog.reset_defaults()
    structlog.contextvars.clear_contextvars()
