"""Pure checks on the LLM's assist answer. Any violation rejects the whole answer."""

from collections import Counter
from collections.abc import Sequence

from app.core.errors import GroundingFailure
from app.services.assist.models.answer import AssistAnswer, CandidateAssessment


def validate(
    answer: AssistAnswer, candidate_ids: Sequence[str], max_results: int
) -> list[CandidateAssessment]:
    """Relevant assessments sorted by rank, at most `max_results`, never padded."""
    _check_coverage([c.id for c in answer.candidates], candidate_ids)
    for candidate in answer.candidates:
        _check_assessment(candidate)
    relevant = sorted((c for c in answer.candidates if c.relevant), key=lambda c: c.rank or 0)
    _check_ranks([c.rank or 0 for c in relevant])
    if not relevant and not any(item.strip() for item in answer.missing_info):
        raise GroundingFailure("no candidate is relevant, so missing_info must not be empty")
    return relevant[:max_results]


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
    justified = bool(candidate.rank_justification and candidate.rank_justification.strip())
    if candidate.relevant and (candidate.rank is None or not justified):
        raise GroundingFailure(
            f"relevant candidate {candidate.id} needs a rank and a rank_justification"
        )
    if not candidate.relevant and (
        candidate.rank is not None or candidate.rank_justification is not None
    ):
        raise GroundingFailure(
            f"candidate {candidate.id} is not relevant, so rank and rank_justification must be null"
        )


def _check_ranks(ranks: Sequence[int]) -> None:
    """Ranks of relevant candidates are 1..k with no gaps or repeats."""
    expected = list(range(1, len(ranks) + 1))
    if list(ranks) != expected:
        raise GroundingFailure(f"ranks of relevant candidates must be {expected}, got {ranks}")
