"""LLM output of the `incident-validation` prompt."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class CandidateValidation(BaseModel):
    """Whether one search hit describes the same kind of problem as the question."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    valid: bool
    reason: str


class ValidationAnswer(BaseModel):
    """A verdict on every incident in the batch."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_name: ClassVar[str] = "validation_answer"

    candidates: list[CandidateValidation]
