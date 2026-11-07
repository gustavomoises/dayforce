"""Guardrails: the assist answer is restricted to the incidents sent to the LLM."""

import pytest

from app.core.errors import GroundingFailure
from app.services.assist import guardrails
from app.services.assist.models.answer import AssistAnswer

SENT = ["inc-00001", "inc-00002", "inc-00003"]


def assessment(incident_id: str, rank: int | None = None, group: int | None = None) -> dict:
    relevant = rank is not None
    return {
        "id": incident_id,
        "relevant": relevant,
        "reason": "matches the question",
        "rank": rank,
        "rank_justification": "closest match" if relevant else None,
        "group": group,
        "group_reason": "same cause and fix" if relevant else None,
    }


def answer(candidates: list[dict], next_steps: list[str] | None = None) -> AssistAnswer:
    return AssistAnswer.model_validate(
        {
            "candidates": candidates,
            "next_steps": next_steps or [],
            "customer_draft": "draft",
            "missing_info": [],
        }
    )


def test_unknown_ids_are_removed_and_ranks_and_groups_renumbered() -> None:
    raw = answer(
        [
            assessment("inc-99999", rank=1, group=1),
            assessment("inc-00001", rank=2, group=1),
            assessment("inc-00002", rank=4, group=3),
            assessment("inc-00003"),
        ]
    )

    grounded = guardrails.ground(raw, SENT)

    assert [(c.id, c.rank, c.group) for c in grounded.candidates] == [
        ("inc-00001", 1, 1),
        ("inc-00002", 2, 2),
        ("inc-00003", None, None),
    ]


def test_next_steps_must_cite_only_relevant_incidents() -> None:
    raw = answer(
        [
            assessment("inc-00001", rank=1, group=1),
            assessment("inc-00002"),
            assessment("inc-00003"),
        ],
        next_steps=[
            "Roll back the deploy [inc-00001]",
            "Invented fix [inc-99999]",
            "Step with no source",
            "Mixed sources [inc-00001, inc-00002]",
        ],
    )

    assert guardrails.ground(raw, SENT).next_steps == ["Roll back the deploy [inc-00001]"]


def test_groups_are_led_by_their_best_ranked_incident() -> None:
    raw = answer(
        [
            assessment("inc-00003", rank=3, group=2),
            assessment("inc-00001", rank=1, group=1),
            assessment("inc-00002", rank=2, group=1),
        ]
    )

    groups = guardrails.group(guardrails.ground(raw, SENT), max_groups=5)

    assert [[c.id for c in g] for g in groups] == [["inc-00001", "inc-00002"], ["inc-00003"]]


def test_groups_are_capped_and_never_padded() -> None:
    raw = answer([assessment(i, rank=n, group=n) for n, i in enumerate(SENT, start=1)])

    assert len(guardrails.group(guardrails.ground(raw, SENT), max_groups=2)) == 2


@pytest.mark.parametrize(
    "candidates",
    [
        [assessment("inc-00001", rank=1, group=1), assessment("inc-00002")],
        [assessment(i) for i in [*SENT, "inc-00001"]],
        [
            assessment("inc-00001", rank=1, group=1),
            assessment("inc-00002", rank=1, group=1),
            assessment("inc-00003"),
        ],
        [
            {**assessment("inc-00001", rank=1, group=1), "group_reason": None},
            *map(assessment, SENT[1:]),
        ],
        [{**assessment("inc-00001"), "rank": 1}, *map(assessment, SENT[1:])],
    ],
    ids=["missing", "repeated", "repeated-rank", "no-group-reason", "rank-when-not-relevant"],
)
def test_inconsistent_answers_are_rejected(candidates: list[dict]) -> None:
    with pytest.raises(GroundingFailure):
        guardrails.ground(answer(candidates), SENT)


def test_no_relevant_incident_requires_missing_info() -> None:
    with pytest.raises(GroundingFailure):
        guardrails.ground(answer([assessment(i) for i in SENT]), SENT)
