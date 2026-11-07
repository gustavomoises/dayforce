"""CandidateScreener: batch sizes, offset paging, stop rules, and grounding of the verdicts."""

import json
from collections.abc import Collection

import pytest
from pydantic import BaseModel

from app.core.errors import GroundingFailure
from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment
from app.core.models.prompt import CompiledPrompt, LLMConfig, LLMResult
from app.core.models.search import SearchHit, SearchPage, SearchQuery
from app.core.settings import Settings
from app.services.assist.models.validation import ValidationAnswer
from app.services.assist.screening import PROMPT_NAME, CandidateScreener, ground_verdicts
from app.services.search.service import SearchService

SETTINGS = Settings()
CONFIG = LLMConfig(
    model="test-model",
    max_output_tokens=100,
    text={"format": {"type": "json_schema", "name": "validation_answer", "schema": {"a": 1}}},
)


def incident_id(number: int) -> str:
    return f"inc-{number:05d}"


class FakeRepository:
    """IncidentRepository whose search pages through a fixed hit list, most similar first."""

    def __init__(self, hit_count: int) -> None:
        self.hits = [
            SearchHit(id=incident_id(n), title=f"t{n}", snippet=f"s{n}", score=1 / n)
            for n in range(1, hit_count + 1)
        ]
        self.pages: list[tuple[int, int]] = []

    def search(self, query: SearchQuery) -> SearchPage:
        self.pages.append((query.limit, query.offset))
        page = self.hits[query.offset : query.offset + query.limit]
        return SearchPage(total=len(self.hits), hits=page)

    def get_query_embedding(self, query_hash: str) -> list[float] | None:
        return [0.1]

    def save_query_embedding(self, query_hash: str, model: str, vector: list[float]) -> None:
        raise AssertionError("the stored vector must be reused")


class FakeEmbedder:
    def embed_batch(self, texts: object) -> object:
        raise AssertionError("the stored vector must be reused")


