"""Hypothesis checks of design Properties 1, 2, 3, 9, 10 and 11."""

import copy
import string
from collections import Counter
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from app.core.errors import GroundingFailure
from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment, Incident, Severity
from app.core.models.prompt import CompiledPrompt, EmbeddingResult, LLMConfig, LLMResult
from app.core.models.search import SearchHit, SearchQuery
from app.core.models.storage import (
    EmbeddedRow,
    ExistingIncident,
    IncidentRecord,
    PendingEmbedding,
    TypeSets,
)
from app.core.settings import Settings
from app.services.assist import guardrails
from app.services.assist.models.answer import AssistAnswer
from app.services.assist.models.request import AssistRequest
from app.services.assist.service import AssistService
from app.services.incidents.service import IncidentService
from app.services.ingest.models import IncidentIn
from app.services.ingest.plan import to_record
from app.services.ingest.service import IngestService
from app.support.database.query_builder import build_count, build_search

SETTINGS = Settings(embedding_dimensions=2)
SERVICES = ("payments-api", "auth-service")
TYPES = TypeSets(
    environments=frozenset(e.value for e in Environment),
    services=frozenset(SERVICES),
    severities=frozenset(s.value for s in Severity),
)
FEW = settings(max_examples=60, deadline=None)

words = st.lists(st.text(string.ascii_lowercase, min_size=1, max_size=8), min_size=1, max_size=6)
free_text = st.text(string.ascii_letters + string.digits + " .,!?'-é", max_size=60)


@st.composite
def messy(draw: st.DrawFn, value: str) -> str:
    """`value` with random letter case and padding spaces."""
    flips = draw(st.lists(st.booleans(), min_size=len(value), max_size=len(value)))
    cased = "".join(c.upper() if flip else c for c, flip in zip(value, flips, strict=True))
    return draw(st.sampled_from(["", " ", "  "])) + cased + draw(st.sampled_from(["", " "]))


@st.composite
def messy_words(draw: st.DrawFn, value: list[str]) -> str:
    """Words joined by extra spaces and punctuation at word ends, in random case."""
    gaps = st.sampled_from([" ", "  ", ", ", "! ", " - ", "? "])
    parts = [draw(messy(word)).strip() + draw(gaps) for word in value]
    return draw(st.sampled_from(["", "  "])) + "".join(parts)


def incident_in(number: int, **fields: Any) -> IncidentIn:
    base: dict[str, Any] = {
        "id": f"inc-{number:05d}",
        "created_at": datetime(2026, 3, 1, tzinfo=UTC),
        "environment": "prod",
        "service": SERVICES[0],
        "severity": "high",
        "title": "Pool exhausted",
        "description": "Connections ran out.",
        "resolution_summary": "Raised the pool size.",
        "tags": ["db"],
    }
    return IncidentIn(**{**base, **fields})


def record_of(item: IncidentIn) -> IncidentRecord:
    record = to_record(item, TYPES)
    assert isinstance(record, IncidentRecord)
    return record


@FEW
@given(
    environment=st.sampled_from([e.value for e in Environment]).flatmap(messy),
    service=st.sampled_from(SERVICES).flatmap(messy),
    severity=st.sampled_from([s.value for s in Severity]).flatmap(messy),
    title=free_text.filter(str.strip),
    description=free_text,
    tags=st.lists(st.text(string.ascii_letters + " -", max_size=12), max_size=20),
)
def test_property_1_normalization_is_idempotent(
    environment: str, service: str, severity: str, title: str, description: str, tags: list[str]
) -> None:
    item = incident_in(
        1,
        environment=environment,
        service=service,
        severity=severity,
        title=title,
        description=description,
        tags=tags,
    )

    once = record_of(item)
    twice = record_of(IncidentIn.model_validate(once.incident.model_dump(mode="json")))

    assert twice == once
    normalized = list(once.incident.tags)
    assert normalized == sorted(set(normalized))
    assert all(tag and tag == tag.lower() == tag.strip() for tag in normalized)


