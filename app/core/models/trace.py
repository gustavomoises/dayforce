"""A trace as returned by Langfuse, unchanged."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class TraceView(BaseModel):
    model_config = ConfigDict(frozen=True)

    correlation_id: str
    trace_id: str
    langfuse_url: str
    observations: list[dict[str, Any]]
