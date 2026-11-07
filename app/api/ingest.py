"""POST /ingest: upsert a batch of incidents; no body, null or [] only embeds pending rows."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body
from pydantic import Field

from app.api.deps import IngestServiceDep, LangfuseDep
from app.api.tracing import run_traced
from app.services.ingest.models import IncidentIn, IngestResult

router = APIRouter(tags=["ingest"])

# Mirrors Settings.ingest_max_items so oversized bodies fail validation with 422.
IngestBody = Annotated[list[IncidentIn], Field(max_length=500)] | None


@router.post("/ingest", response_model=IngestResult, response_model_exclude_none=True)
def ingest(
    background_tasks: BackgroundTasks,
    service: IngestServiceDep,
    langfuse: LangfuseDep,
    incidents: Annotated[IngestBody, Body()] = None,
) -> IngestResult:
    return run_traced(
        langfuse,
        background_tasks,
        "POST /ingest",
        lambda _: service.ingest(incidents),
        input={"items": len(incidents or [])},
    )
