"""Seed generator: reproducible, ordered, distinct pairs per event, weighted values."""

from collections import Counter
from itertools import groupby

import pytest

from app.core.models.catalog import Catalog, CatalogEvent
from app.services.seed.generator import (
    CREATED_FROM,
    CREATED_TO,
    MAX_REPEATS,
    generate_incidents,
)


def catalog(events_per_service: int, services: tuple[str, ...] = ("svc-b", "svc-a")) -> Catalog:
    return Catalog(
        {
            service: [
                CatalogEvent(
                    title=f"{service} event {n}",
                    description="Something failed.",
                    resolution_summary="Fixed it.",
                    tags=["tag"],
                )
                for n in range(events_per_service)
            ]
            for service in services
        }
    )


def test_same_seed_gives_identical_incidents() -> None:
    assert generate_incidents(catalog(5), seed=42, repeats=3) == generate_incidents(
        catalog(5), seed=42, repeats=3
    )


def test_different_seed_gives_different_incidents() -> None:
    assert generate_incidents(catalog(5), seed=1, repeats=3) != generate_incidents(
        catalog(5), seed=2, repeats=3
    )


def test_services_sorted_copies_adjacent_and_ids_sequential() -> None:
    incidents = generate_incidents(catalog(2), seed=42, repeats=2)

    assert [i.id for i in incidents] == [f"inc-{n:05d}" for n in range(1, 9)]
    assert [i.title for i in incidents] == [
        "svc-a event 0",
        "svc-a event 0",
        "svc-a event 1",
        "svc-a event 1",
        "svc-b event 0",
        "svc-b event 0",
        "svc-b event 1",
        "svc-b event 1",
    ]


@pytest.mark.parametrize("repeats", [2, 5, MAX_REPEATS])
def test_each_event_gets_distinct_environment_severity_pairs(repeats: int) -> None:
    incidents = generate_incidents(catalog(4), seed=42, repeats=repeats)

    for _, copies in groupby(incidents, key=lambda i: i.title):
        pairs = [(i.environment, i.severity) for i in copies]
        assert len(pairs) == repeats
        assert len(set(pairs)) == repeats


def test_created_at_is_utc_within_the_fixed_range() -> None:
    incidents = generate_incidents(catalog(20), seed=42, repeats=2)

    assert all(CREATED_FROM <= i.created_at <= CREATED_TO for i in incidents)
    assert all(i.created_at.utcoffset().total_seconds() == 0 for i in incidents)


def test_environment_and_severity_follow_the_weights() -> None:
    incidents = generate_incidents(catalog(2000, services=("svc",)), seed=42, repeats=1)
    environments = Counter(i.environment for i in incidents)
    severities = Counter(i.severity for i in incidents)

    assert 0.45 < environments["prod"] / len(incidents) < 0.55
    assert 0.12 < environments["dev"] / len(incidents) < 0.18
    assert 0.35 < severities["medium"] / len(incidents) < 0.45
    assert 0.07 < severities["critical"] / len(incidents) < 0.13


@pytest.mark.parametrize("repeats", [0, MAX_REPEATS + 1])
def test_repeats_outside_the_range_are_rejected(repeats: int) -> None:
    with pytest.raises(ValueError, match=f"repeats must be 1-{MAX_REPEATS}"):
        generate_incidents(catalog(1), seed=42, repeats=repeats)
