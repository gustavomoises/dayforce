"""Protocols that services depend on. Support code implements them; tests fake them."""

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import Protocol

from pydantic import BaseModel

from app.core.models.incident import Incident, Severity
from app.core.models.prompt import CompiledPrompt, EmbeddingResult, LLMResult
from app.core.models.search import SearchPage, SearchQuery
from app.core.models.storage import (
    EmbeddedRow,
    ExistingIncident,
    IncidentRecord,
    PendingEmbedding,
    TypeSets,
)
from app.core.models.trace import TraceView


class PromptProvider(Protocol):
    def get(self, name: str, variables: dict[str, str], label: str) -> CompiledPrompt: ...


class LLMClient(Protocol):
    def complete[OutputT: BaseModel](
        self, prompt: CompiledPrompt, output_model: type[OutputT]
    ) -> LLMResult[OutputT]: ...


class EmbeddingClient(Protocol):
    def embed_batch(self, texts: Sequence[str]) -> EmbeddingResult: ...


class IncidentUnitOfWork(Protocol):
    """One transaction. Commits on normal exit, rolls back on exception."""

    def load_types(self) -> TypeSets: ...

    def find_existing(
        self, ids: Sequence[str], content_hashes: Sequence[str]
    ) -> tuple[dict[str, ExistingIncident], dict[str, str]]:
        """Return (existing incidents by id, owning id by content hash)."""
        ...

    def insert(self, records: Sequence[IncidentRecord]) -> None: ...

    def update(self, records: Sequence[IncidentRecord]) -> None:
        """Update rows; clear the embedding where embedding_text_hash changed."""
        ...

    def lock_pending_embeddings(self, model: str, limit: int) -> list[PendingEmbedding]:
        """Rows with NULL embedding or another model, FOR UPDATE SKIP LOCKED."""
        ...

    def save_embeddings(self, rows: Sequence[EmbeddedRow]) -> None: ...

    def count_pending_embeddings(self, model: str) -> int: ...


class IncidentRepository(Protocol):
    def unit_of_work(self) -> AbstractContextManager[IncidentUnitOfWork]: ...

    def search(self, query: SearchQuery) -> SearchPage: ...

    def get(self, incident_id: str) -> Incident | None: ...

    def get_many(self, incident_ids: Sequence[str]) -> list[Incident]: ...

    def get_query_embedding(self, query_hash: str) -> list[float] | None: ...

    def save_query_embedding(self, query_hash: str, model: str, vector: list[float]) -> None: ...

    def ping(self) -> bool: ...


class SchemaRepository(Protocol):
    def create_schema(self) -> None:
        """Apply the DDL files in order. Idempotent; never drops."""
        ...

    def drop_incident_tables(self) -> None: ...

    def upsert_types(
        self,
        environments: Sequence[str],
        severities: Sequence[tuple[Severity, int]],
        services: Sequence[str],
    ) -> None: ...


class TraceReader(Protocol):
    def get(self, correlation_id: str) -> TraceView: ...
