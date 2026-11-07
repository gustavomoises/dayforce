"""AssistService: no-match path, groups with related, top 5 groups, note, data from records."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment, Incident, Severity
from app.core.models.prompt import CompiledPrompt, LLMConfig, LLMResult
from app.core.models.search import SearchHit
from app.core.settings import Settings
from app.services.assist.models.answer import AssistAnswer
from app.services.assist.models.request import AssistRequest
from app.services.assist.models.validation import CandidateValidation
from app.services.assist.service import NO_MATCH_QUESTIONS, PROMPT_NAME, AssistService
from app.services.incidents.service import IncidentService

SETTINGS = Settings()
CONFIG = LLMConfig(
    model="test-model",
    max_output_tokens=100,
    text={"format": {"type": "json_schema", "name": "assist_answer", "schema": {"a": 1}}},
)
PROMPT_VERSION = 7


def incident_id(number: int) -> str:
    return f"inc-{number:05d}"


def record(number: int) -> Incident:
    return Incident(
        id=incident_id(number),
        created_at=datetime(2026, 1, number, tzinfo=UTC),
        environment=Environment.STAGE,
        service="payments-api",
        severity=Severity.HIGH,
        title=f"Database title {number}",
        description="Connections ran out.",
        resolution_summary="Raised the pool size.",
        tags=("db",),
    )


class FakeScreener:
    """CandidateScreener stand-in that returns fixed valid hits and verdicts."""

    def __init__(self, numbers: Sequence[int], verdicts: list[CandidateValidation]) -> None:
        self.hits = [
            SearchHit(id=incident_id(n), title="hit", snippet="", score=1.0) for n in numbers
        ]
        self.verdicts = verdicts
        self.calls: list[tuple[str, SearchFilters, int, str]] = []

    def screen(
        self, question: str, filters: SearchFilters, target: int, label: str
    ) -> tuple[list[SearchHit], list[CandidateValidation]]:
        self.calls.append((question, filters, target, label))
        return self.hits, self.verdicts


class FakeRepository:
    """IncidentRepository read side over in-memory records."""

    def __init__(self, records: Sequence[Incident]) -> None:
        self.records = {r.id: r for r in records}

    def get(self, incident_id: str) -> Incident | None:
        return self.records.get(incident_id)

    def get_many(self, incident_ids: Sequence[str]) -> list[Incident]:
        return [self.records[i] for i in incident_ids if i in self.records]


class FakePrompts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str], str]] = []

    def get(self, name: str, variables: dict[str, str], label: str) -> CompiledPrompt:
        self.calls.append((name, variables, label))
        return CompiledPrompt(
            name=name, version=PROMPT_VERSION, label=label, text="prompt", config=CONFIG
        )


class FakeLLM:
    """LLMClient that returns one fixed assist answer."""

    def __init__(self, answer: AssistAnswer | None = None) -> None:
        self.answer = answer
        self.calls = 0

    def complete[OutputT: BaseModel](
        self, prompt: CompiledPrompt, output_model: type[OutputT]
    ) -> LLMResult[OutputT]:
        self.calls += 1
        output = output_model.model_validate(self.answer.model_dump())
        return LLMResult(output=output, model="test-model", input_tokens=1, output_tokens=1)


def relevant(number: int, rank: int, group: int) -> dict[str, Any]:
    return {
        "id": incident_id(number),
        "relevant": True,
        "reason": f"reason {number}",
        "rank": rank,
        "rank_justification": "close match",
        "group": group,
        "group_reason": "same root cause",
    }


def not_relevant(number: int) -> dict[str, Any]:
    return {
        "id": incident_id(number),
        "relevant": False,
        "reason": "different problem",
        "rank": None,
        "rank_justification": None,
        "group": None,
        "group_reason": None,
    }


def assist_answer(
    candidates: list[dict[str, Any]], next_steps: list[str] | None = None
) -> AssistAnswer:
    return AssistAnswer.model_validate(
        {
            "candidates": candidates,
            "next_steps": next_steps or [],
            "customer_draft": "We are looking into it.",
            "missing_info": ["Which region?"],
        }
    )


class Harness:
    """AssistService wired to fakes, keeping the fakes for assertions."""

    def __init__(self, numbers: Sequence[int], answer: AssistAnswer | None = None) -> None:
        verdicts = [
            CandidateValidation(id=incident_id(n), valid=True, reason="same") for n in numbers
        ]
        self.screener = FakeScreener(numbers, verdicts)
        self.prompts = FakePrompts()
        self.llm = FakeLLM(answer)
        incidents = IncidentService(FakeRepository([record(n) for n in range(1, 21)]))
        self.service = AssistService(self.screener, incidents, self.prompts, self.llm, SETTINGS)

    def assist(self, multiplier: int = 3, label: str = "production") -> Any:
        request = AssistRequest(question="pool exhausted", candidate_multiplier=multiplier)
        return self.service.assist(request, label)


def test_no_valid_hit_skips_the_assist_call() -> None:
    harness = Harness([])
    harness.screener.verdicts = [CandidateValidation(id=incident_id(1), valid=False, reason="no")]

    response = harness.assist()

    assert (harness.llm.calls, harness.prompts.calls) == (0, [])
    assert response.status == "no_relevant_incidents"
    assert response.relevant_incidents == []
    assert response.missing_info == list(NO_MATCH_QUESTIONS)
    assert response.validation == harness.screener.verdicts


@pytest.mark.parametrize("multiplier", [1, 3, 5])
def test_screener_target_is_multiplier_times_max_results(multiplier: int) -> None:
    harness = Harness([])

    harness.assist(multiplier=multiplier, label="dev")

    _, _, target, label = harness.screener.calls[0]
    assert (target, label) == (multiplier * SETTINGS.assist_max_results, "dev")


def test_only_valid_hits_are_sent_to_the_prompt() -> None:
    harness = Harness([2, 5], assist_answer([relevant(2, 1, 1), not_relevant(5)]))

    harness.assist(label="qa")

    name, variables, label = harness.prompts.calls[0]
    assert (name, label, harness.llm.calls) == (PROMPT_NAME, "qa", 1)
    assert [r["id"] for r in json.loads(variables["incidents"])] == [incident_id(2), incident_id(5)]


def test_groups_are_led_by_their_best_rank_with_the_rest_as_related() -> None:
    answer = assist_answer([relevant(1, 1, 1), relevant(2, 3, 1), relevant(3, 2, 2)])

    response = Harness([1, 2, 3], answer).assist()

    assert [(e.id, e.group, e.rank) for e in response.relevant_incidents] == [
        (incident_id(1), 1, 1),
        (incident_id(3), 2, 2),
    ]
    assert [(r.id, r.rank) for r in response.relevant_incidents[0].related] == [(incident_id(2), 3)]
    assert response.relevant_incidents[1].related == []


def test_top_five_counts_groups_not_incidents() -> None:
    candidates = [relevant(1, 1, 1), relevant(2, 2, 1)] + [
        relevant(n, n, n - 1) for n in range(3, 9)
    ]

    response = Harness(range(1, 9), assist_answer(candidates)).assist()

    assert len(response.relevant_incidents) == SETTINGS.assist_max_results
    assert [e.group for e in response.relevant_incidents] == [1, 2, 3, 4, 5]
    assert len(response.relevant_incidents[0].related) == 1


@pytest.mark.parametrize(
    ("candidates", "note"),
    [
        ([relevant(1, 1, 1)], "only 1 distinct problem found"),
        ([relevant(1, 1, 1), relevant(2, 2, 1)], "only 1 distinct problem found"),
        ([relevant(1, 1, 1), relevant(2, 2, 2)], "only 2 distinct problems found"),
        ([relevant(1, 1, 1), relevant(2, 2, 2), relevant(3, 3, 3)], None),
    ],
    ids=["one-incident", "one-group-of-two", "two-groups", "three-groups"],
)
def test_note_counts_distinct_problems(candidates: list[dict[str, Any]], note: str | None) -> None:
    numbers = [int(c["id"][-5:]) for c in candidates]

    response = Harness(numbers, assist_answer(candidates)).assist()

    assert response.status == "answered"
    assert response.note == note


def test_incident_fields_come_from_the_records() -> None:
    answer = assist_answer([relevant(4, 1, 1), relevant(9, 2, 1)])

    response = Harness([4, 9], answer).assist()

    lead = response.relevant_incidents[0]
    related = lead.related[0]
    for entry, source in ((lead, record(4)), (related, record(9))):
        assert (entry.title, entry.environment, entry.severity, entry.created_at) == (
            source.title,
            source.environment,
            source.severity,
            source.created_at,
        )


def test_unknown_ids_from_the_llm_never_reach_the_response() -> None:
    invented = incident_id(99999)
    candidates = [{**relevant(1, 1, 1), "id": invented}, relevant(2, 2, 1), not_relevant(3)]
    steps = [f"Restart the pool [{invented}]", f"Raise the pool size [{incident_id(2)}]"]

    response = Harness([2, 3], assist_answer(candidates, steps)).assist()

    assert invented not in response.model_dump_json()
    assert [e.id for e in response.relevant_incidents] == [incident_id(2)]
    assert response.relevant_incidents[0].rank == 1
    assert response.next_steps == [f"Raise the pool size [{incident_id(2)}]"]


def test_no_relevant_candidate_keeps_the_llm_missing_info() -> None:
    response = Harness([1, 2], assist_answer([not_relevant(1), not_relevant(2)])).assist()

    assert response.status == "no_relevant_incidents"
    assert (response.relevant_incidents, response.note) == ([], None)
    assert response.missing_info == ["Which region?"]
    assert len(response.candidates) == 2


def test_answer_reports_the_prompt_version_and_verdicts() -> None:
    harness = Harness([1], assist_answer([relevant(1, 1, 1)]))

    response = harness.assist()

    assert response.prompt_version == PROMPT_VERSION
    assert response.validation == harness.screener.verdicts
