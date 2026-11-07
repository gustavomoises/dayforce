"""Live tests against a running API; run with `API_BASE_URL=... pytest -m live`.

They only read, or re-ingest an existing unchanged incident, so no stored data changes.
"""

import os
import re
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

pytestmark = pytest.mark.live

CORRELATION_HEADER = "X-Correlation-ID"
DEFAULT_TIMEOUT = 30.0
ASSIST_TIMEOUT = 180.0
TRACE_WAIT_SECONDS = 30.0
TRACE_POLL_SECONDS = 3.0
MAX_RELEVANT = 5
SEARCH_PARAMS = {"q": "database connection timeouts", "service": "payments-api"}
ASSIST_BODY = {"question": "database connection timeouts in payments"}
CITED_ID = re.compile(r"inc-\d{5}")


@pytest.fixture(scope="module")
def client() -> Iterator[httpx.Client]:
    base_url = os.environ.get("API_BASE_URL")
    if not base_url:
        pytest.skip("API_BASE_URL is not set")
    with httpx.Client(base_url=base_url, timeout=DEFAULT_TIMEOUT) as client:
        yield client


@pytest.fixture(scope="module")
def assist_response(client: httpx.Client) -> httpx.Response:
    """One /assist call shared by the assist and trace tests, since each takes up to ~100 s."""
    return call(client, "POST", "/assist", "assist", json=ASSIST_BODY, timeout=ASSIST_TIMEOUT)


def call(client: httpx.Client, method: str, path: str, test: str, **kwargs: Any) -> httpx.Response:
    """Send a request with a fresh correlation id and check that the API echoes it."""
    correlation_id = f"live-{test}-{uuid.uuid4().hex[:8]}"
    response = client.request(method, path, headers={CORRELATION_HEADER: correlation_id}, **kwargs)
    assert response.headers.get(CORRELATION_HEADER) == correlation_id
    return response


def first_search_id(client: httpx.Client) -> str:
    response = call(client, "GET", "/search", "search-id", params=SEARCH_PARAMS)
    assert response.status_code == 200, response.text
    return response.json()["results"][0]["id"]


def test_health_is_ok(client: httpx.Client) -> None:
    response = call(client, "GET", "/health", "health")
    assert response.status_code == 200, response.text


def test_search_returns_hits_within_total(client: httpx.Client) -> None:
    response = call(client, "GET", "/search", "search", params=SEARCH_PARAMS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["results"]
    assert body["total"] >= len(body["results"])
    for hit in body["results"]:
        assert hit["id"] and hit["title"] and hit["snippet"]


def test_incident_details_return_full_record(client: httpx.Client) -> None:
    incident_id = first_search_id(client)
    response = call(client, "GET", f"/incidents/{incident_id}", "incident")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == incident_id
    expected = {
        "id",
        "created_at",
        "environment",
        "service",
        "severity",
        "title",
        "description",
        "resolution_summary",
        "tags",
    }
    assert set(body) == expected


def test_unknown_incident_is_404_with_error_body(client: httpx.Client) -> None:
    response = call(client, "GET", "/incidents/inc-99999", "incident-404")
    assert response.status_code == 404, response.text
    body = response.json()
    assert set(body) == {"error", "detail", "correlation_id"}
    assert body["correlation_id"] == response.headers[CORRELATION_HEADER]


def test_reingesting_unchanged_incident_twice_skips(client: httpx.Client) -> None:
    incident_id = first_search_id(client)
    incident = call(client, "GET", f"/incidents/{incident_id}", "ingest-source").json()
    for attempt in range(2):
        response = call(client, "POST", "/ingest", f"ingest-{attempt}", json=[incident])
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["skipped"], body["ingested"], body["updated"]) == (1, 0, 0), body


def test_ingest_without_body_returns_counts(client: httpx.Client) -> None:
    response = call(client, "POST", "/ingest", "ingest-empty")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"ingested", "updated", "skipped", "embedded", "embedding_pending"} <= set(body)


def test_catalog_maps_services_to_events(client: httpx.Client) -> None:
    response = call(client, "GET", "/catalog", "catalog")
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict) and body
    assert all(isinstance(events, list) and events for events in body.values())


def test_assist_answer_is_grounded_in_candidates(assist_response: httpx.Response) -> None:
    assert assist_response.status_code == 200, assist_response.text
    body = assist_response.json()
    assert body["status"] in {"answered", "no_relevant_incidents"}
    assert len(body["relevant_incidents"]) <= MAX_RELEVANT
    candidate_ids = {candidate["id"] for candidate in body["candidates"]}
    relevant_ids = {candidate["id"] for candidate in body["candidates"] if candidate["relevant"]}
    for incident in body["relevant_incidents"]:
        assert incident["id"] in candidate_ids
        assert {related["id"] for related in incident["related"]} <= candidate_ids
    for step in body["next_steps"]:
        assert set(CITED_ID.findall(step)) <= relevant_ids, step


def test_assist_rejects_empty_question(client: httpx.Client) -> None:
    response = call(client, "POST", "/assist", "assist-422", json={"question": ""})
    assert response.status_code == 422, response.text
    assert response.json()["error"] == "invalid_input"


def test_debug_trace_of_assist_call(client: httpx.Client, assist_response: httpx.Response) -> None:
    correlation_id = assist_response.headers[CORRELATION_HEADER]
    deadline = time.monotonic() + TRACE_WAIT_SECONDS
    while True:
        response = call(client, "GET", f"/debug/trace/{correlation_id}", "trace")
        # Langfuse ingests asynchronously, so a fresh trace can be briefly missing.
        not_ready = response.status_code == 404 and response.json()["error"] == "trace_not_ready"
        if not not_ready or time.monotonic() >= deadline:
            break
        time.sleep(TRACE_POLL_SECONDS)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["correlation_id"] == correlation_id
    assert body["observations"]
