"""POST /assist body."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment, Severity
from app.core.normalize import normalize_code, normalize_tags

# Limits mirror Settings.max_question_length and Settings.assist_max_multiplier, so that
# FastAPI rejects bad input with 422 before the service runs.
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AssistRequest(BaseModel):
    """A question plus the same optional filters as GET /search."""

    model_config = ConfigDict(frozen=True)

    question: Question
    environment: Environment | None = None
    service: str | None = None
    severity: Severity | None = None
    tags: list[str] = []
    candidate_multiplier: int = Field(3, ge=1, le=5)

    def filters(self) -> SearchFilters:
        """Normalized search filters for this request."""
        return SearchFilters(
            environment=self.environment,
            service=normalize_code(self.service or "") or None,
            severity=self.severity,
            tags=normalize_tags(self.tags),
        )
