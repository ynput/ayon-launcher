"""Logging setup for AYON common package.

Three opt-in observability levels are supported, additive to each other:
    1. Console (default) - human readable output to stdout. Always on.
    2. NDJSON file - one JSON object per line, written to a local log
        file with retention. Enabled with 'AYON_LOG_FILE=1'.
    3. Vector - forward JSON logs to a Vector HTTP source. Enabled by
        setting 'AYON_VECTOR_LOG_URL'.
"""
import atexit
import logging
import os
import queue
import sys
import time
from collections.abc import Callable
from logging.handlers import QueueHandler, QueueListener, TimedRotatingFileHandler

import requests
import requests.adapters
import structlog
import urllib3.util

from ayon_common.utils import get_launcher_local_dir

VECTOR_LOG_URL = os.getenv("AYON_VECTOR_LOG_URL")
LOG_FILE_ENABLED = os.getenv("AYON_LOG_FILE") == "1"
LOG_FILE_RETENTION_DAYS = int(os.getenv("AYON_LOG_RETENTION_DAYS", "1"))
LOG_FILE_NAME = "ayon.ndjson"

# Max records buffered for Vector delivery. Beyond this, new records are
# dropped rather than growing memory unbounded during an outage.
VECTOR_QUEUE_MAX_SIZE = 10_000
# Consecutive send failures after which the circuit opens (stop trying
# HTTP calls for a while, just drop records fast).
VECTOR_FAILURE_THRESHOLD = 5
# How long the circuit stays open once tripped.
VECTOR_CIRCUIT_COOLDOWN = 30.0
# Minimum time between "records are being dropped" warnings, to avoid
# flooding the console/log file during a prolonged outage.
VECTOR_WARN_INTERVAL = 30.0


class _RateLimitedLogger:
    """Log a warning at most once per 'interval' seconds."""

    def __init__(self, logger, interval):
        self._logger = logger
        self._interval = interval
        self._last_emit = 0.0

    def warning(self, msg, **kwargs):
        now = time.monotonic()
        if now - self._last_emit < self._interval:
            return
        self._last_emit = now
        self._logger.warning(msg, **kwargs)


_vector_warn_logger = _RateLimitedLogger(
    logging.getLogger("ayon.vector_log"), VECTOR_WARN_INTERVAL
)


class _RawQueueHandler(QueueHandler):
    """QueueHandler that does not pre-format/stringify the record.

    The stdlib's default 'prepare' stringifies 'record.msg', which
    destroys the structlog event dict before it reaches the listener's
    handlers.
    """

    def prepare(self, record):
        return record

    def enqueue(self, record):
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


class VectorHTTPHandler(logging.Handler):
    """Forward formatted log records to a Vector HTTP source.

    This is here so we can use Vector for log aggregation
    earlier before ayon-core and ayon-vector are started.
    """

    def __init__(
        self,
        url,
        failure_threshold=VECTOR_FAILURE_THRESHOLD,
        cooldown=VECTOR_CIRCUIT_COOLDOWN,
    ):
        super().__init__()
        self._url = url
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown
        self._consecutive_failures = 0
        self._circuit_open_until = 0.0
        # Reuse a single session so repeated POSTs reuse pooled
        # connections instead of opening a new one per log record.
        self._session = requests.Session()
        retry = urllib3.util.Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=(502, 503, 504),
            allowed_methods=("POST",),
        )
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1, pool_maxsize=10, max_retries=retry
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def emit(self, record):
        now = time.monotonic()
        if now < self._circuit_open_until:
            # Circuit is open - skip the HTTP attempt entirely so a dead
            # Vector endpoint cannot slow down the sender thread.
            return
        try:
            self._session.post(
                self._url,
                data=self.format(record),
                headers={"Content-Type": "application/json"},
                # (connect timeout, read timeout) - a slow-but-alive
                # endpoint should not stall as long as a dead one.
                timeout=(0.3, 1.0),
            )
        except Exception:  # noqa: BLE001
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._failure_threshold:
                self._circuit_open_until = now + self._cooldown
                self._consecutive_failures = 0
                _vector_warn_logger.warning(
                    "Vector endpoint unreachable, pausing log delivery.",
                    cooldown=self._cooldown,
                )
            self.handleError(record)
        else:
            self._consecutive_failures = 0

    def handleError(self, record):
        # Default 'Handler.handleError' prints a full traceback to stderr
        # per failed record, which floods the console during an outage.
        # Rate-limit it instead.
        _vector_warn_logger.warning("Failed to send log record to Vector.")

    def close(self):
        self._session.close()
        super().close()


def configure_logging() -> None:
    """Set up logging for AYON common package.

    Sets up structlog with a console renderer
    and a JSON renderer for sending logs to Vector.

    Safe to call multiple times, and safe even if another package (e.g.
    'ayon_core') configures logging first - only the first call in the
    process has any effect, to avoid attaching duplicate handlers.

    """
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

    def _drop_site_id(logger, method_name, event_dict):
        # Keep 'site_id' in JSON sent to Vector but not in console output
        event_dict.pop("site_id", None)
        return event_dict

    shared_processors: list[Callable] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_site_id,
    ]

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors + [
            structlog.stdlib.PositionalArgumentsFormatter(),
        ],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _drop_site_id,
            structlog.dev.ConsoleRenderer(
                exception_formatter=structlog.dev.rich_traceback,
            ),
        ],
    )
    json_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(console_formatter)

    if LOG_FILE_ENABLED:
        log_dir = get_launcher_local_dir("logs", create=True)
        file_handler = TimedRotatingFileHandler(
            os.path.join(log_dir, LOG_FILE_NAME),
            when="midnight",
            backupCount=LOG_FILE_RETENTION_DAYS,
            encoding="utf-8",
        )
        file_handler.setFormatter(json_formatter)

    if VECTOR_LOG_URL:
        # Send logs to Vector asynchronously so HTTP calls
        # don't block the app.
        vector_handler = VectorHTTPHandler(VECTOR_LOG_URL)
        vector_handler.setFormatter(json_formatter)
        log_queue: queue.Queue = queue.Queue(VECTOR_QUEUE_MAX_SIZE)
        queue_handler = _RawQueueHandler(log_queue)
        queue_listener = QueueListener(
            log_queue, vector_handler, respect_handler_level=True,
        )
        queue_listener.start()
        # The listener thread is background by default and otherwise would
        # keep the process alive/delay shutdown since 'queue_listener.stop()'
        # is never called explicitly elsewhere.
        atexit.register(queue_listener.stop)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    if LOG_FILE_ENABLED:
        root_logger.addHandler(file_handler)
    if VECTOR_LOG_URL:
        root_logger.info("Vector logging enabled", extra={"vector_log_url": VECTOR_LOG_URL})
        root_logger.addHandler(queue_handler)
    root_logger.setLevel(logging.INFO if os.getenv("AYON_DEBUG") != "1" else logging.DEBUG)

    if os.getenv("AYON_DEBUG") == "1":
        # force silence for some very noisy loggers
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("GlobalServerAPI").setLevel(logging.WARNING)
