"""POST /assist response."""

from typing import Literal

from pydantic import BaseModel

from app.services.assist.models.answer import CandidateAssessment


class RelevantIncident(BaseModel):
    """A relevant candidate, in rank order, with the title of the stored record."""

    rank: int
    id: str
    title: str
    reason: str
    rank_justification: str


class AssistResponse(BaseModel):
    """Status is derived in code; `candidates` keeps the verdict on every retrieved incident."""

    status: Literal["answered", "no_relevant_incidents"]
    relevant_incidents: list[RelevantIncident]
    note: str | None = None
    candidates: list[CandidateAssessment]
    next_steps: list[str]
    customer_draft: str
    missing_info: list[str]
    prompt_version: int | None = None
