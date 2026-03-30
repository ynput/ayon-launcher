"""Shared utilities for AYON build tools."""

from __future__ import annotations

import logging
import sys

import blessed

term = blessed.Terminal()

# -----------------------------------------------------------------
# Logger setup
# -----------------------------------------------------------------


class _CustomFormatter(logging.Formatter):
    """Custom formatter with prefixed output mimicking blessed style."""

    _PREFIXES = {
        logging.INFO: term.aquamarine3(">>> "),
        logging.ERROR: term.orangered2("!!! "),
        logging.WARNING: term.tan1("... "),
        logging.DEBUG: term.darkolivegreen3("--- "),
    }

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with prefixed style.

        Args:
            record: The log record to format.

        Returns:
            Formatted log message string.
        """
        prefix = self._PREFIXES.get(record.levelno, "--- ")
        return f"{prefix}{record.getMessage()}"


def get_logger(name: str) -> logging.Logger:
    """Get a logger with custom formatting.

    Idempotent — calling this multiple times for the same *name*
    will not add duplicate handlers.

    Args:
        name: Logger name (typically ``__name__``).

    Returns:
        Configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Guard against duplicate handlers on re-import / repeated calls.
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_CustomFormatter())
        logger.addHandler(handler)

    # Prevent propagation to the root logger to avoid double output.
    logger.propagate = False

    return logger
