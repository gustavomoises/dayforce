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
        raise Unavailable(f"database unavailable: {type(exc).__name__}") from exc
    except psycopg.Error as exc:
        raise AppError(f"database error: {type(exc).__name__}") from exc