class FakePrompts:
    """PromptProvider that records requests and passes the variables as JSON text."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], str]] = []

    def get(self, name: str, variables: dict[str, str], label: str) -> CompiledPrompt:
        self.calls.append((name, variables, label))
        text = json.dumps(variables)
        return CompiledPrompt(name=name, version=1, label=label, text=text, config=CONFIG)


class FakeLLM:
    """LLMClient that judges each sent incident valid when its ID is in `valid_ids`."""

    def __init__(self, valid_ids: Collection[str]) -> None:
        self.valid_ids = set(valid_ids)
        self.batches: list[list[str]] = []

    def complete[OutputT: BaseModel](
        self, prompt: CompiledPrompt, output_model: type[OutputT]
    ) -> LLMResult[OutputT]:
        sent = [record["id"] for record in json.loads(json.loads(prompt.text)["incidents"])]
        self.batches.append(sent)
        verdicts = [{"id": i, "valid": i in self.valid_ids, "reason": "checked"} for i in sent]
        output = output_model.model_validate({"candidates": verdicts})
        return LLMResult(output=output, model="test-model", input_tokens=1, output_tokens=1)


def screen(
    hit_count: int, valid_numbers: Collection[int], target: int
) -> tuple[list[str], list[str], FakeRepository, FakeLLM]:
    """Run the screener; return valid IDs, checked IDs and the fakes."""
    repository = FakeRepository(hit_count)
    llm = FakeLLM({incident_id(n) for n in valid_numbers})
    search = SearchService(repository, FakeEmbedder(), SETTINGS)
    screener = CandidateScreener(search, FakePrompts(), llm, SETTINGS)
    valid, verdicts = screener.screen("pool exhausted", SearchFilters(), target, "production")
    return [h.id for h in valid], [v.id for v in verdicts], repository, llm


def test_first_batch_asks_for_the_target() -> None:
    valid, _, repository, llm = screen(100, range(1, 101), target=5)

    assert repository.pages == [(5, 0)]
    assert valid == [incident_id(n) for n in range(1, 6)]
    assert len(llm.batches) == 1


def test_batches_never_exceed_the_batch_size() -> None:
    _, _, repository, llm = screen(100, range(1, 101), target=45)

    assert [limit for limit, _ in repository.pages] == [15, 15, 15]
    assert all(len(batch) <= SETTINGS.validation_batch_size for batch in llm.batches)


def test_next_batch_starts_after_the_hits_already_checked() -> None:
    _, checked, repository, _ = screen(100, range(1, 101), target=20)

    assert repository.pages == [(15, 0), (5, 15)]
    assert checked == [incident_id(n) for n in range(1, 21)]


@pytest.mark.parametrize(
    ("valid_in_first", "second_batch"),
    [(8, 3), (5, 10), (2, 15)],
    ids=["high-rate", "half-rate", "low-rate-capped"],
)
def test_next_batch_is_sized_by_the_valid_rate(valid_in_first: int, second_batch: int) -> None:
    _, _, repository, _ = screen(100, range(1, valid_in_first + 1), target=10)

    assert repository.pages[:2] == [(10, 0), (second_batch, 10)]


def test_stops_once_the_target_is_reached_and_trims_to_it() -> None:
    valid, _, repository, llm = screen(100, [*range(1, 9), 11, 12, 13], target=10)

    assert repository.pages == [(10, 0), (3, 10)]
    assert valid == [*(incident_id(n) for n in range(1, 9)), incident_id(11), incident_id(12)]
    assert len(llm.batches) == 2


def test_stops_when_search_has_no_more_hits() -> None:
    valid, _, repository, llm = screen(3, range(1, 4), target=10)

    assert repository.pages == [(10, 0), (7, 3)]
    assert len(valid) == 3
    assert len(llm.batches) == 1


@pytest.mark.parametrize(
    ("valid_numbers", "calls"),
    [([], 1), ([1], 2)],
    ids=["first-batch", "second-batch"],
)
def test_stops_after_a_batch_with_no_valid_hit(valid_numbers: list[int], calls: int) -> None:
    _, _, _, llm = screen(100, valid_numbers, target=5)

    assert len(llm.batches) == calls


def test_stops_after_the_maximum_number_of_calls() -> None:
    one_valid_per_batch = range(1, 101, 15)

    valid, checked, _, llm = screen(100, one_valid_per_batch, target=45)

    assert len(llm.batches) == SETTINGS.validation_max_batches
    assert len(checked) == 60
    assert valid == [incident_id(n) for n in (1, 16, 31, 46)]


def test_every_verdict_is_returned_in_search_order() -> None:
    _, checked, _, _ = screen(100, [2, 4], target=5)

    assert checked == [incident_id(n) for n in range(1, 14)]


def test_prompt_gets_the_label_filters_and_the_hits() -> None:
    prompts = FakePrompts()
    search = SearchService(FakeRepository(2), FakeEmbedder(), SETTINGS)
    screener = CandidateScreener(search, prompts, FakeLLM([incident_id(1)]), SETTINGS)

    screener.screen("pool", SearchFilters(environment=Environment.DEV), 2, "dev")

    name, variables, label = prompts.calls[0]
    assert (name, label) == (PROMPT_NAME, "dev")
    assert json.loads(variables["filters"]) == {"environment": "dev"}
    assert json.loads(variables["incidents"]) == [
        {"id": incident_id(1), "title": "t1", "snippet": "s1"},
        {"id": incident_id(2), "title": "t2", "snippet": "s2"},
    ]


def answer(*verdicts: tuple[str, bool, str]) -> ValidationAnswer:
    candidates = [{"id": i, "valid": valid, "reason": reason} for i, valid, reason in verdicts]
    return ValidationAnswer.model_validate({"candidates": candidates})


def test_ground_verdicts_drops_unknown_ids() -> None:
    raw = answer(("inc-00001", True, "same"), ("inc-99999", True, "invented"))

    assert [v.id for v in ground_verdicts(raw, ["inc-00001"])] == ["inc-00001"]


@pytest.mark.parametrize(
    "verdicts",
    [
        [("inc-00001", True, "same")],
        [("inc-00001", True, "same"), ("inc-00001", False, "x"), ("inc-00002", True, "y")],
        [("inc-00001", True, "same"), ("inc-00002", False, "   ")],
    ],
    ids=["missing", "repeated", "empty-reason"],
)
def test_ground_verdicts_rejects_incomplete_answers(verdicts: list[tuple[str, bool, str]]) -> None:
    with pytest.raises(GroundingFailure):
        ground_verdicts(answer(*verdicts), ["inc-00001", "inc-00002"])
