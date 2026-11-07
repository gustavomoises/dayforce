"""Generate the service catalog with the LLM, and read the committed file."""

import logging
from pathlib import Path

from pydantic import ValidationError

from app.core.errors import InvalidInput, LLMOutputInvalid, NotFound
from app.core.models.catalog import Catalog, CatalogEvent
from app.core.ports import LLMClient, PromptProvider
from app.core.settings import Settings
from app.services.catalog.defaults import PROMPT_NAME
from app.services.catalog.models.batch import CatalogBatch
from app.services.catalog.models.request import CatalogRequest
from app.support.tracing.span import traced

logger = logging.getLogger(__name__)


class CatalogService:
    """One LLM call per service; the result is saved as {service: [events]}."""

    def __init__(self, prompts: PromptProvider, llm: LLMClient, settings: Settings) -> None:
        self._prompts = prompts
        self._llm = llm
        self._settings = settings

    @traced(name="CatalogService.generate")
    def generate(self, request: CatalogRequest, label: str = "production") -> Catalog:
        """Generate every service, then write the catalog file."""
        catalog: dict[str, list[CatalogEvent]] = {}
        for done, service in enumerate(request.services, start=1):
            catalog[service] = self._generate_service(service, request.events_per_service, label)
            logger.info(
                "catalog service generated",
                extra={"service": service, "done": done, "total": len(request.services)},
            )
        result = Catalog(catalog)
        self._write(result)
        return result

    @traced(name="CatalogService.get")
    def get(self) -> Catalog:
        """The committed catalog file; never calls the LLM."""
        path = self._path
        if not path.is_file():
            raise NotFound("catalog not found; run `python -m app.cli catalog`")
        try:
            return Catalog.model_validate_json(path.read_text(encoding="utf-8"))
        except ValidationError as exc:
            raise InvalidInput(f"catalog {path} is invalid: {exc.error_count()} errors") from None

    @property
    def _path(self) -> Path:
        return Path(self._settings.catalog_path)

    def _generate_service(self, service: str, count: int, label: str) -> list[CatalogEvent]:
        prompt = self._prompts.get(PROMPT_NAME, {"service": service, "count": str(count)}, label)
        events = self._llm.complete(prompt, CatalogBatch).output.events
        if len(events) != count:
            raise LLMOutputInvalid(
                f"catalog for service {service}: expected {count} events, got {len(events)}"
            )
        return events

    def _write(self, catalog: Catalog) -> None:
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(catalog.model_dump_json(indent=2), encoding="utf-8")
        logger.info("catalog written", extra={"path": str(path), "events": catalog.total_events()})
