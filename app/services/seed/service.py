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
from app.services.seed.generator import MAX_REPEATS, generate_incidents

logger = logging.getLogger(__name__)


def ivfflat_lists(embedded_rows: int, settings: Settings) -> int:
    """pgvector guidance rows/1000, at least 1, capped so probes (>= lists) stay exact."""
    lists = embedded_rows // settings.ivfflat_rows_per_list
    return max(1, min(lists, settings.ivfflat_max_lists))


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
        result = self._ingest_service.ingest(incidents)
        self._build_vector_index()
        return result

    def _build_vector_index(self) -> None:
        """Last step: IVFFlat learns its lists from the rows present when it is built."""
        rows = self._schema_repository.count_embedded()
        lists = ivfflat_lists(rows, self._settings)
        self._schema_repository.create_vector_index(lists)

    def _load_catalog(self) -> Catalog:
        path = Path(self._settings.catalog_path)
        if not path.is_file():
            raise NotFound(f"catalog {path} not found. Run `cli catalog` first")
        try:
            catalog = Catalog.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise InvalidInput(f"catalog {path} is invalid: {exc.error_count()} errors") from None
        self._check_size(catalog.total_events())
        return catalog

    def _check_size(self, events: int) -> None:
        """Incidents = catalog events x SEED_REPEATS, kept below 1,000 (one IVFFlat list)."""
        settings = self._settings
        if not 1 <= settings.seed_repeats <= MAX_REPEATS:
            raise InvalidInput(f"SEED_REPEATS must be 1-{MAX_REPEATS}")
        total = events * settings.seed_repeats
        if not settings.seed_min_incidents <= total <= settings.seed_max_incidents:
            raise InvalidInput(
                f"seed would create {total} incidents ({events} events x "
                f"{settings.seed_repeats} repeats); need {settings.seed_min_incidents}-"
                f"{settings.seed_max_incidents}. Change SEED_REPEATS or re-run `cli catalog`"
            )

    def _generate(self, catalog: Catalog) -> list[IncidentIn]:
        try:
            return generate_incidents(catalog, self._settings.seed, self._settings.seed_repeats)
        except ValidationError as exc:
            raise InvalidInput(
                f"catalog events break ingest limits: {exc.error_count()} errors"
            ) from None
