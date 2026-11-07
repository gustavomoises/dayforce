"""Reproducible incidents from the catalog: same catalog, seed and repeats give the same rows."""

import random
from datetime import UTC, datetime, timedelta

from app.core.models.catalog import Catalog, CatalogEvent
from app.core.models.incident import Environment, Severity
from app.services.ingest.models import IncidentIn

# Production dominates real incident trackers; lower environments still get rows to filter.
ENVIRONMENT_WEIGHTS = {
    Environment.DEV: 15,
    Environment.QA: 15,
    Environment.STAGE: 20,
    Environment.PROD: 50,
}
# Critical outages are rare and most tickets are medium; every value still has dozens of rows.
SEVERITY_WEIGHTS = {
    Severity.CRITICAL: 10,
    Severity.HIGH: 25,
    Severity.MEDIUM: 40,
    Severity.LOW: 25,
}
# Every (environment, severity) pair, weighted by both: a recurring failure lands in a
# different combination each time, so copies never share a content hash.
COMBINATIONS = [
    ((environment, severity), env_weight * sev_weight)
    for environment, env_weight in ENVIRONMENT_WEIGHTS.items()
    for severity, sev_weight in SEVERITY_WEIGHTS.items()
]
MAX_REPEATS = len(COMBINATIONS)
# Fixed bounds, not "now minus N days", so a rerun next week gives identical rows.
CREATED_FROM = datetime(2026, 1, 1, tzinfo=UTC)
CREATED_TO = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)


def generate_incidents(catalog: Catalog, seed: int, repeats: int) -> list[IncidentIn]:
    """Each event `repeats` times, each copy with its own environment, severity and date.

    Services sorted, events in catalog order, copies next to each other, IDs from inc-00001.
    """
    if not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be 1-{MAX_REPEATS}")
    rng = random.Random(seed)
    events = [
        (service, event) for service in sorted(catalog.root) for event in catalog.root[service]
    ]
    incidents: list[IncidentIn] = []
    for service, event in events:
        for environment, severity in _distinct_combinations(rng, repeats):
            number = len(incidents) + 1
            incidents.append(_incident(number, service, event, environment, severity, rng))
    return incidents


def _distinct_combinations(rng: random.Random, count: int) -> list[tuple[Environment, Severity]]:
    """Weighted draws without repeats, in draw order (deterministic for a given rng state)."""
    remaining = list(COMBINATIONS)
    chosen = []
    for _ in range(count):
        index = rng.choices(range(len(remaining)), weights=[w for _, w in remaining])[0]
        chosen.append(remaining.pop(index)[0])
    return chosen


def _incident(
    number: int,
    service: str,
    event: CatalogEvent,
    environment: Environment,
    severity: Severity,
    rng: random.Random,
) -> IncidentIn:
    return IncidentIn(
        id=f"inc-{number:05d}",
        environment=environment,
        severity=severity,
        created_at=_created_at(rng),
        service=service,
        title=event.title,
        description=event.description,
        resolution_summary=event.resolution_summary,
        tags=event.tags,
    )


def _created_at(rng: random.Random) -> datetime:
    minutes = int((CREATED_TO - CREATED_FROM).total_seconds() // 60)
    return CREATED_FROM + timedelta(minutes=rng.randint(0, minutes))
