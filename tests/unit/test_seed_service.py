"""SeedService: size checks before any drop, step order, and IVFFlat list count."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.core.errors import InvalidInput, NotFound
from app.core.models.catalog import Catalog, CatalogEvent
from app.core.models.incident import SEVERITY_RANK, Severity
from app.core.settings import Settings
from app.services.ingest.models import IncidentIn, IngestResult
from app.services.schema.service import SchemaService
from app.services.seed.service import SeedService, ivfflat_lists


class FakeSchemaRepository:
    """Records SchemaRepository calls in a shared log."""

    def __init__(self, log: list[str], embedded: int) -> None:
        self.log = log
        self.embedded = embedded
        self.types: tuple[list[str], list[tuple[Severity, int]], list[str]] | None = None
        self.lists: int | None = None

    def create_schema(self) -> None:
        self.log.append("create_schema")

    def drop_incident_tables(self) -> None:
        self.log.append("drop_incident_tables")

    def create_vector_index(self, lists: int) -> None:
        self.log.append("create_vector_index")
        self.lists = lists

    def count_embedded(self) -> int:
        self.log.append("count_embedded")
        return self.embedded

    def upsert_types(
        self,
        environments: Sequence[str],
        severities: Sequence[tuple[Severity, int]],
        services: Sequence[str],
    ) -> None:
        self.log.append("upsert_types")
        self.types = (list(environments), list(severities), list(services))


class FakeIngestService:
    """Stands in for IngestService and keeps the incidents it was given."""

    def __init__(self, log: list[str]) -> None:
        self.log = log
        self.incidents: list[IncidentIn] = []

    def ingest(self, incidents: Sequence[IncidentIn] | None) -> IngestResult:
        self.log.append("ingest")
        self.incidents = list(incidents or [])
        return IngestResult(ingested=len(self.incidents))


def write_catalog(path: Path, events: int) -> Path:
    catalog = Catalog(
        {
            "svc-b": [
                CatalogEvent(
                    title=f"event {n}",
                    description="Something failed.",
                    resolution_summary="Fixed it.",
                    tags=["tag"],
                )
                for n in range(events)
            ],
            "svc-a": [],
        }
    )
    path.write_text(catalog.model_dump_json(), encoding="utf-8")
    return path


@dataclass
class Harness:
    log: list[str]
    schema: FakeSchemaRepository
    ingest: FakeIngestService
    service: SeedService


def harness(catalog_path: Path, repeats: int = 2, embedded: int = 0) -> Harness:
    log: list[str] = []
    schema = FakeSchemaRepository(log, embedded)
    ingest = FakeIngestService(log)
    settings = Settings(catalog_path=str(catalog_path), seed_repeats=repeats)
    service = SeedService(schema, SchemaService(schema), ingest, settings)  # type: ignore[arg-type]
    return Harness(log, schema, ingest, service)


def seeded(tmp_path: Path, events: int, repeats: int = 2, embedded: int = 0) -> Harness:
    run = harness(write_catalog(tmp_path / "catalog.json", events), repeats, embedded)
    run.service.seed()
    return run


def test_steps_run_in_order_with_the_index_last(tmp_path: Path) -> None:
    assert seeded(tmp_path, events=100).log == [
        "drop_incident_tables",
        "create_schema",
        "upsert_types",
        "ingest",
        "count_embedded",
        "create_vector_index",
    ]


def test_type_tables_get_the_fixed_lists(tmp_path: Path) -> None:
    assert seeded(tmp_path, events=100).schema.types == (
        ["dev", "qa", "stage", "prod"],
        list(SEVERITY_RANK.items()),
        ["svc-a", "svc-b"],
    )


def test_generated_incidents_are_passed_to_ingest(tmp_path: Path) -> None:
    assert len(seeded(tmp_path, events=100, repeats=2).ingest.incidents) == 200


def test_index_lists_come_from_embedded_rows(tmp_path: Path) -> None:
    assert seeded(tmp_path, events=100, embedded=2500).schema.lists == 2


@pytest.mark.parametrize(("events", "repeats"), [(100, 2), (999, 1)])
def test_sizes_at_the_bounds_are_accepted(tmp_path: Path, events: int, repeats: int) -> None:
    assert len(seeded(tmp_path, events, repeats).ingest.incidents) == events * repeats


@pytest.mark.parametrize(
    ("events", "repeats", "total"), [(99, 2, 198), (500, 2, 1000)], ids=["too-few", "too-many"]
)
def test_size_outside_the_range_stops_before_any_drop(
    tmp_path: Path, events: int, repeats: int, total: int
) -> None:
    run = harness(write_catalog(tmp_path / "catalog.json", events), repeats)

    with pytest.raises(InvalidInput) as caught:
        run.service.seed()

    assert caught.value.detail == (
        f"seed would create {total} incidents ({events} events x {repeats} repeats); "
        "need 200-999. Change SEED_REPEATS or re-run `cli catalog`"
    )
    assert run.log == []


@pytest.mark.parametrize("repeats", [0, 17])
def test_repeats_outside_the_range_are_rejected(tmp_path: Path, repeats: int) -> None:
    run = harness(write_catalog(tmp_path / "catalog.json", 100), repeats)

    with pytest.raises(InvalidInput, match="SEED_REPEATS must be 1-16"):
        run.service.seed()
    assert run.log == []


def test_missing_catalog_names_the_command(tmp_path: Path) -> None:
    run = harness(tmp_path / "missing.json")

    with pytest.raises(NotFound, match="cli catalog"):
        run.service.seed()
    assert run.log == []


@pytest.mark.parametrize(
    ("embedded", "lists"), [(0, 1), (999, 1), (1000, 1), (2500, 2), (50_000, 10)]
)
def test_ivfflat_lists_are_bounded(embedded: int, lists: int) -> None:
    assert ivfflat_lists(embedded, Settings()) == lists