@FEW
@given(data=st.data(), title=words, description=words, tags=words)
def test_property_2_content_hash_ignores_formatting(
    data: st.DataObject, title: list[str], description: list[str], tags: list[str]
) -> None:
    base = incident_in(1, title=" ".join(title), description=" ".join(description), tags=tags)
    shuffled = data.draw(st.permutations(tags + tags[:1]))
    variant = incident_in(
        data.draw(st.integers(2, 99999)),
        created_at=datetime(2026, 9, data.draw(st.integers(1, 30)), tzinfo=UTC),
        title=data.draw(messy_words(title)),
        description=data.draw(messy_words(description)),
        tags=[data.draw(messy(tag)) for tag in shuffled],
    )

    assert record_of(variant).content_hash == record_of(base).content_hash


@FEW
@given(
    data=st.data(),
    field=st.sampled_from(["title", "description", "resolution_summary", "tags"]),
    value=words,
)
def test_property_2_content_hash_changes_with_the_words(
    data: st.DataObject, field: str, value: list[str]
) -> None:
    position = data.draw(st.integers(0, len(value) - 1))
    other = data.draw(st.text(string.ascii_lowercase, min_size=1, max_size=8))
    changed = [*value[:position], other, *value[position + 1 :]]
    assume(set(changed) != set(value))

    def as_field(word_list: list[str]) -> str | list[str]:
        return word_list if field == "tags" else " ".join(word_list)

    before = record_of(incident_in(1, **{field: as_field(value)}))
    after = record_of(incident_in(1, **{field: as_field(changed)}))

    assert before.content_hash != after.content_hash


class MemoryUnitOfWork:
    """IncidentUnitOfWork over committed rows and embedded IDs."""

    def __init__(self, rows: dict[str, IncidentRecord], embedded: set[str]) -> None:
        self.rows, self.embedded = rows, embedded

    def load_types(self) -> TypeSets:
        return TYPES

    def find_existing(
        self, ids: Sequence[str], content_hashes: Sequence[str]
    ) -> tuple[dict[str, ExistingIncident], dict[str, str]]:
        rows = self.rows
        found = {
            i: ExistingIncident(id=i, content_hash=rows[i].content_hash) for i in ids if i in rows
        }
        owners = {r.content_hash: i for i, r in rows.items() if r.content_hash in content_hashes}
        return found, owners

    def insert(self, records: Sequence[IncidentRecord]) -> None:
        self.rows.update({r.incident.id: r for r in records})

    def update(self, records: Sequence[IncidentRecord]) -> None:
        for r in records:
            if self.rows[r.incident.id].embedding_text_hash != r.embedding_text_hash:
                self.embedded.discard(r.incident.id)
            self.rows[r.incident.id] = r

    def lock_pending_embeddings(self, model: str, limit: int) -> list[PendingEmbedding]:
        pending = sorted(set(self.rows) - self.embedded)[:limit]
        return [
            PendingEmbedding(id=i, title="t", description="", resolution_summary="")
            for i in pending
        ]

    def save_embeddings(self, rows: Sequence[EmbeddedRow]) -> None:
        self.embedded.update(r.id for r in rows)

    def count_pending_embeddings(self, model: str) -> int:
        return len(set(self.rows) - self.embedded)


class MemoryRepository:
    """Commits a unit of work on normal exit, discards it on exception."""

    def __init__(self) -> None:
        self.rows: dict[str, IncidentRecord] = {}
        self.embedded: set[str] = set()

    @contextmanager
    def unit_of_work(self) -> Iterator[MemoryUnitOfWork]:
        uow = MemoryUnitOfWork(copy.deepcopy(self.rows), set(self.embedded))
        yield uow
        self.rows, self.embedded = uow.rows, uow.embedded


class FixedEmbedder:
    def embed_batch(self, texts: Sequence[str]) -> EmbeddingResult:
        return EmbeddingResult(vectors=[[0.1, 0.2] for _ in texts], model="m", total_tokens=1)


def ingest_twice(batch: list[IncidentIn]) -> tuple[Any, Any, Any]:
    repository = MemoryRepository()
    service = IngestService(repository, FixedEmbedder(), SETTINGS)
    service.ingest(batch)
    state = (copy.deepcopy(repository.rows), set(repository.embedded))
    second = service.ingest(batch)
    return state, (repository.rows, repository.embedded), second


