"""Pure ingest steps: normalize and check one incident, then classify a batch."""

from dataclasses import dataclass, field

from app.core.embedding_text import embedding_text
from app.core.fingerprint import content_hash, text_hash
from app.core.models.incident import Environment, Incident, Severity
from app.core.models.storage import ExistingIncident, IncidentRecord, TypeSets
from app.core.normalize import normalize_code, normalize_tags, normalize_text
from app.services.ingest.models import IncidentIn, Rejection


@dataclass
class WritePlan:
    """Rows to write and the per-outcome counts for one batch."""

    inserts: list[IncidentRecord] = field(default_factory=list)
    updates: list[IncidentRecord] = field(default_factory=list)
    ingested: int = 0
    updated: int = 0
    skipped: int = 0
    duplicates: list[Rejection] = field(default_factory=list)


def to_record(item: IncidentIn, types: TypeSets) -> IncidentRecord | Rejection:
    """Normalize, check codes against the type tables, and hash."""
    incident_id = normalize_code(item.id)
    codes = {
        "environment": (normalize_code(item.environment), types.environments),
        "service": (normalize_code(item.service), types.services),
        "severity": (normalize_code(item.severity), types.severities),
    }
    for name, (value, allowed) in codes.items():
        if value not in allowed:
            return Rejection(id=incident_id, reason="invalid", field=name, value=value)
    incident = Incident(
        id=incident_id,
        created_at=item.created_at,
        environment=Environment(codes["environment"][0]),
        service=codes["service"][0],
        severity=Severity(codes["severity"][0]),
        title=normalize_text(item.title),
        description=normalize_text(item.description),
        resolution_summary=normalize_text(item.resolution_summary),
        tags=normalize_tags(item.tags),
    )
    text = embedding_text(incident.title, incident.description, incident.resolution_summary)
    return IncidentRecord(
        incident=incident,
        content_hash=content_hash(incident),
        embedding_text_hash=text_hash(text),
    )


def plan_writes(
    records: list[IncidentRecord],
    existing: dict[str, ExistingIncident],
    owner_by_hash: dict[str, str],
) -> WritePlan:
    """Classify each record in order, as if earlier records in the batch were already applied."""
    plan = WritePlan()
    hash_by_id = {incident_id: row.content_hash for incident_id, row in existing.items()}
    owners = dict(owner_by_hash)
    planned: dict[str, IncidentRecord] = {}
    for record in records:
        incident_id, new_hash = record.incident.id, record.content_hash
        owner = owners.get(new_hash)
        if owner is not None and owner != incident_id:
            plan.duplicates.append(
                Rejection(id=incident_id, reason="duplicate", duplicate_of=owner)
            )
            continue
        current = hash_by_id.get(incident_id)
        if current == new_hash:
            plan.skipped += 1
            continue
        if current is None:
            plan.ingested += 1
        else:
            plan.updated += 1
            owners.pop(current, None)
        hash_by_id[incident_id] = new_hash
        owners[new_hash] = incident_id
        planned[incident_id] = record
    plan.inserts = [r for incident_id, r in planned.items() if incident_id not in existing]
    plan.updates = [r for incident_id, r in planned.items() if incident_id in existing]
    return plan
