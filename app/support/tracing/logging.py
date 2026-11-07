"""JSON logs on stdout with correlation_id and observation id, forwarded to Langfuse as events."""

import json
import logging
import sys
from contextlib import suppress
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from langfuse import Langfuse
from opentelemetry import trace

from app.support.tracing.context import get_correlation_id

_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {
    "message",
    "asctime",
    "correlation_id",
    "observation_id",
}
_MAX_METADATA_CHARS = 200  # Langfuse metadata limit per value
_EVENT_LEVELS = {logging.ERROR: "ERROR", logging.WARNING: "WARNING", logging.INFO: "DEFAULT"}
_forwarding: ContextVar[bool] = ContextVar("langfuse_log_forwarding", default=False)
# `extra={"io": "output", ...}` puts a log line's fields in the Langfuse event output;
# otherwise they go in the event input.
IO_FIELD = "io"
# Library request logs duplicate what Langfuse already records; keep only their warnings.
_QUIET_LOGGERS = ("httpx", "httpx2", "httpcore", "httpcore2", "botocore", "urllib3", "openai")


def configure_logging(level: int | str, langfuse: Langfuse | None = None) -> None:
    """Install JSON stdout logging; with a client, also forward records to Langfuse.

    Call without a client before the container exists, then again with it.
    """
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(JsonFormatter())
    handlers: list[logging.Handler] = [stdout]
    if langfuse is not None:
        handlers.append(LangfuseLogHandler(langfuse))
    for handler in handlers:
        handler.addFilter(TraceContextFilter())
    logging.basicConfig(level=level, handlers=handlers, force=True)
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def current_observation_id() -> str | None:
    """Id of the active Langfuse observation (the current OpenTelemetry span), if any."""
    span = trace.get_current_span()
    if not span.is_recording():
        return None
    return format(span.get_span_context().span_id, "016x")


def extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    """Fields passed through `extra={...}`."""
    return {key: value for key, value in vars(record).items() if key not in _STANDARD_ATTRS}


class TraceContextFilter(logging.Filter):
    """Adds `correlation_id` and `observation_id` to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        record.observation_id = current_observation_id()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg, ids and extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        line = {
            "ts": ts.replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "correlation_id": getattr(record, "correlation_id", None),
            "observation_id": getattr(record, "observation_id", None),
            "msg": record.getMessage(),
            **extra_fields(record),
        }
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str, ensure_ascii=False)


class LangfuseLogHandler(logging.Handler):
    """Sends INFO and above as a Langfuse event under the active observation; never raises."""

    def __init__(self, langfuse: Langfuse) -> None:
        super().__init__(level=logging.INFO)
        self._langfuse = langfuse

    def emit(self, record: logging.LogRecord) -> None:
        if _forwarding.get() or getattr(record, "observation_id", None) is None:
            return
        token = _forwarding.set(True)  # SDK logs raised while sending must not loop back here
        # The stdout line is already written; a Langfuse failure must never break the request.
        try:
            with suppress(Exception):
                fields = extra_fields(record)
                side = "output" if fields.pop(IO_FIELD, None) == "output" else "input"
                self._langfuse.create_event(
                    name=record.getMessage(),
                    level=_EVENT_LEVELS.get(record.levelno, "ERROR"),
                    metadata=_event_metadata(record),
                    **{side: fields or None},
                )
        finally:
            _forwarding.reset(token)


def _event_metadata(record: logging.LogRecord) -> dict[str, Any]:
    """Filterable context; the log line's own fields go in the event input."""
    fields = {"correlation_id": getattr(record, "correlation_id", None), "logger": record.name}
    return {key: _truncate(value) for key, value in fields.items() if value is not None}


def _truncate(value: Any) -> Any:
    """Keep short values as they are; cut long ones to a string within the Langfuse limit."""
    text = value if isinstance(value, str) else json.dumps(value, default=str, ensure_ascii=False)
    return value if len(text) <= _MAX_METADATA_CHARS else text[:_MAX_METADATA_CHARS]
