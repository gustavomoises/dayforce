"""Reproducible incidents from the catalog: same catalog and seed give the same rows."""

import random
from datetime import UTC, datetime, timedelta

from app.core.models.catalog import Catalog
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
# Fixed bounds, not "now minus N days", so a rerun next week gives identical rows.
CREATED_FROM = datetime(2026, 1, 1, tzinfo=UTC)
CREATED_TO = datetime(2026, 10, 31, 23, 59, tzinfo=UTC)


def generate_incidents(catalog: Catalog, seed: int) -> list[IncidentIn]:
    """Services sorted, events in catalog order, IDs from inc-00001; fixed draw order."""
    rng = random.Random(seed)
    events = [
        (service, event) for service in sorted(catalog.root) for event in catalog.root[service]
    ]
    return [
        IncidentIn(
            id=f"inc-{number:05d}",
            environment=_choose(rng, ENVIRONMENT_WEIGHTS),
            severity=_choose(rng, SEVERITY_WEIGHTS),
            created_at=_created_at(rng),
            service=service,
            title=event.title,
            description=event.description,
            resolution_summary=event.resolution_summary,
            tags=event.tags,
        )
        for number, (service, event) in enumerate(events, start=1)
    ]


def _choose[T: str](rng: random.Random, weights: dict[T, int]) -> T:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _created_at(rng: random.Random) -> datetime:
    minutes = int((CREATED_TO - CREATED_FROM).total_seconds() // 60)
    return CREATED_FROM + timedelta(minutes=rng.randint(0, minutes))
