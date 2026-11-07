"""CatalogService: defaults, limits, one LLM call per service, exact event count, save and get."""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.core.errors import InvalidInput, LLMOutputInvalid, NotFound
from app.core.models.catalog import Catalog, CatalogEvent
from app.core.models.prompt import CompiledPrompt, LLMConfig, LLMResult
from app.core.settings import Settings
from app.services.catalog.defaults import DEFAULT_SERVICES, PROMPT_NAME
from app.services.catalog.models.batch import CatalogBatch
from app.services.catalog.models.request import CatalogRequest
from app.services.catalog.service import CatalogService

CONFIG = LLMConfig(
    model="test-model",
    max_output_tokens=100,
    text={"format": {"type": "json_schema", "name": "catalog_batch", "schema": {"type": "object"}}},
)


class FakePrompts:
    """PromptProvider that records every request and echoes the variables in the text."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], str]] = []

    def get(self, name: str, variables: dict[str, str], label: str) -> CompiledPrompt:
        self.calls.append((name, variables, label))
        text = json.dumps(variables)
        return CompiledPrompt(name=name, version=1, label=label, text=text, config=CONFIG)


class FakeLLM:
    """LLMClient that answers `count` events, plus `extra` more, for the requested service."""

    def __init__(self, extra: int = 0) -> None:
        self.calls: list[type[BaseModel]] = []
        self._extra = extra

    def complete[OutputT: BaseModel](
        self, prompt: CompiledPrompt, output_model: type[OutputT]
    ) -> LLMResult[OutputT]:
        self.calls.append(output_model)
        variables = json.loads(prompt.text)
        count = int(variables["count"]) + self._extra
        events = [event(variables["service"], n) for n in range(count)]
        output = output_model.model_validate({"events": events})
        return LLMResult(output=output, model="test-model", input_tokens=1, output_tokens=1)


def event(service: str, number: int) -> dict[str, object]:
    return {
        "title": f"{service} failure {number}",
        "description": "Something broke.",
        "resolution_summary": "Fixed it.",
        "tags": ["outage"],
    }


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(catalog_path=str(tmp_path / "data" / "service_catalog.json"))


def service_with(settings: Settings, extra: int = 0) -> tuple[CatalogService, FakePrompts, FakeLLM]:
    prompts = FakePrompts()
    llm = FakeLLM(extra)
    return CatalogService(prompts, llm, settings), prompts, llm


def test_defaults_are_20_services_with_20_events() -> None:
    request = CatalogRequest()

    assert request.services == list(DEFAULT_SERVICES)
    assert (len(request.services), request.events_per_service) == (20, 20)


def test_service_names_are_normalized_and_deduplicated() -> None:
    request = CatalogRequest(services=[" Payments-API ", "payments-api", "Auth-Service"])

    assert request.services == ["payments-api", "auth-service"]


@pytest.mark.parametrize(
    "fields",
    [
        {"services": []},
        {"services": [f"service-{n}" for n in range(51)]},
        {"services": ["  "]},
        {"events_per_service": 0},
        {"events_per_service": 51},
    ],
    ids=["no-services", "51-services", "blank-name", "0-events", "51-events"],
)
def test_out_of_range_requests_are_rejected(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CatalogRequest(**fields)


def test_generate_makes_one_llm_call_per_service(settings: Settings) -> None:
    service, prompts, llm = service_with(settings)

    catalog = service.generate(
        CatalogRequest(services=["api-gateway", "auth-service"], events_per_service=3), label="dev"
    )

    assert prompts.calls == [
        (PROMPT_NAME, {"service": "api-gateway", "count": "3"}, "dev"),
        (PROMPT_NAME, {"service": "auth-service", "count": "3"}, "dev"),
    ]
    assert llm.calls == [CatalogBatch, CatalogBatch]
    assert {name: len(events) for name, events in catalog.root.items()} == {
        "api-gateway": 3,
        "auth-service": 3,
    }


def test_generate_saves_the_catalog_that_get_returns(settings: Settings) -> None:
    service, _, llm = service_with(settings)
    generated = service.generate(CatalogRequest(services=["api-gateway"], events_per_service=2))
    calls_after_generate = len(llm.calls)

    assert service.get() == generated
    assert len(llm.calls) == calls_after_generate


@pytest.mark.parametrize("extra", [-1, 1], ids=["too-few", "too-many"])
def test_wrong_event_count_is_rejected_and_nothing_saved(settings: Settings, extra: int) -> None:
    service, _, _ = service_with(settings, extra=extra)

    with pytest.raises(LLMOutputInvalid, match="expected 2 events"):
        service.generate(CatalogRequest(services=["api-gateway"], events_per_service=2))

    assert not Path(settings.catalog_path).exists()


def test_missing_catalog_names_the_cli_command(settings: Settings) -> None:
    service, _, _ = service_with(settings)

    with pytest.raises(NotFound, match="app.cli catalog"):
        service.get()


def test_invalid_catalog_file_is_rejected(settings: Settings) -> None:
    path = Path(settings.catalog_path)
    path.parent.mkdir(parents=True)
    path.write_text('{"api-gateway": [{"title": "only a title"}]}', encoding="utf-8")
    service, _, _ = service_with(settings)

    with pytest.raises(InvalidInput):
        service.get()


def test_get_reads_a_committed_file_without_the_llm(settings: Settings) -> None:
    committed = Catalog({"api-gateway": [CatalogEvent.model_validate(event("api-gateway", 1))]})
    path = Path(settings.catalog_path)
    path.parent.mkdir(parents=True)
    path.write_text(committed.model_dump_json(), encoding="utf-8")
    service, prompts, llm = service_with(settings)

    assert service.get() == committed
    assert (prompts.calls, llm.calls) == ([], [])
