"""Ingest request item and response."""

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.models.incident import INCIDENT_ID_PATTERN

IncidentId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_lower=True, pattern=f"(?i){INCIDENT_ID_PATTERN}"),
]
Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Tag = Annotated[str, StringConstraints(max_length=50)]


class IncidentIn(BaseModel):
    """One incident in a POST /ingest body. Codes are checked against the type tables later."""

    model_config = ConfigDict(frozen=True)

    id: IncidentId
    created_at: AwareDatetime
    environment: str
    service: str
    severity: str
    title: Title
    description: LongText
    resolution_summary: LongText
    tags: list[Tag] = Field(max_length=20)

    @field_validator("created_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class Rejection(BaseModel):
    """An incident that was not stored, with the reason."""

    model_config = ConfigDict(frozen=True)

    id: str
    reason: Literal["duplicate", "invalid"]
    field: str | None = None
    value: str | None = None
    duplicate_of: str | None = None


class IngestResult(BaseModel):
    """Counts for one ingest call, plus the embedding step outcome."""

    ingested: int = 0
    updated: int = 0
    skipped: int = 0
    duplicates: int = 0
    invalid: int = 0
    embedded: int = 0
    embedding_pending: int = 0
    embedding_error: str | None = None
    rejected: list[Rejection] = []
