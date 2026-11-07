"""Root observation: trace id from the correlation id, propagated attributes, error marking."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import BackgroundTasks
from langfuse import Langfuse

from app.support.tracing import endpoint
from app.support.tracing.endpoint import root_observation, schedule_flush


class FakeRoot:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update(self, **fields: Any) -> None:
        self.updates.append(fields)


class FakeLangfuse:
    """Records the root observation it is asked to open."""

    def __init__(self) -> None:
        self.root = FakeRoot()
        self.started: list[dict[str, Any]] = []

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Iterator[FakeRoot]:
        self.started.append(kwargs)
        yield self.root

    def flush(self) -> None:
        """Stands in for Langfuse.flush."""


@pytest.fixture
def propagated(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    @contextmanager
    def fake_propagate(**kwargs: Any) -> Iterator[None]:
        calls.append(kwargs)
        yield

    monkeypatch.setattr(endpoint, "propagate_attributes", fake_propagate)
    return calls


def test_root_propagates_environment_name_and_correlation_id(
    propagated: list[dict[str, Any]],
) -> None:
    with root_observation(FakeLangfuse(), "POST /assist", "qa", "corr-1"):
        pass

    assert propagated == [
        {
            "environment": "qa",
            "trace_name": "POST /assist",
            "metadata": {"correlation_id": "corr-1"},
        }
    ]


def test_root_trace_id_is_derived_from_the_correlation_id(
    propagated: list[dict[str, Any]],
) -> None:
    langfuse = FakeLangfuse()

    with root_observation(langfuse, "GET /search", "production", "corr-1", input={"q": "db"}):
        pass

    assert langfuse.started == [
        {
            "as_type": "span",
            "name": "GET /search",
            "trace_context": {"trace_id": Langfuse.create_trace_id(seed="corr-1")},
            "input": {"q": "db"},
        }
    ]


def test_trace_id_is_stable_for_a_correlation_id() -> None:
    first = Langfuse.create_trace_id(seed="corr-1")

    assert first == Langfuse.create_trace_id(seed="corr-1")
    assert first != Langfuse.create_trace_id(seed="corr-2")
    assert len(first) == 32


def test_root_yields_the_observation_for_the_caller(propagated: list[dict[str, Any]]) -> None:
    langfuse = FakeLangfuse()

    with root_observation(langfuse, "cli seed", "production", "corr-1") as root:
        root.update(output={"seeded": 3})

    assert langfuse.root.updates == [{"output": {"seeded": 3}}]


@pytest.mark.parametrize(
    ("error", "status_message"),
    [(ValueError("bad input"), "bad input"), (KeyError(), "KeyError")],
)
def test_error_marks_the_root_and_is_reraised(
    propagated: list[dict[str, Any]], error: Exception, status_message: str
) -> None:
    langfuse = FakeLangfuse()

    with pytest.raises(type(error)), root_observation(langfuse, "n", "dev", "corr-1"):
        raise error

    assert langfuse.root.updates == [{"level": "ERROR", "status_message": status_message}]


def test_flush_runs_as_a_background_task() -> None:
    langfuse = FakeLangfuse()
    tasks = BackgroundTasks()

    schedule_flush(tasks, langfuse)

    assert [task.func for task in tasks.tasks] == [langfuse.flush]
