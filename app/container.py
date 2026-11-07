"""Composition root: builds every client and service once. Used by main.py and cli.py."""

from dataclasses import dataclass

import openai
from langfuse import Langfuse
from psycopg_pool import ConnectionPool

from app.core.settings import Settings
from app.services.assist.screening import CandidateScreener
from app.services.assist.service import AssistService
from app.services.catalog.service import CatalogService
from app.services.incidents.service import IncidentService
from app.services.ingest.service import IngestService
from app.services.schema.service import SchemaService
from app.services.search.service import SearchService
from app.services.seed.service import SeedService
from app.support.database.incident_repository import PostgresIncidentRepository
from app.support.database.pool import create_pool
from app.support.database.schema_repository import PostgresSchemaRepository
from app.support.langfuse.client import create_langfuse
from app.support.langfuse.prompts import LangfusePromptProvider
from app.support.langfuse.trace_reader import LangfuseTraceReader
from app.support.llm.openai_client import OpenAIClient, create_openai
from app.support.llm.openai_embedder import OpenAIEmbedder
from app.support.secrets.secrets_manager import load_secrets


@dataclass(frozen=True)
class Container:
    settings: Settings
    langfuse: Langfuse
    pool: ConnectionPool
    openai: openai.OpenAI
    repository: PostgresIncidentRepository
    trace_reader: LangfuseTraceReader
    schema: SchemaService
    seed: SeedService
    ingest: IngestService
    search: SearchService
    incidents: IncidentService
    catalog: CatalogService
    assist: AssistService

    def close(self) -> None:
        """Flush traces and release connections."""
        self.langfuse.flush()
        self.pool.close()
        self.openai.close()


def build_container(settings: Settings) -> Container:
    """Read secrets, create clients, wire services through the core ports."""
    secrets = load_secrets(settings.aws_region)
    langfuse = create_langfuse(secrets, settings)
    pool = create_pool(secrets.database, settings)
    client = create_openai(secrets, settings)

    repository = PostgresIncidentRepository(pool, settings.ivfflat_probes)
    schema_repository = PostgresSchemaRepository(pool)
    prompts = LangfusePromptProvider(langfuse)
    llm = OpenAIClient(client, settings)
    embedder = OpenAIEmbedder(client, settings)

    schema = SchemaService(schema_repository)
    ingest = IngestService(repository, embedder, settings)
    search = SearchService(repository, embedder, settings)
    incidents = IncidentService(repository)
    return Container(
        settings=settings,
        langfuse=langfuse,
        pool=pool,
        openai=client,
        repository=repository,
        trace_reader=LangfuseTraceReader(langfuse, settings),
        schema=schema,
        seed=SeedService(schema_repository, schema, ingest, settings),
        ingest=ingest,
        search=search,
        incidents=incidents,
        catalog=CatalogService(prompts, llm, settings),
        assist=AssistService(
            CandidateScreener(search, prompts, llm, settings), incidents, prompts, llm, settings
        ),
    )
