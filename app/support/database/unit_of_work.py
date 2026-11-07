"""Incident writes and embedding bookkeeping inside one transaction."""

from collections.abc import Sequence
from typing import Any

from pgvector import Vector
from psycopg import Connection
from psycopg.rows import dict_row

from app.core.models.storage import (
    EmbeddedRow,
    ExistingIncident,
    IncidentRecord,
    PendingEmbedding,
    TypeSets,
)

_TYPE_ID = "(SELECT id FROM {table} WHERE code = %({field})s)"
_ENVIRONMENT_ID = _TYPE_ID.format(table="environment_types", field="environment")
_SERVICE_ID = _TYPE_ID.format(table="service_types", field="service")
_SEVERITY_ID = _TYPE_ID.format(table="severity_types", field="severity")

FIND_EXISTING = """SELECT id, content_hash FROM incidents
WHERE id = ANY(%(ids)s) OR content_hash = ANY(%(hashes)s::char(64)[])"""

# New rows start with a NULL embedding: pending until the embed step.
INSERT_INCIDENT = f"""INSERT INTO incidents (
    id, created_at, environment_id, service_id, severity_id,
    title, description, resolution_summary, content_hash
) VALUES (
    %(id)s, %(created_at)s, {_ENVIRONMENT_ID}, {_SERVICE_ID}, {_SEVERITY_ID},
    %(title)s, %(description)s, %(resolution_summary)s, %(content_hash)s
)"""

# SET expressions read the old row, so each CASE compares against the stored text hash.
_TEXT_CHANGED = "embedding_text_hash IS DISTINCT FROM %(embedding_text_hash)s"
UPDATE_INCIDENT = f"""UPDATE incidents SET
    created_at = %(created_at)s,
    environment_id = {_ENVIRONMENT_ID},
    service_id = {_SERVICE_ID},
    severity_id = {_SEVERITY_ID},
    title = %(title)s,
    description = %(description)s,
    resolution_summary = %(resolution_summary)s,
    content_hash = %(content_hash)s,
    embedding = CASE WHEN {_TEXT_CHANGED} THEN NULL ELSE embedding END,
    embedding_model = CASE WHEN {_TEXT_CHANGED} THEN NULL ELSE embedding_model END,
    embedding_text_hash = CASE WHEN {_TEXT_CHANGED} THEN NULL ELSE embedding_text_hash END,
    updated_at = now()
WHERE id = %(id)s"""

DELETE_TAG_LINKS = "DELETE FROM incident_tags WHERE incident_id = ANY(%s)"
INSERT_TAGS = "INSERT INTO tags (name) SELECT unnest(%s::text[]) ON CONFLICT (name) DO NOTHING"
INSERT_TAG_LINKS = """INSERT INTO incident_tags (incident_id, tag_id)
SELECT %s, id FROM tags WHERE name = ANY(%s)"""

_PENDING = "embedding IS NULL OR embedding_model IS DISTINCT FROM %(model)s"
LOCK_PENDING = f"""SELECT id, title, description, resolution_summary FROM incidents
WHERE {_PENDING}
ORDER BY id
LIMIT %(limit)s
FOR UPDATE SKIP LOCKED"""
COUNT_PENDING = f"SELECT count(*) FROM incidents WHERE {_PENDING}"
SAVE_EMBEDDING = """UPDATE incidents
SET embedding = %s, embedding_model = %s, embedding_text_hash = %s
WHERE id = %s"""

TYPE_CODES = {
    "environments": "SELECT code FROM environment_types",
    "services": "SELECT code FROM service_types",
    "severities": "SELECT code FROM severity_types",
}


class PostgresUnitOfWork:
    """IncidentUnitOfWork on one connection; the repository owns commit and rollback."""

    def __init__(self, conn: Connection[Any]) -> None:
        self._conn = conn

    def load_types(self) -> TypeSets:
        codes = {
            name: frozenset(row[0] for row in self._conn.execute(sql))
            for name, sql in TYPE_CODES.items()
        }
        return TypeSets(**codes)

    def find_existing(
        self, ids: Sequence[str], content_hashes: Sequence[str]
    ) -> tuple[dict[str, ExistingIncident], dict[str, str]]:
        params = {"ids": list(ids), "hashes": list(content_hashes)}
        with self._conn.cursor(row_factory=dict_row) as cur:
            rows = [ExistingIncident(**row) for row in cur.execute(FIND_EXISTING, params)]
        id_set = set(ids)
        by_id = {row.id: row for row in rows if row.id in id_set}
        return by_id, {row.content_hash: row.id for row in rows}

    def insert(self, records: Sequence[IncidentRecord]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(INSERT_INCIDENT, [_incident_params(r) for r in records])
        self._link_tags(records)

    def update(self, records: Sequence[IncidentRecord]) -> None:
        with self._conn.cursor() as cur:
            cur.executemany(UPDATE_INCIDENT, [_incident_params(r) for r in records])
            cur.execute(DELETE_TAG_LINKS, ([r.incident.id for r in records],))
        self._link_tags(records)

    def lock_pending_embeddings(self, model: str, limit: int) -> list[PendingEmbedding]:
        with self._conn.cursor(row_factory=dict_row) as cur:
            rows = cur.execute(LOCK_PENDING, {"model": model, "limit": limit}).fetchall()
        return [PendingEmbedding(**row) for row in rows]

    def save_embeddings(self, rows: Sequence[EmbeddedRow]) -> None:
        params = [(Vector(r.vector), r.model, r.embedding_text_hash, r.id) for r in rows]
        with self._conn.cursor() as cur:
            cur.executemany(SAVE_EMBEDDING, params)

    def count_pending_embeddings(self, model: str) -> int:
        row = self._conn.execute(COUNT_PENDING, {"model": model}).fetchone()
        return row[0] if row else 0

    def _link_tags(self, records: Sequence[IncidentRecord]) -> None:
        names = sorted({tag for r in records for tag in r.incident.tags})
        if not names:
            return
        with self._conn.cursor() as cur:
            cur.execute(INSERT_TAGS, (names,))
            cur.executemany(
                INSERT_TAG_LINKS,
                [(r.incident.id, list(r.incident.tags)) for r in records if r.incident.tags],
            )


def _incident_params(record: IncidentRecord) -> dict[str, Any]:
    incident = record.incident
    return {
        "id": incident.id,
        "created_at": incident.created_at,
        "environment": incident.environment.value,
        "service": incident.service,
        "severity": incident.severity.value,
        "title": incident.title,
        "description": incident.description,
        "resolution_summary": incident.resolution_summary,
        "content_hash": record.content_hash,
        "embedding_text_hash": record.embedding_text_hash,
    }
