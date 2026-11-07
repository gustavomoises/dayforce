"""Hybrid search: one code path for GET /search and the /assist candidates."""

import logging

from app.core.errors import InvalidInput
from app.core.fingerprint import query_hash
from app.core.models.filters import SearchFilters
from app.core.models.search import SearchQuery
from app.core.normalize import normalize_query
from app.core.ports import EmbeddingClient, IncidentRepository
from app.core.settings import Settings
from app.services.search.models import SearchResult
from app.support.tracing.span import traced

logger = logging.getLogger(__name__)


class SearchService:
    """Full-text and vector search with the same filters, fused by the repository."""

    def __init__(
        self, repository: IncidentRepository, embedder: EmbeddingClient, settings: Settings
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._settings = settings

    @traced(name="tool:search")
    def search(
        self, filters: SearchFilters, q: str | None, limit: int | None = None
    ) -> SearchResult:
        """GET /search: `limit` defaults to SEARCH_DEFAULT_LIMIT, capped at SEARCH_MAX_LIMIT."""
        limit = self._settings.search_default_limit if limit is None else limit
        if limit < 1:
            raise InvalidInput("limit must be at least 1")
        return self._run(filters, q, min(limit, self._settings.search_max_limit))

    @traced(name="tool:search")
    def candidates(self, filters: SearchFilters, q: str, k: int) -> SearchResult:
        """The top `k` incidents for /assist, through the same path as `search`."""
        return self._run(filters, q, k)

    def _run(self, filters: SearchFilters, q: str | None, limit: int) -> SearchResult:
        text = normalize_query(q or "") or None
        filter_values = filters.model_dump(mode="json")
        logger.info(
            "step tool:search input", extra={"q": text, "filters": filter_values, "limit": limit}
        )
        page = self._repository.search(
            SearchQuery(
                filters=filters,
                text=text,
                vector=self._query_vector(text) if text else None,
                limit=limit,
                branch_limit=self._settings.search_branch_limit,
                min_similarity=self._settings.vector_min_similarity,
                rrf_k=self._settings.rrf_k,
            )
        )
        logger.info(
            "step tool:search output",
            extra={"io": "output", "hits": page.total, "top_ids": [hit.id for hit in page.hits]},
        )
        return SearchResult(total=page.total, results=page.hits)

    def _query_vector(self, text: str) -> list[float]:
        """Reuse the stored vector so the same query always ranks the same way."""
        model = self._settings.embedding_model
        key = query_hash(text, model)
        vector = self._repository.get_query_embedding(key)
        if vector is None:
            vector = self._embedder.embed_batch([text]).vectors[0]
            self._repository.save_query_embedding(key, model, vector)
        return vector
