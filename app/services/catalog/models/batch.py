"""LLM output of the `incident-catalog` prompt."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from app.core.models.catalog import CatalogEvent


class CatalogBatch(BaseModel):
    """The events generated for one service."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_name: ClassVar[str] = "catalog_batch"

    events: list[CatalogEvent]
