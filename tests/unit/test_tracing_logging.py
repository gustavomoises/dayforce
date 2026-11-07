"""JSON log lines and the Langfuse log handler: fields, io routing, ids, never raising."""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider

from app.support.tracing.context import correlation_scope
from app.support.tracing.logging import (
    JsonFormatter,
    LangfuseLogHandler,
    TraceContextFilter,
    current_observation_id,
)

OBSERVATION_ID = "00f067aa0ba902b7"


class FakeLangfuse:
    """Records events; optionally fails or calls back into the handler like SDK logging would."""

    def __init__(self, error: Exception | None = None) -> None:
        self.events: list[dict[str, Any]] = []
        self.error = error
        self.on_event: LangfuseLogHandler | None = None

    def create_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)
        if self.on_event is not None:
            self.on_event.emit(make_record("sdk log while sending"))
        if self.error is not None:
            raise self.error


def make_record(msg: str, level: int = logging.INFO, **fields: Any) -> logging.LogRecord:
    return logging.makeLogRecord(
        {
            "name": "app.services.assist",
            "levelno": level,
            "levelname": logging.getLevelName(level),
            "msg": msg,
            "observation_id": OBSERVATION_ID,
            "correlation_id": "corr-1",
            **fields,
        }
    )


def emit(record: logging.LogRecord, langfuse: FakeLangfuse | None = None) -> list[dict[str, Any]]:
    langfuse = langfuse or FakeLangfuse()
    LangfuseLogHandler(langfuse).emit(record)
    return langfuse.events


def test_json_line_has_ids_message_and_extra_fields() -> None:
    record = make_record("step tool:search output", hits=12, top_ids=["inc-00001"])

    line = json.loads(JsonFormatter().format(record))

    assert line["level"] == "INFO"
    assert line["logger"] == "app.services.assist"
    assert line["msg"] == "step tool:search output"
    assert line["correlation_id"] == "corr-1"
    assert line["observation_id"] == OBSERVATION_ID
    assert (line["hits"], line["top_ids"]) == (12, ["inc-00001"])
    assert line["ts"].endswith("Z")


def test_json_line_serializes_unknown_types_as_text() -> None:
    when = datetime(2026, 1, 2, tzinfo=UTC)

    line = json.loads(JsonFormatter().format(make_record("m", when=when)))

    assert line["when"] == str(when)


def test_json_line_includes_the_exception() -> None:
    try:
        raise ValueError("broken")
    except ValueError:
        record = make_record("failed", logging.ERROR, exc_info=sys.exc_info())

    line = json.loads(JsonFormatter().format(record))

    assert "ValueError: broken" in line["exc"]


def test_filter_adds_the_current_correlation_id() -> None:
    record = logging.makeLogRecord({"msg": "m"})

    with correlation_scope("corr-9"):
        TraceContextFilter().filter(record)

    assert record.correlation_id == "corr-9"
    assert record.observation_id is None


def test_observation_id_is_the_active_span_id() -> None:
    tracer = TracerProvider().get_tracer("test")

    with tracer.start_as_current_span("step") as span:
        observation_id = current_observation_id()

    assert observation_id == format(span.get_span_context().span_id, "016x")
    assert current_observation_id() is None


def test_record_without_observation_is_not_sent() -> None:
    assert emit(make_record("m", observation_id=None)) == []


def test_fields_go_to_the_event_input() -> None:
    [event] = emit(make_record("step tool:search input", q="db timeout", n=5))

    assert event["name"] == "step tool:search input"
    assert event["input"] == {"q": "db timeout", "n": 5}
    assert "output" not in event


def test_io_output_routes_fields_to_the_event_output() -> None:
    [event] = emit(make_record("step selected_ids", io="output", selected_ids=["inc-00001"]))

    assert event["output"] == {"selected_ids": ["inc-00001"]}
    assert "input" not in event


def test_record_without_fields_sends_no_input() -> None:
    [event] = emit(make_record("plain"))

    assert event["input"] is None


def test_metadata_has_correlation_id_and_logger() -> None:
    [event] = emit(make_record("m"))

    assert event["metadata"] == {"correlation_id": "corr-1", "logger": "app.services.assist"}


def test_long_metadata_values_are_truncated() -> None:
    [event] = emit(make_record("m", name="x" * 500))

    assert event["metadata"]["logger"] == "x" * 200


@pytest.mark.parametrize(
    ("level", "event_level"),
    [
        (logging.INFO, "DEFAULT"),
        (logging.WARNING, "WARNING"),
        (logging.ERROR, "ERROR"),
        (logging.CRITICAL, "ERROR"),
    ],
)
def test_log_level_maps_to_event_level(level: int, event_level: str) -> None:
    [event] = emit(make_record("m", level))

    assert event["level"] == event_level


def test_debug_records_are_not_sent() -> None:
    langfuse = FakeLangfuse()
    logger = logging.Logger("isolated")
    logger.addHandler(LangfuseLogHandler(langfuse))

    logger.debug("noise", extra={"observation_id": OBSERVATION_ID})
    logger.info("kept", extra={"observation_id": OBSERVATION_ID})

    assert [event["name"] for event in langfuse.events] == ["kept"]


def test_langfuse_failure_never_raises() -> None:
    langfuse = FakeLangfuse(error=ConnectionError("langfuse down"))

    events = emit(make_record("m"), langfuse)

    assert len(events) == 1


@pytest.mark.parametrize("name", ["uvicorn", "uvicorn.access", "uvicorn.error"])
def test_server_logs_stay_on_stdout_only(name: str) -> None:
    assert emit(make_record('1.2.3.4:5 - "POST /assist HTTP/1.1" 200', name=name)) == []


def test_logs_raised_while_sending_are_not_forwarded() -> None:
    langfuse = FakeLangfuse()
    handler = LangfuseLogHandler(langfuse)
    langfuse.on_event = handler

    handler.emit(make_record("original"))

    assert [event["name"] for event in langfuse.events] == ["original"]
