"""Reset: drop the incident tables, recreate them, fill types, ingest generated incidents."""

import logging
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import InvalidInput, NotFound
from app.core.models.catalog import Catalog
from app.core.models.incident import SEVERITY_RANK, Environment
from app.core.ports import SchemaRepository
from app.core.settings import Settings
from app.services.ingest.models import IncidentIn, IngestResult
from app.services.ingest.service import IngestService
from app.services.schema.service import SchemaService
from app.services.seed.generator import generate_incidents

logger = logging.getLogger(__name__)

# The take-home asks for 200-500 incidents; the seed uses every catalog event once.
MIN_EVENTS = 200
MAX_EVENTS = 500


class SeedService:
    """The only destructive operation. CLI only, no confirmation."""

    def __init__(
        self,
        schema_repository: SchemaRepository,
        schema_service: SchemaService,
        ingest_service: IngestService,
        settings: Settings,
    ) -> None:
        self._schema_repository = schema_repository
        self._schema_service = schema_service
        self._ingest_service = ingest_service
        self._settings = settings

    def seed(self) -> IngestResult:
        catalog = self._load_catalog()
        incidents = self._generate(catalog)
        self._schema_repository.drop_incident_tables()
        self._schema_service.create()
        self._schema_repository.upsert_types(
            environments=[environment.value for environment in Environment],
            severities=list(SEVERITY_RANK.items()),
            services=sorted(catalog.root),
        )
        logger.info("seed generated incidents", extra={"count": len(incidents)})
        return self._ingest_service.ingest(incidents)

    def _load_catalog(self) -> Catalog:
        path = Path(self._settings.catalog_path)
        if not path.is_file():
            raise NotFound(f"catalog {path} not found. Run `cli catalog` first")
        try:
            catalog = Catalog.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise InvalidInput(f"catalog {path} is invalid: {exc.error_count()} errors") from None
        total = catalog.total_events()
        if not MIN_EVENTS <= total <= MAX_EVENTS:
            raise InvalidInput(
                f"catalog has {total} events; need {MIN_EVENTS}-{MAX_EVENTS}. "
                "Re-run `cli catalog` with more services or events"
            )
        return catalog

    def _generate(self, catalog: Catalog) -> list[IncidentIn]:
        try:
            return generate_incidents(catalog, self._settings.seed)
        except ValidationError as exc:
            raise InvalidInput(
                f"catalog events break ingest limits: {exc.error_count()} errors"
            ) from None
