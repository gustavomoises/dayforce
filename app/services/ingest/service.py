"""The single write path for incidents: write step, then embed every pending row."""

import logging
from collections.abc import Sequence

from app.core.embedding_text import embedding_text
from app.core.errors import EmbeddingInvalid, LLMTimeout, Unavailable
from app.core.fingerprint import text_hash
from app.core.models.prompt import EmbeddingResult
from app.core.models.storage import EmbeddedRow, IncidentRecord
from app.core.ports import EmbeddingClient, IncidentRepository
from app.core.settings import Settings
from app.services.ingest.models import IncidentIn, IngestResult, Rejection
from app.services.ingest.plan import plan_writes, to_record

logger = logging.getLogger(__name__)

RETRY_HINT = "pending rows will be retried on the next ingest call"


class IngestService:
    """Upsert incidents by id, then embed all pending rows in small transactions."""

    def __init__(
        self, repository: IncidentRepository, embedder: EmbeddingClient, settings: Settings
    ) -> None:
        self._repository = repository
        self._embedder = embedder
        self._settings = settings

    def ingest(self, incidents: Sequence[IncidentIn] | None) -> IngestResult:
        """No body, null or [] skips the write step and only embeds pending rows."""
        result = self._write(incidents) if incidents else IngestResult()
        result.embedded, result.embedding_error = self._embed_pending()
        with self._repository.unit_of_work() as uow:
            result.embedding_pending = uow.count_pending_embeddings(self._settings.embedding_model)
        logger.info("ingest finished", extra=result.model_dump(exclude={"rejected"}))
        return result

    def _write(self, incidents: Sequence[IncidentIn]) -> IngestResult:
        with self._repository.unit_of_work() as uow:
            types = uow.load_types()
            checked = [to_record(item, types) for item in incidents]
            invalid = [item for item in checked if isinstance(item, Rejection)]
            records = [item for item in checked if isinstance(item, IncidentRecord)]
            existing, owner_by_hash = uow.find_existing(
                [r.incident.id for r in records], [r.content_hash for r in records]
            )
            plan = plan_writes(records, existing, owner_by_hash)
            if plan.inserts:
                uow.insert(plan.inserts)
            if plan.updates:
                uow.update(plan.updates)
        return IngestResult(
            ingested=plan.ingested,
            updated=plan.updated,
            skipped=plan.skipped,
            duplicates=len(plan.duplicates),
            invalid=len(invalid),
            rejected=[*invalid, *plan.duplicates],
        )

    def _embed_pending(self) -> tuple[int, str | None]:
        """Embed batches until none are pending; an embedding failure stops, never undoes."""
        embedded = 0
        while True:
            try:
                count = self._embed_next_batch()
            except (Unavailable, LLMTimeout, EmbeddingInvalid) as exc:
                logger.warning(
                    "ingest embedding stopped", extra={"error": exc.code, "embedded": embedded}
                )
                return embedded, f"{exc.detail}; {RETRY_HINT}"
            if count == 0:
                return embedded, None
            embedded += count

    def _embed_next_batch(self) -> int:
        model = self._settings.embedding_model
        with self._repository.unit_of_work() as uow:
            pending = uow.lock_pending_embeddings(model, self._settings.embedding_batch_size)
            if not pending:
                return 0
            texts = [embedding_text(p.title, p.description, p.resolution_summary) for p in pending]
            result = self._embedder.embed_batch(texts)
            self._check_vectors(result, len(texts))
            uow.save_embeddings(
                [
                    EmbeddedRow(id=p.id, vector=v, model=model, embedding_text_hash=text_hash(t))
                    for p, t, v in zip(pending, texts, result.vectors, strict=True)
                ]
            )
        return len(pending)

    def _check_vectors(self, result: EmbeddingResult, expected: int) -> None:
        dimensions = self._settings.embedding_dimensions
        if len(result.vectors) != expected:
            raise EmbeddingInvalid(f"expected {expected} vectors, got {len(result.vectors)}")
        if any(len(vector) != dimensions for vector in result.vectors):
            raise EmbeddingInvalid(f"embedding dimension is not {dimensions}")
