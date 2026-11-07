"""Read full incident records by ID."""

from collections.abc import Sequence

from app.core.errors import NotFound
from app.core.models.incident import Incident
from app.core.normalize import normalize_code
from app.core.ports import IncidentRepository
from app.support.tracing.span import traced


class IncidentService:
    """GET /incidents/{id} and the full records behind /assist candidates."""

    def __init__(self, repository: IncidentRepository) -> None:
        self._repository = repository

    @traced(name="IncidentService.get")
    def get(self, incident_id: str) -> Incident:
        incident_id = normalize_code(incident_id)
        incident = self._repository.get(incident_id)
        if incident is None:
            raise NotFound(f"incident {incident_id} not found")
        return incident

    @traced(name="IncidentService.get_many")
    def get_many(self, incident_ids: Sequence[str]) -> list[Incident]:
        """Incidents in the given order; unknown IDs are left out."""
        return self._repository.get_many([normalize_code(i) for i in incident_ids])
