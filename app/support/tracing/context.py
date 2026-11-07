"""The current correlation_id, held in a contextvar (survives await and the threadpool)."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """The correlation_id of the current request or CLI command, if any."""
    return _correlation_id.get()


@contextmanager
def correlation_scope(correlation_id: str | None) -> Iterator[None]:
    """Set the correlation_id for the enclosed block and restore the previous value after."""
    token = _correlation_id.set(correlation_id)
    try:
        yield
    finally:
        _correlation_id.reset(token)
