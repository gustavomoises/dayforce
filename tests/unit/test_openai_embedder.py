"""OpenAIEmbedder: one request per batch, vectors in input order, count and dimension checks."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import openai
import pytest
from openai.types import CreateEmbeddingResponse

from app.core.errors import EmbeddingInvalid, EmbeddingUnavailable, LLMTimeout
from app.core.settings import Settings
from app.support.llm import openai_embedder
from app.support.llm.openai_embedder import OpenAIEmbedder

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
SETTINGS = Settings(embedding_dimensions=3, embedding_timeout_seconds=7)


class FakeEmbeddings:
    def __init__(self, result: CreateEmbeddingResponse | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> CreateEmbeddingResponse:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeOpenAI:
    def __init__(self, result: CreateEmbeddingResponse | Exception) -> None:
        self.embeddings = FakeEmbeddings(result)


class FakeObservation:
    def update(self, **kwargs: Any) -> None:
        """Accepts the recorded model, output and usage."""


class FakeLangfuse:
    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Iterator[FakeObservation]:
        yield FakeObservation()


@pytest.fixture(autouse=True)
def langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openai_embedder, "get_client", FakeLangfuse)


def embeddings(vectors: dict[int, list[float]]) -> CreateEmbeddingResponse:
    return CreateEmbeddingResponse.model_validate(
        {
            "object": "list",
            "model": "text-embedding-3-small",
            "data": [
                {"object": "embedding", "index": index, "embedding": vector}
                for index, vector in vectors.items()
            ],
            "usage": {"prompt_tokens": 9, "total_tokens": 9},
        }
    )


def embed(result: CreateEmbeddingResponse | Exception, texts: list[str]) -> Any:
    return OpenAIEmbedder(FakeOpenAI(result), SETTINGS).embed_batch(texts)


def test_batch_is_sent_in_one_request_with_model_dimensions_and_timeout() -> None:
    fake = FakeOpenAI(embeddings({0: [0.1, 0.2, 0.3], 1: [0.4, 0.5, 0.6]}))

    OpenAIEmbedder(fake, SETTINGS).embed_batch(("a", "b"))

    assert fake.embeddings.calls == [
        {"input": ["a", "b"], "model": "text-embedding-3-small", "dimensions": 3, "timeout": 7}
    ]


def test_vectors_are_returned_in_input_order() -> None:
    result = embed(embeddings({1: [1.0, 1.0, 1.0], 0: [0.0, 0.0, 0.0]}), ["first", "second"])

    assert result.vectors == [[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]
    assert (result.model, result.total_tokens) == ("text-embedding-3-small", 9)


@pytest.mark.parametrize(
    "vectors",
    [{0: [0.1, 0.2, 0.3]}, {0: [0.1, 0.2, 0.3], 1: [0.1, 0.2, 0.3], 2: [0.1, 0.2, 0.3]}],
    ids=["too-few", "too-many"],
)
def test_wrong_vector_count_is_invalid(vectors: dict[int, list[float]]) -> None:
    with pytest.raises(EmbeddingInvalid, match="for 2 texts"):
        embed(embeddings(vectors), ["a", "b"])


def test_wrong_indexes_are_invalid() -> None:
    with pytest.raises(EmbeddingInvalid):
        embed(embeddings({0: [0.1, 0.2, 0.3], 5: [0.1, 0.2, 0.3]}), ["a", "b"])


def test_wrong_dimension_is_invalid_and_names_the_positions() -> None:
    with pytest.raises(EmbeddingInvalid, match=r"without 3 dimensions at positions \[1\]"):
        embed(embeddings({0: [0.1, 0.2, 0.3], 1: [0.1, 0.2]}), ["a", "b"])


def test_timeout_names_the_embedding_setting() -> None:
    with pytest.raises(LLMTimeout, match="EMBEDDING_TIMEOUT_SECONDS") as caught:
        embed(openai.APITimeoutError(request=REQUEST), ["a"])

    assert "7 s" in caught.value.detail


def test_connection_error_is_embedding_unavailable() -> None:
    with pytest.raises(EmbeddingUnavailable, match="unreachable"):
        embed(openai.APIConnectionError(request=REQUEST), ["a"])
