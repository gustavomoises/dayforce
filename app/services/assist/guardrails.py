"""Never trust the LLM with real data: keep only what matches the input, then check the rest.

IDs the LLM was not given are removed, as are next steps citing them. Answers that are
incomplete or inconsistent (a candidate missing or repeated, a relevant one without a rank)
reject the whole answer.
"""

import logging
import re
from collections import Counter
from collections.abc import Sequence

from app.core.errors import GroundingFailure
from app.core.models.incident import INCIDENT_ID_PATTERN
from app.services.assist.models.answer import AssistAnswer, CandidateAssessment

logger = logging.getLogger(__name__)

_CITED_ID = re.compile(INCIDENT_ID_PATTERN.strip("^$"))


def ground(answer: AssistAnswer, candidate_ids: Sequence[str]) -> AssistAnswer:
    """The answer restricted to the input: unknown IDs dropped, ranks and groups renumbered."""
    known = set(candidate_ids)
    unknown = sorted({c.id for c in answer.candidates} - known)
    candidates = [c for c in answer.candidates if c.id in known]
    _check_coverage([c.id for c in candidates], candidate_ids)
    for candidate in candidates:
        _check_assessment(candidate)
    candidates = _renumber(candidates)
    relevant_ids = {c.id for c in candidates if c.relevant}
    steps = [step for step in answer.next_steps if _cites_only(step, relevant_ids)]
    if unknown or len(steps) < len(answer.next_steps):
        logger.warning(
            "step grounding dropped",
            extra={"unknown_ids": unknown, "dropped_steps": len(answer.next_steps) - len(steps)},
        )
    if not relevant_ids and not any(item.strip() for item in answer.missing_info):
        raise GroundingFailure("no candidate is relevant, so missing_info must not be empty")
    return answer.model_copy(update={"candidates": candidates, "next_steps": steps})


def group(answer: AssistAnswer, max_groups: int) -> list[list[CandidateAssessment]]:
    """Relevant assessments by group, best group first, each sorted by rank; never padded."""
    groups: dict[int | None, list[CandidateAssessment]] = {}
    for candidate in sorted((c for c in answer.candidates if c.relevant), key=_rank):
        groups.setdefault(candidate.group, []).append(candidate)
    return list(groups.values())[:max_groups]


def _check_coverage(answered_ids: Sequence[str], candidate_ids: Sequence[str]) -> None:
    """Every retrieved ID judged exactly once."""
    repeated = sorted(i for i, count in Counter(answered_ids).items() if count > 1)
    if repeated:
        raise GroundingFailure(f"candidates repeated in the answer: {repeated}")
    missing = [i for i in candidate_ids if i not in set(answered_ids)]
    if missing:
        raise GroundingFailure(f"candidates missing from the answer: {missing}")


def _check_assessment(candidate: CandidateAssessment) -> None:
    if not candidate.reason.strip():
        raise GroundingFailure(f"candidate {candidate.id} has an empty reason")
    texts = (candidate.rank_justification, candidate.group_reason)
    complete = candidate.rank is not None and candidate.group is not None
    if candidate.relevant and not (complete and all(t and t.strip() for t in texts)):
        raise GroundingFailure(
            f"relevant candidate {candidate.id} needs a rank, a rank_justification, "
            "a group and a group_reason"
        )
    if not candidate.relevant and (
        candidate.rank is not None
        or candidate.group is not None
        or any(t is not None for t in texts)
    ):
        raise GroundingFailure(
            f"candidate {candidate.id} is not relevant, "
            "so rank, rank_justification, group and group_reason must be null"
        )


def _renumber(candidates: Sequence[CandidateAssessment]) -> list[CandidateAssessment]:
    """Ranks 1..k in rank order and groups 1..g by first appearance, so drops leave no gaps."""
    relevant = sorted((c for c in candidates if c.relevant), key=_rank)
    repeated = sorted(r for r, count in Counter(_rank(c) for c in relevant).items() if count > 1)
    if repeated:
        raise GroundingFailure(f"ranks repeated in the answer: {repeated}")
    ranks = {c.id: n for n, c in enumerate(relevant, start=1)}
    groups = {g: n for n, g in enumerate(dict.fromkeys(c.group for c in relevant), start=1)}
    return [
        c.model_copy(update={"rank": ranks[c.id], "group": groups[c.group]}) if c.relevant else c
        for c in candidates
    ]


def _cites_only(step: str, relevant_ids: set[str]) -> bool:
    """A next step must cite at least one incident, and only relevant ones."""
    cited = set(_CITED_ID.findall(step))
    return bool(cited) and cited <= relevant_ids


def _rank(candidate: CandidateAssessment) -> int:
    return candidate.rank or 0
