"""Search filters shared by /search, /assist and the database layer."""

from pydantic import BaseModel, ConfigDict

from app.core.models.incident import Environment, Severity


class SearchFilters(BaseModel):
    """Exact-match filters. Every given tag must match."""

    model_config = ConfigDict(frozen=True)

    environment: Environment | None = None
    service: str | None = None
    severity: Severity | None = None
    tags: tuple[str, ...] = ()
