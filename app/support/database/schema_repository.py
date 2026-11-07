"""DDL and type tables. The only database code that drops anything."""

import logging
from collections.abc import Sequence
from pathlib import Path

from psycopg_pool import ConnectionPool

from app.core.models.incident import Severity
from app.support.database.errors import database_errors

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).parent / "sql"

# Exactly the six incident tables; query_embeddings and the vector extension are kept.
DROP_INCIDENT_TABLES = (
    "DROP TABLE IF EXISTS incident_tags, incidents, tags, "
    "service_types, severity_types, environment_types CASCADE"
)
VECTOR_INDEX = "incidents_embedding_ivfflat"
COUNT_EMBEDDED = "SELECT count(*) FROM incidents WHERE embedding IS NOT NULL"
DROP_VECTOR_INDEX = f"DROP INDEX IF EXISTS {VECTOR_INDEX}"
# lists is an int computed in code; CREATE INDEX options cannot be bound as parameters.
CREATE_VECTOR_INDEX = (
    f"CREATE INDEX {VECTOR_INDEX} ON incidents "
    "USING ivfflat (embedding vector_cosine_ops) WITH (lists = {lists})"
)
INSERT_ENVIRONMENT = (
    "INSERT INTO environment_types (code) VALUES (%s) ON CONFLICT (code) DO NOTHING"
)
INSERT_SEVERITY = (
    "INSERT INTO severity_types (code, rank) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING"
)
INSERT_SERVICE = (
    "INSERT INTO service_types (code, name) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING"
)


class PostgresSchemaRepository:
    """SchemaRepository on PostgreSQL; each method is one transaction."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def create_schema(self) -> None:
        files = sorted(SQL_DIR.glob("*.sql"))
        with database_errors(), self._pool.connection() as conn:
            for path in files:
                conn.execute(path.read_text(encoding="utf-8"))
        logger.info("schema applied", extra={"files": [path.name for path in files]})

    def drop_incident_tables(self) -> None:
        with database_errors(), self._pool.connection() as conn:
            logger.info(
                "seed: dropping app tables",
                extra={"host": conn.info.host, "dbname": conn.info.dbname},
            )
            conn.execute(DROP_INCIDENT_TABLES)

    def count_embedded(self) -> int:
        with database_errors(), self._pool.connection() as conn:
            row = conn.execute(COUNT_EMBEDDED).fetchone()
        return row[0] if row else 0

    def create_vector_index(self, lists: int) -> None:
        if lists < 1:
            raise ValueError("lists must be at least 1")
        with database_errors(), self._pool.connection() as conn:
            conn.execute(DROP_VECTOR_INDEX)
            conn.execute(CREATE_VECTOR_INDEX.format(lists=int(lists)))
            conn.execute("ANALYZE incidents")
        logger.info("vector index built", extra={"index": VECTOR_INDEX, "lists": lists})

    def upsert_types(
        self,
        environments: Sequence[str],
        severities: Sequence[tuple[Severity, int]],
        services: Sequence[str],
    ) -> None:
        with database_errors(), self._pool.connection() as conn, conn.cursor() as cur:
            cur.executemany(INSERT_ENVIRONMENT, [(code,) for code in environments])
            cur.executemany(INSERT_SEVERITY, [(code.value, rank) for code, rank in severities])
            cur.executemany(INSERT_SERVICE, [(code, code) for code in services])
        logger.info(
            "type tables filled",
            extra={
                "environments": len(environments),
                "severities": len(severities),
                "services": len(services),
            },
        )
