"""Convert psycopg errors into domain errors at the database boundary."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from app.core.errors import AppError, Unavailable


@contextmanager
def database_errors() -> Iterator[None]:
    """Connection, pool and timeout failures become Unavailable; other driver errors AppError."""
    try:
        yield
    except psycopg.OperationalError as exc:
        raise Unavailable(f"database unavailable: {_describe(exc)}") from exc
    except psycopg.Error as exc:
        raise AppError(f"database error: {_describe(exc)}") from exc


def _describe(exc: psycopg.Error) -> str:
    """Error class plus PostgreSQL's primary message (names columns and tables, never data)."""
    message = exc.diag.message_primary if exc.diag else None
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__
