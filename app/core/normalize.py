"""Normalization of codes, tags and IDs before validation, hashing and storage."""

import re
from collections.abc import Iterable

_WHITESPACE = re.compile(r"\s+")


def normalize_code(value: str) -> str:
    """Lowercase, trim and collapse inner whitespace: ' Payments-API ' -> 'payments-api'."""
    return _WHITESPACE.sub(" ", value).strip().lower()


def normalize_tags(tags: Iterable[str]) -> tuple[str, ...]:
    """Lowercase and trim each tag, drop empties and duplicates, sort alphabetically."""
    return tuple(sorted({tag for tag in (normalize_code(t) for t in tags) if tag}))


def normalize_text(value: str) -> str:
    """Trim free text; case and punctuation are kept."""
    return value.strip()


def normalize_query(value: str) -> str:
    """Trim and collapse whitespace in a search query; case is kept for embedding."""
    return _WHITESPACE.sub(" ", value).strip()