@FEW
@given(
    numbers=st.lists(st.integers(1, 99999), min_size=1, max_size=8, unique=True),
    data=st.data(),
)
def test_property_3_ingest_is_idempotent(numbers: list[int], data: st.DataObject) -> None:
    batch = [
        incident_in(
            n,
            title=f"case{n} " + " ".join(data.draw(words)),
            severity=data.draw(st.sampled_from([s.value for s in Severity])),
            tags=data.draw(words),
        )
        for n in numbers
    ]

    after_first, after_second, second = ingest_twice(batch)

    assert after_second == after_first
    assert second.skipped == len(batch)
    assert (second.ingested, second.updated, second.duplicates, second.invalid) == (0, 0, 0, 0)


def test_property_3_repeated_id_last_version_wins() -> None:
    batch = [incident_in(1, title="Pool exhausted"), incident_in(1, title="Pool drained")]

    after_first, after_second, second = ingest_twice(batch)

    rows, _ = after_first
    assert rows["inc-00001"].incident.title == "Pool drained"
    assert after_second == after_first
    assert second.embedded == 0


user_values = st.text(min_size=1, max_size=40)


@FEW
@given(
    text=user_values,
    service=st.one_of(st.none(), user_values),
    tags=st.lists(user_values, max_size=4),
    environment=st.one_of(st.none(), st.sampled_from(Environment)),
    severity=st.one_of(st.none(), st.sampled_from(Severity)),
    with_vector=st.booleans(),
)
def test_property_9_queries_are_parameterized(
    text: str,
    service: str | None,
    tags: list[str],
    environment: Environment | None,
    severity: Severity | None,
    with_vector: bool,
) -> None:
    def query(text: str, service: str | None, tags: Sequence[str]) -> SearchQuery:
        filters = SearchFilters(
            environment=environment, service=service, severity=severity, tags=tuple(tags)
        )
        vector = [0.1, 0.2] if with_vector else None
        return SearchQuery(
            filters=filters,
            text=text,
            vector=vector,
            limit=10,
            branch_limit=50,
            min_similarity=0.3,
            rrf_k=60,
        )

    user = query(text, service, tags)
    placeholder = query(
        "placeholder" if text.strip() else " ",
        None if service is None else "placeholder",
        [f"tag{n}" for n in range(len(set(tags)))],
    )

    for build in (build_search, build_count):
        built = build(user)
        assert built.sql == build(placeholder).sql
        assert (built.params["text"], built.params["service"]) == (text, service)
        assert built.params["tags"] == sorted(set(tags))


SENT = ["inc-00001", "inc-00002", "inc-00003", "inc-00004"]
reasons = st.sampled_from(["matches", "", "  "])
optional_text = st.sampled_from([None, "", "same cause"])


@st.composite
def raw_assessment(draw: st.DrawFn, incident_id: str) -> dict[str, Any]:
    """An assessment whose fields may be inconsistent."""
    return {
        "id": incident_id,
        "relevant": draw(st.booleans()),
        "reason": draw(reasons),
        "rank": draw(st.one_of(st.none(), st.integers(1, 6))),
        "rank_justification": draw(optional_text),
        "group": draw(st.one_of(st.none(), st.integers(1, 3))),
        "group_reason": draw(optional_text),
    }


def expected_to_accept(candidates: list[dict[str, Any]], missing_info: list[str]) -> bool:
    """Oracle for Property 10, written from the statement rather than the code."""
    known = [c for c in candidates if c["id"] in SENT]
    if sorted(c["id"] for c in known) != sorted(SENT):
        return False
    texts = ("rank_justification", "group_reason")
    for c in known:
        if not c["reason"].strip():
            return False
        filled = c["rank"] is not None and c["group"] is not None
        if c["relevant"] and not (filled and all(c[t] and c[t].strip() for t in texts)):
            return False
        if not c["relevant"] and any(c[key] is not None for key in ("rank", "group", *texts)):
            return False
    ranks = [c["rank"] for c in known if c["relevant"]]
    if len(ranks) != len(set(ranks)):
        return False
    return bool(ranks) or any(item.strip() for item in missing_info)


