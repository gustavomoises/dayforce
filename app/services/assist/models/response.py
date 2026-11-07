"""POST /assist response."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.models.incident import Environment, Severity
from app.services.assist.models.answer import CandidateAssessment
from app.services.assist.models.validation import CandidateValidation


class RelatedIncident(BaseModel):
    """Another valid candidate recording the same failure (identical text)."""

    id: str
    environment: Environment
    severity: Severity
    created_at: datetime


class RelevantIncident(BaseModel):
    """A relevant candidate, in rank order, with the title and its cluster of recurrences."""

    rank: int
    id: str
    title: str
    reason: str
    rank_justification: str
    related: list[RelatedIncident] = []


class AssistResponse(BaseModel):
    """Status is derived in code; `candidates` keeps the verdict on every retrieved incident."""

    status: Literal["answered", "no_relevant_incidents"]
    relevant_incidents: list[RelevantIncident]
    note: str | None = None
    candidates: list[CandidateAssessment]
    next_steps: list[str]
    customer_draft: str
    missing_info: list[str]
    # Every search hit checked by incident-validation, valid or not, with the reason.
    validation: list[CandidateValidation] = []
    prompt_version: int | None = None
