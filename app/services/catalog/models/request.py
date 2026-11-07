"""Input of `cli catalog`; anything not given uses the defaults."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.normalize import normalize_code
from app.services.catalog.defaults import (
    DEFAULT_EVENTS_PER_SERVICE,
    DEFAULT_SERVICES,
    MAX_EVENTS_PER_SERVICE,
    MAX_SERVICES,
)


class CatalogRequest(BaseModel):
    """Services to generate events for, and how many events each."""

    model_config = ConfigDict(frozen=True)

    services: list[str] = Field(default_factory=lambda: list(DEFAULT_SERVICES))
    events_per_service: int = Field(DEFAULT_EVENTS_PER_SERVICE, ge=1, le=MAX_EVENTS_PER_SERVICE)

    @field_validator("services")
    @classmethod
    def _normalize_services(cls, services: list[str]) -> list[str]:
        names = [normalize_code(service) for service in services]
        if not all(names):
            raise ValueError("service names must not be empty")
        unique = list(dict.fromkeys(names))
        if not 1 <= len(unique) <= MAX_SERVICES:
            raise ValueError(f"give 1-{MAX_SERVICES} services, got {len(unique)}")
        return unique
