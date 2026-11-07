"""IngestService: outcomes, commit before embedding, and pending-only runs."""

import copy
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.errors import EmbeddingUnavailable, LLMTimeout
from app.core.models.prompt import EmbeddingResult
from app.core.models.storage import (
    EmbeddedRow,
    ExistingIncident,
    IncidentRecord,
    PendingEmbedding,
    TypeSets,
)
from app.core.settings import Settings
from app.services.ingest.models import IncidentIn, IngestResult, Rejection
from app.services.ingest.service import RETRY_HINT, IngestService

SETTINGS = Settings(embedding_dimensions=3, embedding_batch_size=2)
TYPES = TypeSets(
    environments=frozenset({"dev", "qa", "stage", "prod"}),
    services=frozenset({"payments-api", "auth-service"}),
    severities=frozenset({"critical", "high", "medium", "low"}),
)


@dataclass
class Store:
    """Committed database state."""

    rows: dict[str, IncidentRecord] = field(default_factory=dict)
    embedded_with: dict[str, str] = field(default_factory=dict)
    type_loads: int = 0


class FakeUnitOfWork:
    """In-memory IncidentUnitOfWork over a private copy of the store."""

    def __init__(self, store: Store) -> None:
        self.store = store

    def load_types(self) -> TypeSets:
        self.store.type_loads += 1
        return TYPES

    def find_existing(
        self, ids: Sequence[str], content_hashes: Sequence[str]
    ) -> tuple[dict[str, ExistingIncident], dict[str, str]]:
        rows = self.store.rows
        found = {
            i: ExistingIncident(id=i, content_hash=rows[i].content_hash) for i in ids if i in rows
        }
        owners = {r.content_hash: i for i, r in rows.items() if r.content_hash in content_hashes}
        return found, owners

    def insert(self, records: Sequence[IncidentRecord]) -> None:
        self.store.rows.update({r.incident.id: r for r in records})

    def update(self, records: Sequence[IncidentRecord]) -> None:
        for r in records:
            if self.store.rows[r.incident.id].embedding_text_hash != r.embedding_text_hash:
                self.store.embedded_with.pop(r.incident.id, None)
            self.store.rows[r.incident.id] = r

    def lock_pending_embeddings(self, model: str, limit: int) -> list[PendingEmbedding]:
        pending = [i for i in self.store.rows if self.store.embedded_with.get(i) != model]
        return [self._pending(self.store.rows[i]) for i in sorted(pending)[:limit]]

    def save_embeddings(self, rows: Sequence[EmbeddedRow]) -> None:
        self.store.embedded_with.update({r.id: r.model for r in rows})

    def count_pending_embeddings(self, model: str) -> int:
        return sum(1 for i in self.store.rows if self.store.embedded_with.get(i) != model)

    @staticmethod
    def _pending(r: IncidentRecord) -> PendingEmbedding:
        i = r.incident
        return PendingEmbedding(
            id=i.id,
            title=i.title,
            description=i.description,
            resolution_summary=i.resolution_summary,
        )


class FakeRepository:
    """Commits the unit of work on normal exit and discards it on exception."""

    def __init__(self) -> None:
        self.store = Store()

    @contextmanager
    def unit_of_work(self) -> Iterator[FakeUnitOfWork]:
        staged = copy.deepcopy(self.store)
        yield FakeUnitOfWork(staged)
        self.store = staged


