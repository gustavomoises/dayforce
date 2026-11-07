"""IncidentRepository on PostgreSQL: units of work, hybrid search, reads, query vectors."""

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import psycopg
from pgvector import Vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.core.models.incident import Incident
from app.core.models.search import SearchHit, SearchPage, SearchQuery
from app.support.database.errors import database_errors
from app.support.database.query_builder import build_count, build_search
from app.support.database.unit_of_work import PostgresUnitOfWork

logger = logging.getLogger(__name__)

SELECT_INCIDENTS = """SELECT i.id, i.created_at, e.code AS environment, s.code AS service,
    v.code AS severity, i.title, i.description, i.resolution_summary,
    ARRAY(
        SELECT t.name FROM incident_tags it JOIN tags t ON t.id = it.tag_id
        WHERE it.incident_id = i.id
        ORDER BY t.name
    ) AS tags
FROM incidents i
JOIN environment_types e ON e.id = i.environment_id
JOIN service_types s ON s.id = i.service_id
JOIN severity_types v ON v.id = i.severity_id
WHERE i.id = ANY(%s)"""
SET_PROBES = "SELECT set_config('ivfflat.probes', %s, true)"
SELECT_QUERY_EMBEDDING = "SELECT embedding FROM query_embeddings WHERE query_hash = %s"
INSERT_QUERY_EMBEDDING = """INSERT INTO query_embeddings (query_hash, model, embedding)
VALUES (%s, %s, %s)
ON CONFLICT (query_hash) DO NOTHING"""


class PostgresIncidentRepository:
    """IncidentRepository backed by one shared connection pool."""

    def __init__(self, pool: ConnectionPool, ivfflat_probes: int) -> None:
        self._pool = pool
        self._probes = ivfflat_probes

    @contextmanager
    def unit_of_work(self) -> Iterator[PostgresUnitOfWork]:
        """One connection and transaction: commit on success, rollback on exception."""
        with database_errors(), self._pool.connection() as conn:
            yield PostgresUnitOfWork(conn)

    def search(self, query: SearchQuery) -> SearchPage:
        hits_query, count_query = build_search(query), build_count(query)
        with database_errors(), self._pool.connection() as conn:
            # Local to this transaction; probes >= lists keeps IVFFlat results exact.
            conn.execute(SET_PROBES, (str(self._probes),))
            with conn.cursor(row_factory=dict_row) as cur:
                hits = [SearchHit(**row) for row in cur.execute(hits_query.sql, hits_query.params)]
            row = conn.execute(count_query.sql, count_query.params).fetchone()
        return SearchPage(total=row[0] if row else 0, hits=hits)

    def get(self, incident_id: str) -> Incident | None:
        found = self.get_many([incident_id])
        return found[0] if found else None

    def get_many(self, incident_ids: Sequence[str]) -> list[Incident]:
        """Incidents in the requested order; unknown IDs are left out."""
        with database_errors(), self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                rows = cur.execute(SELECT_INCIDENTS, (list(incident_ids),)).fetchall()
        by_id = {row["id"]: Incident(**row) for row in rows}
        return [by_id[incident_id] for incident_id in incident_ids if incident_id in by_id]

    def get_query_embedding(self, query_hash: str) -> list[float] | None:
        with database_errors(), self._pool.connection() as conn:
            row = conn.execute(SELECT_QUERY_EMBEDDING, (query_hash,)).fetchone()
        return row[0].to_list() if row else None

    def save_query_embedding(self, query_hash: str, model: str, vector: list[float]) -> None:
        with database_errors(), self._pool.connection() as conn:
            conn.execute(INSERT_QUERY_EMBEDDING, (query_hash, model, Vector(vector)))

    def ping(self) -> bool:
        try:
            with self._pool.connection() as conn:
                conn.execute("SELECT 1")
        except psycopg.Error as exc:
            logger.warning("database ping failed", extra={"error": type(exc).__name__})
            return False
        return True
