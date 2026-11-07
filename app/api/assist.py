"""POST /assist: grounded, ranked suggestions for a support question."""

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import AssistServiceDep, LangfuseDep
from app.api.tracing import run_traced
from app.services.assist.models.request import AssistRequest
from app.services.assist.models.response import AssistResponse

router = APIRouter(tags=["assist"])


@router.post("/assist", response_model=AssistResponse)
def assist(
    request: AssistRequest,
    background_tasks: BackgroundTasks,
    service: AssistServiceDep,
    langfuse: LangfuseDep,
) -> AssistResponse:
    return run_traced(
        langfuse,
        background_tasks,
        "POST /assist",
        lambda app_env: service.assist(request, label=app_env),
        environment=request.environment,
        input=request.model_dump(mode="json"),
    )
