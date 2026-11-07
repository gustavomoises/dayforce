"""GET /debug/trace/{correlation_id}: the trace as Langfuse returns it. Not traced itself."""

from fastapi import APIRouter

from app.api.deps import TraceReaderDep
from app.core.models.trace import TraceView

router = APIRouter(tags=["debug"])


@router.get("/debug/trace/{correlation_id}", response_model=TraceView)
def get_trace(correlation_id: str, reader: TraceReaderDep) -> TraceView:
    return reader.get(correlation_id)
