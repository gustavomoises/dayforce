"""FastAPI dependencies. Routes use these aliases, never app.state directly."""

from typing import Annotated

from fastapi import Depends
from langfuse import Langfuse
from starlette.requests import HTTPConnection

from app.container import Container
from app.services.assist.service import AssistService
from app.services.catalog.service import CatalogService
from app.services.incidents.service import IncidentService
from app.services.ingest.service import IngestService
from app.services.search.service import SearchService
from app.support.database.incident_repository import PostgresIncidentRepository
from app.support.langfuse.trace_reader import LangfuseTraceReader


def _container(connection: HTTPConnection) -> Container:
    return connection.app.state.container


def get_langfuse(connection: HTTPConnection) -> Langfuse:
    return _container(connection).langfuse


def get_ingest_service(connection: HTTPConnection) -> IngestService:
    return _container(connection).ingest


def get_search_service(connection: HTTPConnection) -> SearchService:
    return _container(connection).search


def get_incident_service(connection: HTTPConnection) -> IncidentService:
    return _container(connection).incidents


def get_assist_service(connection: HTTPConnection) -> AssistService:
    return _container(connection).assist


def get_catalog_service(connection: HTTPConnection) -> CatalogService:
    return _container(connection).catalog


def get_trace_reader(connection: HTTPConnection) -> LangfuseTraceReader:
    return _container(connection).trace_reader


def get_repository(connection: HTTPConnection) -> PostgresIncidentRepository:
    return _container(connection).repository


LangfuseDep = Annotated[Langfuse, Depends(get_langfuse)]
IngestServiceDep = Annotated[IngestService, Depends(get_ingest_service)]
SearchServiceDep = Annotated[SearchService, Depends(get_search_service)]
IncidentServiceDep = Annotated[IncidentService, Depends(get_incident_service)]
AssistServiceDep = Annotated[AssistService, Depends(get_assist_service)]
CatalogServiceDep = Annotated[CatalogService, Depends(get_catalog_service)]
TraceReaderDep = Annotated[LangfuseTraceReader, Depends(get_trace_reader)]
RepositoryDep = Annotated[PostgresIncidentRepository, Depends(get_repository)]
