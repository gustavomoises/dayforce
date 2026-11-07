"""Ingest plan: normalization, type checks and the per-record outcome."""

from datetime import UTC, datetime
from typing import Any

import pytest

from app.core.models.storage import ExistingIncident, IncidentRecord, TypeSets
from app.services.ingest.models import IncidentIn, Rejection
from app.services.ingest.plan import plan_writes, to_record

TYPES = TypeSets(
    environments=frozenset({"dev", "qa", "stage", "prod"}),
    services=frozenset({"payments-api", "auth-service"}),
    severities=frozenset({"critical", "high", "medium", "low"}),
)


def item(**overrides: Any) -> IncidentIn:
    fields: dict[str, Any] = {
        "id": "inc-00001",
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "environment": "prod",
        "service": "payments-api",
        "severity": "high",
        "title": "Pool exhausted",
        "description": "Connections ran out.",
        "resolution_summary": "Raised the pool size.",
        "tags": ["db", "pool"],
    }
    return IncidentIn(**{**fields, **overrides})


def record(**overrides: Any) -> IncidentRecord:
    result = to_record(item(**overrides), TYPES)
    assert isinstance(result, IncidentRecord)
    return result


def existing(*records: IncidentRecord) -> dict[str, ExistingIncident]:
    return {
        r.incident.id: ExistingIncident(id=r.incident.id, content_hash=r.content_hash)
        for r in records
    }


def test_codes_and_tags_are_normalized_and_free_text_keeps_case() -> None:
    incident = record(
        id=" INC-00007 ",
        environment=" PROD",
        service="Payments-API ",
        severity="High",
        title="  Pool EXHAUSTED ",
        tags=["Pool", " db", "pool"],
    ).incident

    assert incident.id == "inc-00007"
    assert (incident.environment, incident.service, incident.severity) == (
        "prod",
        "payments-api",
        "high",
    )
    assert incident.title == "Pool EXHAUSTED"
    assert incident.tags == ("db", "pool")


@pytest.mark.parametrize(
    ("field", "raw", "value"),
    [
        ("environment", "Production", "production"),
        ("service", " Billing ", "billing"),
        ("severity", "urgent", "urgent"),
    ],
)
def test_unknown_code_is_rejected_with_field_and_value(field: str, raw: str, value: str) -> None:
    result = to_record(item(**{field: raw}), TYPES)

    assert result == Rejection(id="inc-00001", reason="invalid", field=field, value=value)


def test_severity_or_tag_change_keeps_the_embedding_text() -> None:
    base = record()
    changed = record(severity="low", tags=["other"])

    assert changed.content_hash != base.content_hash
    assert changed.embedding_text_hash == base.embedding_text_hash


def test_text_change_changes_the_embedding_text() -> None:
    assert record(title="Pool drained").embedding_text_hash != record().embedding_text_hash


def test_new_id_is_ingested() -> None:
    new = record()

    plan = plan_writes([new], {}, {})

    assert (plan.ingested, plan.inserts, plan.updates) == (1, [new], [])


def test_same_id_and_hash_is_skipped() -> None:
    same = record()

    plan = plan_writes([same], existing(same), {same.content_hash: "inc-00001"})

    assert (plan.skipped, plan.inserts, plan.updates) == (1, [], [])


def test_same_id_with_new_hash_is_updated() -> None:
    changed = record(title="Pool drained")

    plan = plan_writes([changed], existing(record()), {})

    assert (plan.updated, plan.inserts, plan.updates) == (1, [], [changed])


def test_hash_owned_by_another_id_is_a_duplicate() -> None:
    copy = record(id="inc-00002")

    plan = plan_writes([copy], {}, {copy.content_hash: "inc-00001"})

    assert plan.duplicates == [
        Rejection(id="inc-00002", reason="duplicate", duplicate_of="inc-00001")
    ]
    assert (plan.ingested, plan.inserts) == (0, [])


def test_copy_within_the_batch_is_a_duplicate_of_the_first() -> None:
    first, copy = record(), record(id="inc-00002")

    plan = plan_writes([first, copy], {}, {})

    assert plan.inserts == [first]
    assert [r.duplicate_of for r in plan.duplicates] == ["inc-00001"]


def test_hash_freed_by_an_earlier_update_can_be_taken() -> None:
    old = record()
    moved, taker = record(title="Pool drained"), record(id="inc-00002")

    plan = plan_writes([moved, taker], existing(old), {old.content_hash: "inc-00001"})

    assert (plan.updated, plan.ingested, plan.duplicates) == (1, 1, [])
    assert (plan.updates, plan.inserts) == ([moved], [taker])


def test_repeated_id_in_the_batch_writes_once() -> None:
    plan = plan_writes([record(), record()], {}, {})

    assert (plan.ingested, plan.skipped, len(plan.inserts)) == (1, 1, 1)
