"""Root observation for one request or CLI command, and the flush after the response."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import BackgroundTasks
from langfuse import Langfuse, LangfuseSpan, propagate_attributes


@contextmanager
def root_observation(
    langfuse: Langfuse,
    name: str,
    app_env: str,
    correlation_id: str,
    input: dict[str, Any] | None = None,
) -> Iterator[LangfuseSpan]:
    """Open the trace root; every nested observation inherits environment and correlation_id.

    The trace id is derived from the correlation_id, so it can be rebuilt later. The caller
    records the output with `root.update(output=...)`; errors mark the root ERROR and re-raise.
    """
    trace_id = Langfuse.create_trace_id(seed=correlation_id)
    with (
        propagate_attributes(
            environment=app_env,
            trace_name=name,
            metadata={"correlation_id": correlation_id},
        ),
        langfuse.start_as_current_observation(
            as_type="span",
            name=name,
            trace_context={"trace_id": trace_id},
            input=input,
        ) as root,
    ):
        try:
            yield root
        except Exception as exc:
            root.update(level="ERROR", status_message=str(exc) or type(exc).__name__)
            raise


def schedule_flush(background_tasks: BackgroundTasks, langfuse: Langfuse) -> None:
    """Flush spans to Langfuse after the response is sent, so it adds no latency."""
    background_tasks.add_task(langfuse.flush)
