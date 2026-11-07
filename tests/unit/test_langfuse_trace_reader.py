"""LangfuseTraceReader: observations returned unchanged, not ready, unreachable."""

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from langfuse import Langfuse
from langfuse.api.core.api_error import ApiError
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import LangfuseUnavailable, TraceNotReady
from app.core.settings import Settings
from app.support.langfuse.trace_reader import LangfuseTraceReader

HOST = "https://langfuse.example"
TRACE_ID = Langfuse.create_trace_id(seed="corr-1")


class Observation(BaseModel):
    """Shaped like the SDK's observation views: camelCase aliases, optional fields."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    start_time: datetime = Field(alias="startTime")
    metadata: dict[str, Any] | None = None


class Page:
    def __init__(self, data: list[Observation]) -> None:
        self.data = data


class FakeObservations:
    def __init__(self, result: Page | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def get_many(self, **kwargs: Any) -> Page:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeApi:
    def __init__(self, observations: FakeObservations) -> None:
        self.observations = observations


class FakeLangfuse:
    def __init__(self, result: Page | Exception, url: str | None = None) -> None:
        self.api = FakeApi(FakeObservations(result))
        self.url = url

    def get_trace_url(self, *, trace_id: str) -> str | None:
        return self.url


def observation() -> Observation:
    return Observation(id="obs-1", start_time=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))


def reader(langfuse: FakeLangfuse) -> LangfuseTraceReader:
    return LangfuseTraceReader(langfuse, Settings(langfuse_host=HOST))


def test_observations_are_requested_by_the_derived_trace_id() -> None:
    langfuse = FakeLangfuse(Page([observation()]))

    reader(langfuse).get("corr-1")

    [call] = langfuse.api.observations.calls
    assert call["trace_id"] == TRACE_ID
    assert {"io", "metadata"} <= set(call["fields"].split(","))


def test_observations_are_returned_as_langfuse_sends_them() -> None:
    view = reader(FakeLangfuse(Page([observation()]))).get("corr-1")

    assert view.correlation_id == "corr-1"
    assert view.trace_id == TRACE_ID
    assert view.observations == [{"id": "obs-1", "startTime": "2026-01-02T03:04:05Z"}]


def test_sdk_trace_url_is_used_when_available() -> None:
    view = reader(FakeLangfuse(Page([observation()]), url="https://lf/project/p/traces/t")).get(
        "corr-1"
    )

    assert view.langfuse_url == "https://lf/project/p/traces/t"


def test_trace_url_falls_back_to_the_host() -> None:
    view = reader(FakeLangfuse(Page([observation()]))).get("corr-1")

    assert view.langfuse_url == f"{HOST}/trace/{TRACE_ID}"


def test_trace_without_observations_is_not_ready() -> None:
    with pytest.raises(TraceNotReady, match="retry shortly"):
        reader(FakeLangfuse(Page([]))).get("corr-1")


@pytest.mark.parametrize(
    "failure",
    [ApiError(status_code=503, body="down"), httpx.ConnectError("unreachable")],
    ids=["api-error", "network"],
)
def test_unreachable_langfuse_names_the_host_setting(failure: Exception) -> None:
    with pytest.raises(LangfuseUnavailable, match="LANGFUSE_HOST"):
        reader(FakeLangfuse(failure)).get("corr-1")
