"""SHA-256 hashes: content hash for duplicates, text hash for embeddings and queries."""

import hashlib
import json
import re
import unicodedata

from app.core.models.incident import Incident

_NON_WORD = re.compile(r"[^\w\s]")
_WHITESPACE = re.compile(r"\s+")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_text(value: str) -> str:
    """Free text for the hash only: NFKC, lowercase, no special characters, single spaces."""
    value = unicodedata.normalize("NFKC", value).lower()
    value = _NON_WORD.sub(" ", value)
    return _WHITESPACE.sub(" ", value).strip()


def content_hash(incident: Incident) -> str:
    """Hash of the canonical JSON of the hashed fields. Ignores id and dates."""
    fields = {
        "service": incident.service,
        "environment": incident.environment.value,
        "severity": incident.severity.value,
        "title": _hash_text(incident.title),
        "description": _hash_text(incident.description),
        "resolution_summary": _hash_text(incident.resolution_summary),
        "tags": list(incident.tags),
    }
    canonical = {key: value for key, value in fields.items() if value not in (None, "", [])}
    return _sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def text_hash(text: str) -> str:
    """Hash of an exact text, used for embedded text and stored query vectors."""
    return _sha256(text)


def query_hash(query: str, model: str) -> str:
    return _sha256(f"{model}\n{query}")
