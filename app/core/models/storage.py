"""Data exchanged between services and the database repositories."""

from pydantic import BaseModel, ConfigDict

from app.core.models.incident import Incident


class TypeSets(BaseModel):
    """Allowed codes, loaded from the type tables."""

    model_config = ConfigDict(frozen=True)

    environments: frozenset[str]
    services: frozenset[str]
    severities: frozenset[str]


class ExistingIncident(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    content_hash: str


class IncidentRecord(BaseModel):
    """A normalized incident ready to write, with its hashes."""

    model_config = ConfigDict(frozen=True)

    incident: Incident
    content_hash: str
    embedding_text_hash: str


class PendingEmbedding(BaseModel):
    """An incident row locked for embedding."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    description: str
    resolution_summary: str


class EmbeddedRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    vector: list[float]
    model: str
    embedding_text_hash: str
