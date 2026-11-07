"""Correlation id: header reuse or generation, the contextvar scope and the ASGI middleware."""

import uuid

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.support.tracing.context import correlation_scope, get_correlation_id
from app.support.tracing.correlation import (
    CORRELATION_HEADER,
    CorrelationMiddleware,
    resolve_correlation_id,
)


def is_uuid4(value: str) -> bool:
    return uuid.UUID(value).version == 4


def echo_correlation_id(_: Request) -> PlainTextResponse:
    return PlainTextResponse(get_correlation_id() or "")


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=[Route("/", echo_correlation_id)])
    return TestClient(CorrelationMiddleware(app))


@pytest.mark.parametrize("header", ["abc-123", "req_1.2", "A" * 64])
def test_well_formed_header_is_reused(header: str) -> None:
    assert resolve_correlation_id(header) == header


@pytest.mark.parametrize("header", [None, "", "a" * 65, "has space", "bad/slash", "ünicode"])
def test_missing_or_malformed_header_gets_a_new_uuid(header: str | None) -> None:
    assert is_uuid4(resolve_correlation_id(header))


def test_scope_sets_and_restores_the_correlation_id() -> None:
    with correlation_scope("outer"):
        with correlation_scope("inner"):
            assert get_correlation_id() == "inner"
        assert get_correlation_id() == "outer"
    assert get_correlation_id() is None


def test_scope_restores_the_previous_value_after_an_error() -> None:
    with pytest.raises(RuntimeError), correlation_scope("failing"):
        raise RuntimeError("boom")

    assert get_correlation_id() is None


def test_middleware_echoes_the_request_header(client: TestClient) -> None:
    response = client.get("/", headers={CORRELATION_HEADER: "req-42"})

    assert response.headers[CORRELATION_HEADER] == "req-42"
    assert response.text == "req-42"


def test_middleware_generates_an_id_visible_to_the_handler(client: TestClient) -> None:
    response = client.get("/")

    correlation_id = response.headers[CORRELATION_HEADER]
    assert is_uuid4(correlation_id)
    assert response.text == correlation_id
