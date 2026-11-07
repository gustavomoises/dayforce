"""FastAPI entry point: `uvicorn main:app --host 0.0.0.0 --port 8000`."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import assist, catalog, debug, health, incidents, ingest, search
from app.api.errors import register_error_handlers
from app.container import build_container
from app.core.settings import Settings
from app.support.tracing.correlation import CorrelationMiddleware
from app.support.tracing.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Build the container once at startup; close clients on shutdown."""
    configure_logging(logging.INFO)
    container = build_container(Settings.from_env())
    configure_logging(logging.INFO, container.langfuse)
    app.state.container = container
    try:
        yield
    finally:
        container.close()


def create_app() -> FastAPI:
    app = FastAPI(title="Incident Triage API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CorrelationMiddleware)
    register_error_handlers(app)
    for module in (ingest, search, incidents, assist, catalog, debug, health):
        app.include_router(module.router)
    return app


app = create_app()
