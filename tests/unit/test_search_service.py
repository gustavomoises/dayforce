"""SearchService: one path for search and candidates, limit cap, stored query vectors, offset."""

from collections.abc import Sequence

import pytest

from app.core.errors import InvalidInput
from app.core.fingerprint import query_hash
from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment
from app.core.models.prompt import EmbeddingResult
from app.core.models.search import SearchHit, SearchPage, SearchQuery
from app.core.settings import Settings
from app.services.search.service import SearchService

SETTINGS = Settings()
FILTERS = SearchFilters(environment=Environment.PROD, service="payments-api", tags=("db",))
HIT = SearchHit(id="inc-00001", title="Pool exhausted", snippet="Connections ran out", score=0.5)
STORED_VECTOR = [0.5, 0.5]


class FakeRepository:
    """IncidentRepository that records search queries and keeps query vectors in memory."""

    def __init__(self, stored: dict[str, list[float]] | None = None) -> None:
        self.queries: list[SearchQuery] = []
        self.vectors = dict(stored or {})
        self.saved: list[tuple[str, str, list[float]]] = []

    def search(self, query: SearchQuery) -> SearchPage:
        self.queries.append(query)
        return SearchPage(total=42, hits=[HIT])

    def get_query_embedding(self, query_hash: str) -> list[float] | None:
        return self.vectors.get(query_hash)

    def save_query_embedding(self, query_hash: str, model: str, vector: list[float]) -> None:
        self.saved.append((query_hash, model, vector))
        self.vectors[query_hash] = vector


class FakeEmbedder:
    """EmbeddingClient that counts calls and returns one fixed vector per text."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_batch(self, texts: Sequence[str]) -> EmbeddingResult:
        self.calls.append(list(texts))
        return EmbeddingResult(vectors=[[0.1, 0.2] for _ in texts], model="m", total_tokens=1)


def build(
    stored: dict[str, list[float]] | None = None, settings: Settings = SETTINGS
) -> tuple[SearchService, FakeRepository, FakeEmbedder]:
    repository, embedder = FakeRepository(stored), FakeEmbedder()
    return SearchService(repository, embedder, settings), repository, embedder


@pytest.mark.parametrize(
    ("limit", "expected"),
    [(None, SETTINGS.search_default_limit), (7, 7), (1000, SETTINGS.search_max_limit)],
    ids=["default", "given", "capped"],
)
def test_search_limit_defaults_and_is_capped(limit: int | None, expected: int) -> None:
    service, repository, _ = build()

    service.search(FILTERS, "pool exhausted", limit)

    assert repository.queries[0].limit == expected


def test_search_rejects_a_limit_below_one() -> None:
    service, _, _ = build()

    with pytest.raises(InvalidInput):
        service.search(FILTERS, "pool", 0)


def test_search_and_candidates_build_the_same_query() -> None:
    service, repository, _ = build()

    service.search(FILTERS, "pool exhausted", 15)
    service.candidates(FILTERS, "pool exhausted", 15)

    assert repository.queries[0] == repository.queries[1]


def test_candidates_pass_the_offset_and_reach_past_it() -> None:
    service, repository, _ = build()

    service.candidates(FILTERS, "pool", k=15, offset=45)

    query = repository.queries[0]
    assert (query.limit, query.offset) == (15, 45)
    assert query.branch_limit == 60


def test_query_settings_are_passed_to_the_repository() -> None:
    service, repository, _ = build()

    service.search(FILTERS, "pool")

    query = repository.queries[0]
    assert query.filters == FILTERS
    assert (query.branch_limit, query.min_similarity, query.rrf_k) == (
        SETTINGS.search_branch_limit,
        SETTINGS.vector_min_similarity,
        SETTINGS.rrf_k,
    )


def test_stored_query_vector_is_reused_without_embedding() -> None:
    key = query_hash("pool exhausted", SETTINGS.embedding_model)
    service, repository, embedder = build(stored={key: STORED_VECTOR})

    service.search(FILTERS, "pool exhausted")

    assert repository.queries[0].vector == STORED_VECTOR
    assert embedder.calls == []
    assert repository.saved == []


def test_new_query_is_embedded_once_and_stored() -> None:
    service, repository, embedder = build()

    service.search(FILTERS, "pool exhausted")
    service.candidates(FILTERS, "pool exhausted", 5)

    key = query_hash("pool exhausted", SETTINGS.embedding_model)
    assert embedder.calls == [["pool exhausted"]]
    assert repository.saved == [(key, SETTINGS.embedding_model, [0.1, 0.2])]
    assert repository.queries[1].vector == [0.1, 0.2]


def test_query_whitespace_is_collapsed_before_hashing() -> None:
    service, repository, embedder = build()

    service.search(FILTERS, "  Pool   exhausted ")

    assert repository.queries[0].text == "Pool exhausted"
    assert embedder.calls == [["Pool exhausted"]]


@pytest.mark.parametrize("q", [None, "", "   "], ids=["none", "empty", "blank"])
def test_empty_query_filters_only_and_skips_embedding(q: str | None) -> None:
    service, repository, embedder = build()

    service.search(FILTERS, q)

    query = repository.queries[0]
    assert (query.text, query.vector) == (None, None)
    assert embedder.calls == []


def test_result_keeps_the_real_total_and_the_page() -> None:
    service, _, _ = build()

    result = service.search(FILTERS, "pool", 1)

    assert (result.total, result.results) == (42, [HIT])
