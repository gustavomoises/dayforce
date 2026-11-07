"""Pure checks on the LLM's assist answer. Any violation rejects the whole answer."""

from collections import Counter
from collections.abc import Sequence

from app.core.errors import GroundingFailure
from app.services.assist.models.answer import AssistAnswer, CandidateAssessment


def validate(
    answer: AssistAnswer, candidate_ids: Sequence[str], max_results: int
) -> list[CandidateAssessment]:
    """Ranked relevant assessments sorted by rank, at most `max_results`, never padded."""
    _check_coverage([c.id for c in answer.candidates], candidate_ids)
    for candidate in answer.candidates:
        _check_assessment(candidate)
    ranked = sorted(
        (c for c in answer.candidates if c.relevant and c.related_to is None),
        key=lambda c: c.rank or 0,
    )
    _check_ranks([c.rank or 0 for c in ranked])
    _check_related_targets(answer.candidates, {c.id for c in ranked})
    if not ranked and not any(item.strip() for item in answer.missing_info):
        raise GroundingFailure("no candidate is relevant, so missing_info must not be empty")
    return ranked[:max_results]


def related_by_ranked(answer: AssistAnswer) -> dict[str, list[CandidateAssessment]]:
    """For each ranked id, the relevant candidates the LLM attached to it, in answer order."""
    related: dict[str, list[CandidateAssessment]] = {}
    for candidate in answer.candidates:
        if candidate.relevant and candidate.related_to is not None:
            related.setdefault(candidate.related_to, []).append(candidate)
    return related


def _check_coverage(answered_ids: Sequence[str], candidate_ids: Sequence[str]) -> None:
    """Every retrieved ID exactly once, and no other ID."""
    repeated = sorted(i for i, count in Counter(answered_ids).items() if count > 1)
    if repeated:
        raise GroundingFailure(f"candidates repeated in the answer: {repeated}")
    unknown = sorted(set(answered_ids) - set(candidate_ids))
    if unknown:
        raise GroundingFailure(f"unknown candidate ids in the answer: {unknown}")
    missing = [i for i in candidate_ids if i not in set(answered_ids)]
    if missing:
        raise GroundingFailure(f"candidates missing from the answer: {missing}")


def _check_assessment(candidate: CandidateAssessment) -> None:
    if not candidate.reason.strip():
        raise GroundingFailure(f"candidate {candidate.id} has an empty reason")
    has_rank = candidate.rank is not None or candidate.rank_justification is not None
    if not candidate.relevant:
        if has_rank or candidate.related_to is not None:
            raise GroundingFailure(
                f"candidate {candidate.id} is not relevant, so rank, rank_justification "
                "and related_to must be null"
            )
    elif candidate.related_to is not None:
        if has_rank:
            raise GroundingFailure(
                f"candidate {candidate.id} is related to {candidate.related_to}, "
                "so rank and rank_justification must be null"
            )
    elif candidate.rank is None or not (candidate.rank_justification or "").strip():
        raise GroundingFailure(
            f"ranked candidate {candidate.id} needs a rank and a rank_justification"
        )


def _check_ranks(ranks: Sequence[int]) -> None:
    """Ranks of ranked candidates are 1..k with no gaps or repeats."""
    expected = list(range(1, len(ranks) + 1))
    if list(ranks) != expected:
        raise GroundingFailure(f"ranks of relevant candidates must be {expected}, got {ranks}")


def _check_related_targets(candidates: Sequence[CandidateAssessment], ranked_ids: set[str]) -> None:
    """`related_to` must point at a ranked candidate, never at itself or a related one."""
    bad = sorted(
        c.id for c in candidates if c.related_to is not None and c.related_to not in ranked_ids
    )
    if bad:
        raise GroundingFailure(f"related_to must name a ranked candidate: {bad}")
