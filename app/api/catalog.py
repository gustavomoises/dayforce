"""GET /catalog: the committed service catalog. Never calls the LLM."""

from fastapi import APIRouter, BackgroundTasks

from app.api.deps import CatalogServiceDep, LangfuseDep
from app.api.tracing import run_traced
from app.core.models.catalog import Catalog

router = APIRouter(tags=["catalog"])


@router.get("/catalog", response_model=Catalog)
def get_catalog(
    background_tasks: BackgroundTasks, service: CatalogServiceDep, langfuse: LangfuseDep
) -> Catalog:
    return run_traced(langfuse, background_tasks, "GET /catalog", lambda _: service.get())
