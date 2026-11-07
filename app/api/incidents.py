"""GET /incidents/{id}: one full incident record."""

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import IncidentServiceDep, LangfuseDep
from app.api.tracing import run_traced
from app.core.models.incident import Incident

router = APIRouter(tags=["incidents"])


@router.get("/incidents/{incident_id}", response_model=Incident)
def get_incident(
    incident_id: str,
    background_tasks: BackgroundTasks,
    service: IncidentServiceDep,
    langfuse: LangfuseDep,
) -> Incident:
    return run_traced(
        langfuse,
        background_tasks,
        "GET /incidents/{id}",
        lambda _: service.get(incident_id),
        input={"id": incident_id},
    )
