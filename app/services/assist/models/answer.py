"""LLM output of the `incident-assist` prompt."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class CandidateAssessment(BaseModel):
    """The LLM's verdict on one retrieved incident.

    A relevant record is either ranked (`related_to` null) or attached to the ranked record it
    is related to (`related_to` = that record's id, `rank` null).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    relevant: bool
    reason: str
    rank: int | None
    rank_justification: str | None
    related_to: str | None


class AssistAnswer(BaseModel):
    """Every candidate judged, plus next steps, a customer draft and missing info."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_name: ClassVar[str] = "assist_answer"

    candidates: list[CandidateAssessment]
    next_steps: list[str]
    customer_draft: str
    missing_info: list[str]
