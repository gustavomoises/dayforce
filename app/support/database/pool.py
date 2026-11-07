"""The PostgreSQL connection pool (TLS, timeouts, pgvector types)."""

from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

from app.core.secrets import DatabaseCredentials
from app.core.settings import Settings

# Settings has no connect timeout yet; a fixed bound keeps startup and /health from hanging.
CONNECT_TIMEOUT_SECONDS = 10


def create_pool(credentials: DatabaseCredentials, settings: Settings) -> ConnectionPool:
    """Build and open the pool; connections are made in the background."""
    pool = ConnectionPool(
        kwargs={
            "host": credentials.host,
            "port": credentials.port,
            "dbname": credentials.dbname,
            "user": credentials.username,
            "password": credentials.password.get_secret_value(),
            "sslmode": "require",
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms} -c timezone=UTC",
        },
        configure=_configure,
        timeout=CONNECT_TIMEOUT_SECONDS,
        open=False,
    )
    pool.open()
    return pool


def _configure(conn: Connection[Any]) -> None:
    # register_vector needs the type; on a fresh database the extension may not exist yet.
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    register_vector(conn)
    # The pool requires connections to be idle after configure.
    conn.commit()