@FEW
@given(
    candidates=st.lists(
        st.sampled_from([*SENT, "inc-99999"]).flatmap(raw_assessment), min_size=3, max_size=6
    ),
    missing_info=st.lists(st.sampled_from(["", "Which region?"]), max_size=2),
)
def test_property_10_guardrails_accept_only_grounded_answers(
    candidates: list[dict[str, Any]], missing_info: list[str]
) -> None:
    answer = AssistAnswer(
        candidates=candidates, next_steps=[], customer_draft="", missing_info=missing_info
    )

    try:
        grounded = guardrails.ground(answer, SENT)
    except GroundingFailure:
        assert not expected_to_accept(candidates, missing_info)
        return

    assert expected_to_accept(candidates, missing_info)
    assert Counter(c.id for c in grounded.candidates) == Counter(SENT)
    relevant = [c for c in grounded.candidates if c.relevant]
    assert sorted(c.rank for c in relevant) == list(range(1, len(relevant) + 1))
    assert all(c.rank is None and c.group is None for c in grounded.candidates if not c.relevant)
    assert all(c.reason.strip() for c in grounded.candidates)


class FixedScreener:
    def __init__(self, ids: Sequence[str]) -> None:
        self.hits = [SearchHit(id=i, title="hit", snippet="", score=1.0) for i in ids]

    def screen(self, *args: Any) -> tuple[list[SearchHit], list[Any]]:
        return self.hits, []


class RecordRepository:
    def get_many(self, incident_ids: Sequence[str]) -> list[Incident]:
        return [
            Incident(
                id=i,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                environment=Environment.PROD,
                service=SERVICES[0],
                severity=Severity.LOW,
                title=f"title {i}",
                description="",
                resolution_summary="",
                tags=(),
            )
            for i in incident_ids
        ]


class FixedPrompts:
    def get(self, name: str, variables: dict[str, str], label: str) -> CompiledPrompt:
        config = LLMConfig(
            model="m",
            max_output_tokens=10,
            text={"format": {"type": "json_schema", "name": "assist_answer", "schema": {"a": 1}}},
        )
        return CompiledPrompt(name=name, version=1, label=label, text="", config=config)


class FixedLLM:
    def __init__(self, answer: AssistAnswer) -> None:
        self.answer = answer

    def complete[OutputT: BaseModel](
        self, prompt: CompiledPrompt, output_model: type[OutputT]
    ) -> LLMResult[OutputT]:
        output = output_model.model_validate(self.answer.model_dump())
        return LLMResult(output=output, model="m", input_tokens=1, output_tokens=1)


@st.composite
def accepted_answers(draw: st.DrawFn) -> AssistAnswer:
    """Consistent answers: unique, possibly gapped ranks; any grouping."""
    count = draw(st.integers(1, 10))
    ids = [f"inc-{n:05d}" for n in range(1, count + 1)]
    flags = draw(st.lists(st.booleans(), min_size=count, max_size=count))
    ranks = iter(draw(st.lists(st.integers(1, 40), min_size=count, max_size=count, unique=True)))
    candidates = []
    for incident_id, is_relevant in zip(ids, flags, strict=True):
        filled = {
            "rank": next(ranks),
            "rank_justification": "close",
            "group": draw(st.integers(1, 8)),
            "group_reason": "same cause",
        }
        empty = dict.fromkeys(filled)
        fields = filled if is_relevant else empty
        candidates.append({"id": incident_id, "relevant": is_relevant, "reason": "r", **fields})
    return AssistAnswer(
        candidates=candidates, next_steps=[], customer_draft="", missing_info=["Which region?"]
    )


@FEW
@given(answer=accepted_answers())
def test_property_11_assist_never_pads(answer: AssistAnswer) -> None:
    ids = [c.id for c in answer.candidates]
    incidents = IncidentService(RecordRepository())
    service = AssistService(
        FixedScreener(ids), incidents, FixedPrompts(), FixedLLM(answer), SETTINGS
    )

    response = service.assist(AssistRequest(question="pool"), "production")

    relevant = [c for c in answer.candidates if c.relevant]
    group_count = len({c.group for c in relevant})
    entries = response.relevant_incidents
    assert len(entries) == min(group_count, SETTINGS.assist_max_results)
    assert [e.rank for e in entries] == sorted(e.rank for e in entries)
    assert (response.status == "no_relevant_incidents") == (not relevant)