class FakeEmbedder:
    """Returns vectors of the configured size, or raises after `fail_after` calls."""

    def __init__(self, fail_after: int | None = None, error: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self._fail_after = fail_after
        self._error = error or EmbeddingUnavailable("openai is down")
        self.vector_count_delta = 0
        self.dimensions = SETTINGS.embedding_dimensions

    def embed_batch(self, texts: Sequence[str]) -> EmbeddingResult:
        if self._fail_after is not None and len(self.calls) >= self._fail_after:
            raise self._error
        self.calls.append(list(texts))
        vectors = [[0.1] * self.dimensions for _ in range(len(texts) + self.vector_count_delta)]
        return EmbeddingResult(vectors=vectors, model=SETTINGS.embedding_model, total_tokens=1)


def item(number: int = 1, **overrides: Any) -> IncidentIn:
    fields: dict[str, Any] = {
        "id": f"inc-{number:05d}",
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "environment": "prod",
        "service": "payments-api",
        "severity": "high",
        "title": f"Pool exhausted {number}",
        "description": "Connections ran out.",
        "resolution_summary": "Raised the pool size.",
        "tags": ["db"],
    }
    return IncidentIn(**{**fields, **overrides})


def ingest(
    repository: FakeRepository, embedder: FakeEmbedder, incidents: list[IncidentIn] | None
) -> IngestResult:
    return IngestService(repository, embedder, SETTINGS).ingest(incidents)


def test_new_incidents_are_ingested_and_embedded_in_batches() -> None:
    repository, embedder = FakeRepository(), FakeEmbedder()

    result = ingest(repository, embedder, [item(n) for n in range(1, 6)])

    assert (result.ingested, result.embedded, result.embedding_pending) == (5, 5, 0)
    assert [len(batch) for batch in embedder.calls] == [2, 2, 1]
    assert result.embedding_error is None


def test_same_body_twice_is_skipped_and_not_embedded_again() -> None:
    repository, embedder = FakeRepository(), FakeEmbedder()
    body = [item(1), item(2)]
    ingest(repository, embedder, body)

    result = ingest(repository, embedder, body)

    assert (result.ingested, result.skipped, result.embedded) == (0, 2, 0)
    assert len(repository.store.rows) == 2
    assert len(embedder.calls) == 1


def test_changed_text_is_updated_and_embedded_again() -> None:
    repository, embedder = FakeRepository(), FakeEmbedder()
    ingest(repository, embedder, [item(1)])

    result = ingest(repository, embedder, [item(1, title="Pool drained")])

    assert (result.updated, result.embedded) == (1, 1)
    assert repository.store.rows["inc-00001"].incident.title == "Pool drained"


def test_invalid_and_duplicate_items_are_rejected_and_not_stored() -> None:
    repository, embedder = FakeRepository(), FakeEmbedder()
    copy_of_first = item(2, title="Pool exhausted 1")

    result = ingest(repository, embedder, [item(1), item(3, service="billing"), copy_of_first])

    assert (result.ingested, result.invalid, result.duplicates) == (1, 1, 1)
    assert result.rejected == [
        Rejection(id="inc-00003", reason="invalid", field="service", value="billing"),
        Rejection(id="inc-00002", reason="duplicate", duplicate_of="inc-00001"),
    ]
    assert set(repository.store.rows) == {"inc-00001"}


@pytest.mark.parametrize(
    "error", [EmbeddingUnavailable("openai is down"), LLMTimeout("embedding timed out")]
)
def test_embedding_failure_keeps_incidents_pending(error: Exception) -> None:
    repository = FakeRepository()

    result = ingest(repository, FakeEmbedder(fail_after=0, error=error), [item(1), item(2)])

    assert (result.ingested, result.embedded, result.embedding_pending) == (2, 0, 2)
    assert result.embedding_error == f"{error}; {RETRY_HINT}"
    assert set(repository.store.rows) == {"inc-00001", "inc-00002"}


def test_failure_after_a_batch_keeps_the_embedded_batch() -> None:
    repository = FakeRepository()

    result = ingest(repository, FakeEmbedder(fail_after=1), [item(n) for n in range(1, 6)])

    assert (result.embedded, result.embedding_pending) == (2, 3)
    assert result.embedding_error is not None


@pytest.mark.parametrize(
    ("vector_count_delta", "dimensions", "detail"),
    [(-1, 3, "expected 2 vectors, got 1"), (0, 4, "embedding dimension is not 3")],
    ids=["wrong-count", "wrong-dimension"],
)
def test_malformed_embedding_response_is_an_error(
    vector_count_delta: int, dimensions: int, detail: str
) -> None:
    repository, embedder = FakeRepository(), FakeEmbedder()
    embedder.vector_count_delta, embedder.dimensions = vector_count_delta, dimensions

    result = ingest(repository, embedder, [item(1), item(2)])

    assert (result.embedded, result.embedding_pending) == (0, 2)
    assert result.embedding_error == f"{detail}; {RETRY_HINT}"


@pytest.mark.parametrize("body", [None, []], ids=["none", "empty"])
def test_empty_body_only_embeds_pending_rows(body: list[IncidentIn] | None) -> None:
    repository = FakeRepository()
    ingest(repository, FakeEmbedder(fail_after=0), [item(1), item(2)])
    loads_before = repository.store.type_loads

    result = ingest(repository, FakeEmbedder(), body)

    assert (result.ingested, result.skipped, result.embedded, result.embedding_pending) == (
        0,
        0,
        2,
        0,
    )
    assert repository.store.type_loads == loads_before
