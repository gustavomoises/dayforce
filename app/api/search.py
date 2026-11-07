"""GET /search: hybrid search with optional filters."""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query

from app.api.deps import LangfuseDep, SearchServiceDep
from app.api.tracing import run_traced
from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment, Severity
from app.core.normalize import normalize_code, normalize_tags
from app.services.search.models import SearchResult

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResult)
def search(
    background_tasks: BackgroundTasks,
    search_service: SearchServiceDep,
    langfuse: LangfuseDep,
    q: Annotated[str | None, Query(max_length=2000)] = None,
    environment: Environment | None = None,
    service: str | None = None,
    severity: Severity | None = None,
    tags: Annotated[str | None, Query(description="comma-separated; all must match")] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> SearchResult:
    filters = SearchFilters(
        environment=environment,
        service=normalize_code(service) if service else None,
        severity=severity,
        tags=normalize_tags(tags.split(",")) if tags else (),
    )
    return run_traced(
        langfuse,
        background_tasks,
        "GET /search",
        lambda _: search_service.search(filters, q, limit),
        environment=environment,
        input={"q": q, "filters": filters.model_dump(mode="json"), "limit": limit},
    )
