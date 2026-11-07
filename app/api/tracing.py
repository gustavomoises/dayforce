"""Run a route handler inside its Langfuse root observation."""

from collections.abc import Callable
from typing import Any

from fastapi import BackgroundTasks
from langfuse import Langfuse

from app.core.app_env import resolve_app_env
from app.core.models.incident import Environment
from app.support.tracing.context import get_correlation_id
from app.support.tracing.endpoint import root_observation, schedule_flush


def run_traced[T](
    langfuse: Langfuse,
    background_tasks: BackgroundTasks,
    name: str,
    call: Callable[[str], T],
    environment: Environment | None = None,
    input: dict[str, Any] | None = None,
) -> T:
    """Open the root observation (APP_ENV from the environment filter), call, record output.

    `call` receives the resolved APP_ENV, which services use as the Langfuse prompt label.
    """
    app_env = resolve_app_env(environment)
    correlation_id = get_correlation_id() or ""
    try:
        with root_observation(langfuse, name, app_env, correlation_id, input) as root:
            result = call(app_env)
            root.update(output=_summary(result))
            return result
    finally:
        schedule_flush(background_tasks, langfuse)


def _summary(result: Any) -> Any:
    """Small output for the root; the full payload is on the nested observations."""
    dump = getattr(result, "model_dump", None)
    if dump is None:
        return None
    data = dump(mode="json")
    return {key: value for key, value in data.items() if not isinstance(value, list)}
