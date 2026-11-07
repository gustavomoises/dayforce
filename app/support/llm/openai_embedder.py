"""EmbeddingClient on the OpenAI embeddings API, recorded as a Langfuse embedding."""

from collections.abc import Sequence

import openai
from langfuse import get_client
from openai.types import CreateEmbeddingResponse

from app.core.errors import EmbeddingInvalid, EmbeddingUnavailable
from app.core.models.prompt import EmbeddingResult
from app.core.settings import Settings
from app.support.llm.errors import to_domain_error


class OpenAIEmbedder:
    """Embed one batch of texts per OpenAI request and check every vector."""

    def __init__(self, client: openai.OpenAI, settings: Settings) -> None:
        self._client = client
        self._model = settings.embedding_model
        self._dimensions = settings.embedding_dimensions
        self._timeout = settings.embedding_timeout_seconds

    def embed_batch(self, texts: Sequence[str]) -> EmbeddingResult:
        with get_client().start_as_current_observation(
            name="openai.embeddings",
            as_type="embedding",
            model=self._model,
            input={"count": len(texts)},
        ) as observation:
            response = self._create(texts)
            observation.update(
                model=response.model,
                output={"count": len(response.data)},
                usage_details={"input": response.usage.prompt_tokens},
            )
            vectors = self._vectors(response, len(texts))
        return EmbeddingResult(
            vectors=vectors, model=response.model, total_tokens=response.usage.total_tokens
        )

    def _create(self, texts: Sequence[str]) -> CreateEmbeddingResponse:
        try:
            return self._client.embeddings.create(
                input=list(texts),
                model=self._model,
                dimensions=self._dimensions,
                timeout=self._timeout,
            )
        except openai.OpenAIError as exc:
            raise to_domain_error(exc, EmbeddingUnavailable, self._timeout) from exc

    def _vectors(self, response: CreateEmbeddingResponse, expected: int) -> list[list[float]]:
        """Vectors in input order; wrong count, order or dimension is an error."""
        items = sorted(response.data, key=lambda item: item.index)
        if [item.index for item in items] != list(range(expected)):
            raise EmbeddingInvalid(f"OpenAI returned {len(items)} embeddings for {expected} texts")
        wrong = [item.index for item in items if len(item.embedding) != self._dimensions]
        if wrong:
            raise EmbeddingInvalid(
                f"OpenAI returned embeddings without {self._dimensions} dimensions "
                f"at positions {wrong[:5]}"
            )
        return [item.embedding for item in items]
