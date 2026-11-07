"""Create tables and indexes. DDL only; never inserts or drops."""

from app.core.ports import SchemaRepository


class SchemaService:
    """Idempotent schema creation, used by `cli schema` and the seed."""

    def __init__(self, repository: SchemaRepository) -> None:
        self._repository = repository

    def create(self) -> None:
        self._repository.create_schema()
