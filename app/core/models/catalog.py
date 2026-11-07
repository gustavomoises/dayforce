"""Shape of data/service_catalog.json, written by CatalogService and read by SeedService."""

from pydantic import BaseModel, ConfigDict, RootModel


class CatalogEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    description: str
    resolution_summary: str
    tags: list[str]


class Catalog(RootModel[dict[str, list[CatalogEvent]]]):
    """{service: [events]}."""

    def total_events(self) -> int:
        return sum(len(events) for events in self.root.values())
