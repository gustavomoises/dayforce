"""Incident domain model and the fixed value sets from the take-home."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

INCIDENT_ID_PATTERN = r"^inc-\d{5}$"


class Environment(StrEnum):
    DEV = "dev"
    QA = "qa"
    STAGE = "stage"
    PROD = "prod"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 1,
    Severity.HIGH: 2,
    Severity.MEDIUM: 3,
    Severity.LOW: 4,
}


class Incident(BaseModel):
    """A stored, normalized incident."""

    model_config = ConfigDict(frozen=True)

    id: str
    created_at: datetime
    environment: Environment
    service: str
    severity: Severity
    title: str
    description: str
    resolution_summary: str
    tags: tuple[str, ...]
