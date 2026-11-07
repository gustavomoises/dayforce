"""SchemaService: creates the schema and never drops or writes rows."""

from collections.abc import Sequence

from app.core.models.incident import Severity
from app.services.schema.service import SchemaService


class FakeSchemaRepository:
    """Records which SchemaRepository methods were called."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def create_schema(self) -> None:
        self.calls.append("create_schema")

    def drop_incident_tables(self) -> None:
        self.calls.append("drop_incident_tables")

    def create_vector_index(self, lists: int) -> None:
        self.calls.append("create_vector_index")

    def count_embedded(self) -> int:
        self.calls.append("count_embedded")
        return 0

    def upsert_types(
        self,
        environments: Sequence[str],
        severities: Sequence[tuple[Severity, int]],
        services: Sequence[str],
    ) -> None:
        self.calls.append("upsert_types")


def test_create_only_applies_the_schema() -> None:
    repository = FakeSchemaRepository()

    SchemaService(repository).create()

    assert repository.calls == ["create_schema"]
