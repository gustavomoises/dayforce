"""GET /health: app status and database reachability."""

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.api.deps import LangfuseDep, RepositoryDep
from app.api.tracing import run_traced

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    database: bool


@router.get("/health", response_model=Health)
def health(
    background_tasks: BackgroundTasks, repository: RepositoryDep, langfuse: LangfuseDep
) -> Health:
    def check(_: str) -> Health:
        database = repository.ping()
        return Health(status="ok" if database else "degraded", database=database)

    return run_traced(langfuse, background_tasks, "GET /health", check)
