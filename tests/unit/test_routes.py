"""Routes through TestClient with dependency_overrides: 422, 404, error bodies, correlation IDs."""

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import assist, catalog, deps, health, incidents, ingest, search
from app.core.app_env import resolve_app_env
from app.core.errors import LLMOutputInvalid, NotFound
from app.core.models.catalog import Catalog
from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment, Incident, Severity
from app.core.models.trace import TraceView
from app.services.assist.models.request import AssistRequest
from app.services.assist.models.response import AssistResponse
from app.services.ingest.models import IncidentIn, IngestResult
from app.services.search.models import SearchResult
from app.support.tracing.correlation import CORRELATION_HEADER
from main import create_app

KNOWN = Incident(
    id="inc-00001",
    created_at=datetime(2026, 3, 1, tzinfo=UTC),
    environment=Environment.PROD,
    service="payments-api",
    severity=Severity.HIGH,
    title="Pool exhausted",
    description="Connections ran out.",
    resolution_summary="Raised the pool size.",
    tags=("db", "pool"),
)
TRACED_ROUTES = (assist, catalog, health, incidents, ingest, search)
ERROR_KEYS = {"error", "detail", "correlation_id"}


class FakeServices:
    """Every service and client a route can get, recording what the routes pass in."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.failure: Exception | None = None

    def _record(self, name: str, value: Any) -> None:
        self.calls.append((name, value))
        if self.failure is not None:
            raise self.failure

    def get(self, incident_id: str) -> Incident:
        self._record("incident", incident_id)
        if incident_id != KNOWN.id:
            raise NotFound(f"incident {incident_id} not found")
        return KNOWN

    def search(self, filters: SearchFilters, q: str | None, limit: int | None) -> SearchResult:
        self._record("search", (filters, q, limit))
        return SearchResult(total=0, results=[])

    def assist(self, request: AssistRequest, label: str) -> AssistResponse:
        self._record("assist", (request, label))
        return AssistResponse(
            status="no_relevant_incidents",
            relevant_incidents=[],
            candidates=[],
            next_steps=[],
            customer_draft="",
            missing_info=["What is the exact error message?"],
        )

    def ingest(self, items: list[IncidentIn] | None) -> IngestResult:
        self._record("ingest", items)
        return IngestResult(ingested=len(items or []))

    def catalog(self) -> Catalog:
        self._record("catalog", None)
        return Catalog({"api-gateway": []})

    def trace(self, correlation_id: str) -> TraceView:
        self._record("trace", correlation_id)
        return TraceView(
            correlation_id=correlation_id, trace_id="t", langfuse_url="u", observations=[]
        )

    def ping(self) -> bool:
        return True


class FakeCatalog:
    def __init__(self, services: FakeServices) -> None:
        self.get = services.catalog


class FakeTraceReader:
    def __init__(self, services: FakeServices) -> None:
        self.get = services.trace


def fake_run_traced(
    langfuse: object,
    background_tasks: object,
    name: str,
    call: Callable[[str], Any],
    environment: Environment | None = None,
    input: dict[str, Any] | None = None,
) -> Any:
    """run_traced without Langfuse: resolve APP_ENV and call the handler."""
    return call(resolve_app_env(environment))


@pytest.fixture
def services() -> FakeServices:
    return FakeServices()


@pytest.fixture
def app(services: FakeServices, monkeypatch: pytest.MonkeyPatch) -> Iterator[FastAPI]:
    for module in TRACED_ROUTES:
        monkeypatch.setattr(module, "run_traced", fake_run_traced)
    application = create_app()
    overrides: dict[Callable[..., Any], Callable[[], Any]] = {
        deps.get_langfuse: lambda: None,
        deps.get_ingest_service: lambda: services,
        deps.get_search_service: lambda: services,
        deps.get_incident_service: lambda: services,
        deps.get_assist_service: lambda: services,
        deps.get_catalog_service: lambda: FakeCatalog(services),
        deps.get_trace_reader: lambda: FakeTraceReader(services),
        deps.get_repository: lambda: services,
    }
    application.dependency_overrides.update(overrides)
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """No `with` block, so the lifespan never builds the real container."""
    return TestClient(app, raise_server_exceptions=False)


def incident_body(number: int = 1) -> dict[str, Any]:
    return {
        "id": f"inc-{number:05d}",
        "created_at": "2026-03-01T00:00:00Z",
        "environment": "prod",
        "service": "payments-api",
        "severity": "high",
        "title": "Pool exhausted",
        "description": "Connections ran out.",
        "resolution_summary": "Raised the pool size.",
        "tags": ["db"],
    }


def assert_error_body(body: dict[str, Any], error: str) -> None:
    assert set(body) == ERROR_KEYS
    assert body["error"] == error
    assert "Traceback" not in str(body)


@pytest.mark.parametrize(
    "body",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 2001},
        {"question": "pool", "candidate_multiplier": 0},
        {"question": "pool", "candidate_multiplier": 6},
        {"question": "pool", "environment": "production"},
        {},
    ],
    ids=["empty", "blank", "too-long", "multiplier-0", "multiplier-6", "bad-env", "missing"],
)
def test_assist_rejects_bad_input_with_422(
    client: TestClient, services: FakeServices, body: dict[str, Any]
) -> None:
    response = client.post("/assist", json=body)

    assert response.status_code == 422
    assert_error_body(response.json(), "invalid_input")
    assert services.calls == []


@pytest.mark.parametrize(
    "params",
    [{"environment": "production"}, {"severity": "urgent"}, {"limit": 0}],
    ids=["bad-env", "bad-severity", "limit-0"],
)
def test_search_rejects_bad_filters_with_422(
    client: TestClient, services: FakeServices, params: dict[str, Any]
) -> None:
    response = client.get("/search", params={"q": "pool", **params})

    assert response.status_code == 422
    assert services.calls == []


@pytest.mark.parametrize(
    "body",
    [
        [incident_body(n) for n in range(1, 502)],
        {"id": "inc-00001"},
        [{**incident_body(), "id": "INC-1"}],
        [{**incident_body(), "created_at": "yesterday"}],
        [{**incident_body(), "title": "x" * 201}],
    ],
    ids=["501-items", "not-an-array", "bad-id", "bad-date", "long-title"],
)
def test_ingest_rejects_bad_bodies_with_422(
    client: TestClient, services: FakeServices, body: Any
) -> None:
    response = client.post("/ingest", json=body)

    assert response.status_code == 422
    assert_error_body(response.json(), "invalid_input")
    assert services.calls == []


def test_ingest_accepts_500_items(client: TestClient, services: FakeServices) -> None:
    response = client.post("/ingest", json=[incident_body(n) for n in range(1, 501)])

    assert response.status_code == 200
    assert response.json()["ingested"] == 500


def test_ingest_without_a_body_only_embeds(client: TestClient, services: FakeServices) -> None:
    response = client.post("/ingest")

    assert response.status_code == 200
    assert services.calls == [("ingest", None)]


def test_unknown_incident_is_404_with_the_error_body(client: TestClient) -> None:
    response = client.get("/incidents/inc-99999", headers={CORRELATION_HEADER: "req-404"})

    assert response.status_code == 404
    body = response.json()
    assert_error_body(body, "not_found")
    assert body["correlation_id"] == "req-404"
    assert "inc-99999" in body["detail"]


def test_known_incident_returns_the_full_record(client: TestClient) -> None:
    response = client.get("/incidents/inc-00001")

    assert response.status_code == 200
    assert Incident.model_validate(response.json()) == KNOWN


def test_correlation_id_header_is_echoed(client: TestClient) -> None:
    response = client.get("/incidents/inc-00001", headers={CORRELATION_HEADER: "abc-123"})

    assert response.headers[CORRELATION_HEADER] == "abc-123"


@pytest.mark.parametrize("header", [None, "not valid!"], ids=["missing", "malformed"])
def test_correlation_id_is_generated_when_missing_or_malformed(
    client: TestClient, header: str | None
) -> None:
    headers = {CORRELATION_HEADER: header} if header else {}

    response = client.get("/incidents/inc-00001", headers=headers)

    assert uuid.UUID(response.headers[CORRELATION_HEADER]).version == 4


def test_upstream_error_maps_to_its_status(client: TestClient, services: FakeServices) -> None:
    services.failure = LLMOutputInvalid("events: field required")

    response = client.post("/assist", json={"question": "pool"})

    assert response.status_code == 502
    assert_error_body(response.json(), "llm_output_invalid")
    assert response.json()["correlation_id"] == response.headers[CORRELATION_HEADER]


def test_unexpected_error_hides_the_details(client: TestClient, services: FakeServices) -> None:
    services.failure = RuntimeError("secret-token leaked in a library error")

    response = client.post("/assist", json={"question": "pool"})

    assert response.status_code == 500
    body = response.json()
    assert_error_body(body, "internal_error")
    assert "secret-token" not in response.text


def test_unexpected_error_keeps_the_correlation_id(
    client: TestClient, services: FakeServices
) -> None:
    services.failure = RuntimeError("boom")

    response = client.post("/assist", json={"question": "pool"}, headers={CORRELATION_HEADER: "c1"})

    assert response.json()["correlation_id"] == "c1"
    assert response.headers.get(CORRELATION_HEADER) == "c1"


@pytest.mark.parametrize(
    ("environment", "label"),
    [(None, "production"), ("prod", "production"), ("dev", "dev"), ("stage", "stage")],
)
def test_assist_label_follows_the_environment_filter(
    client: TestClient, services: FakeServices, environment: str | None, label: str
) -> None:
    body = {"question": " pool exhausted ", "environment": environment}

    response = client.post("/assist", json=body)

    assert response.status_code == 200
    request, used_label = services.calls[0][1]
    assert (request.question, used_label) == ("pool exhausted", label)


def test_search_normalizes_filters_before_the_service(
    client: TestClient, services: FakeServices
) -> None:
    params = {"q": "pool", "service": " Payments-API ", "tags": "Pool, db,,DB", "limit": 5}

    response = client.get("/search", params=params)

    assert response.status_code == 200
    assert services.calls == [
        ("search", (SearchFilters(service="payments-api", tags=("db", "pool")), "pool", 5))
    ]


@pytest.mark.parametrize(
    ("path", "call"),
    [("/catalog", "catalog"), ("/debug/trace/abc-123", "trace")],
)
def test_read_routes_use_their_injected_service(
    client: TestClient, services: FakeServices, path: str, call: str
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert services.calls[0][0] == call


def test_health_reports_database_reachability(client: TestClient) -> None:
    response = client.get("/health")

    assert response.json() == {"status": "ok", "database": True}
