"""Structured JSON logging."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "asctime", "message", "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        # Structured payloads travel under "data" because several natural field names
        # ("created", "module", "name", "args") are reserved LogRecord attributes and
        # passing them through `extra=` raises at call time.
        if isinstance(payload.get("data"), dict):
            payload["data"] = record.data  # type: ignore[attr-defined]
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def payload(data: dict) -> dict:
    """Wrap a structured payload for ``extra=``.

    ``logging`` rejects any key that shadows a ``LogRecord`` attribute — ``created``,
    ``name``, ``module``, ``args``, ``message`` and others — and several of those are
    natural result-field names. Nesting under ``data`` sidesteps the collision entirely
    instead of asking every call site to remember the reserved list.
    """
    return {"data": data}
