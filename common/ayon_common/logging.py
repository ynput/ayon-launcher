"""Logging setup for AYON common package."""
import logging
import os
import queue
import sys
from logging.handlers import QueueHandler, QueueListener

import requests
import requests.adapters
import structlog

VECTOR_LOG_URL = os.getenv("AYON_VECTOR_LOG_URL")


class _RawQueueHandler(QueueHandler):
    """QueueHandler that does not pre-format/stringify the record.

    The stdlib's default 'prepare' stringifies 'record.msg', which
    destroys the structlog event dict before it reaches the listener's
    handlers.
    """

    def prepare(self, record):
        return record


class VectorHTTPHandler(logging.Handler):
    """Forward formatted log records to a Vector HTTP source.

    This is here so we can use Vector for log aggregation
    earlier before ayon-core and ayon-vector are started.
    """

    def __init__(self, url):
        super().__init__()
        self._url = url
        # Reuse a single session so repeated POSTs reuse pooled
        # connections instead of opening a new one per log record.
        self._session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=1, pool_maxsize=10
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def emit(self, record):
        try:
            self._session.post(
                self._url,
                data=self.format(record),
                headers={"Content-Type": "application/json"},
                timeout=1,
            )
        except Exception:  # noqa: BLE001
            self.handleError(record)

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

    shared_processors = [
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

    if VECTOR_LOG_URL:
        # Send logs to Vector asynchronously so HTTP calls don't block the app.
        vector_handler = VectorHTTPHandler(VECTOR_LOG_URL)
        vector_handler.setFormatter(json_formatter)
        log_queue = queue.Queue(-1)
        queue_handler = _RawQueueHandler(log_queue)
        queue_listener = QueueListener(
            log_queue, vector_handler, respect_handler_level=True
        )
        queue_listener.start()

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    if VECTOR_LOG_URL:
        root_logger.info("Vector logging enabled", extra={"vector_log_url": VECTOR_LOG_URL})
        root_logger.addHandler(queue_handler)
    root_logger.setLevel(logging.INFO if os.getenv("AYON_DEBUG") != "1" else logging.DEBUG)
    # when debug is enabled, we want to silence some of the noisy libraries
    # TODO(antirotor): make this configurable via env var or config file or
    # even a command line argument (list of modules and their log levels, comma separated)
    info_level = logging.getLevelNamesMapping()['INFO']
    if (
            os.getenv("AYON_DEBUG") == "1" or
            int(os.getenv("AYON_LOG_LEVEL", info_level)) < info_level):
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("GlobalServerAPI").setLevel(logging.WARNING)
