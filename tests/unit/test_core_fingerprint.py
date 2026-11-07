"""Content hash, text hash and query hash."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.fingerprint import content_hash, query_hash, text_hash
from app.core.models.incident import Environment, Incident, Severity


def incident(**overrides: Any) -> Incident:
    fields: dict[str, Any] = {
        "id": "inc-00001",
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "environment": Environment.PROD,
        "service": "payments-api",
        "severity": Severity.HIGH,
        "title": "Pool exhausted",
        "description": "Connections ran out.",
        "resolution_summary": "Raised the pool size.",
        "tags": ("db", "pool"),
    }
    return Incident(**{**fields, **overrides})


def test_hash_ignores_id_and_dates() -> None:
    moved = incident(id="inc-00002", created_at=datetime(2026, 9, 9, tzinfo=UTC))

    assert content_hash(moved) == content_hash(incident())


@pytest.mark.parametrize(
    "title",
    ["POOL EXHAUSTED", "Pool   exhausted!", "  pool, exhausted. ", "Ｐｏｏｌ exhausted"],
)
def test_case_punctuation_spacing_and_width_do_not_change_the_hash(title: str) -> None:
    assert content_hash(incident(title=title)) == content_hash(incident())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("service", "auth-service"),
        ("environment", Environment.DEV),
        ("severity", Severity.LOW),
        ("title", "Pool drained"),
        ("description", "Other text."),
        ("resolution_summary", "Restarted."),
        ("tags", ("db",)),
    ],
)
def test_every_hashed_field_changes_the_hash(field: str, value: Any) -> None:
    assert content_hash(incident(**{field: value})) != content_hash(incident())


def test_hash_is_sha256_of_sorted_json_without_empty_fields() -> None:
    canonical = {
        "environment": "prod",
        "service": "payments-api",
        "severity": "high",
        "title": "pool exhausted",
    }
    expected = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    bare = incident(description="", resolution_summary="  ", tags=())

    assert content_hash(bare) == expected


def test_text_hash_is_sha256_of_the_exact_text() -> None:
    assert text_hash("Title: X") == hashlib.sha256(b"Title: X").hexdigest()
    assert text_hash("Title: X") != text_hash("title: x")


def test_query_hash_depends_on_the_model() -> None:
    assert query_hash("pool", "model-a") != query_hash("pool", "model-b")
