"""Validate search hits in small batches until enough valid candidates are found.

One LLM call per batch of at most VALIDATION_BATCH_SIZE hits, most similar first; each next
batch starts where the last one ended and is sized by the valid rate seen so far. It stops as
soon as `target` hits are valid, when search runs out, when a whole batch is invalid (later
hits are less similar still), or after VALIDATION_MAX_BATCHES calls.
"""

import json
import logging
import math
from collections import Counter
from collections.abc import Sequence

from app.core.errors import GroundingFailure
from app.core.models.filters import SearchFilters
from app.core.models.search import SearchHit
from app.core.ports import LLMClient, PromptProvider
from app.core.settings import Settings
from app.services.assist.models.validation import CandidateValidation, ValidationAnswer
from app.services.search.service import SearchService
from app.support.tracing.span import traced

logger = logging.getLogger(__name__)

PROMPT_NAME = "incident-validation"


class CandidateScreener:
    """Returns valid hits in search order plus every verdict, for the response and the trace."""

    def __init__(
        self,
        search: SearchService,
        prompts: PromptProvider,
        llm: LLMClient,
        settings: Settings,
    ) -> None:
        self._search = search
        self._prompts = prompts
        self._llm = llm
        self._settings = settings

    @traced(name="validation")
    def screen(
        self, question: str, filters: SearchFilters, target: int, label: str
    ) -> tuple[list[SearchHit], list[CandidateValidation]]:
        valid: list[SearchHit] = []
        verdicts: list[CandidateValidation] = []
        offset = 0
        for _ in range(self._settings.validation_max_batches):
            size = self._next_batch_size(target - len(valid), len(valid), len(verdicts))
            hits = self._search.candidates(filters, question, size, offset).results
            if not hits:
                break
            offset += len(hits)
            batch = self._validate(question, filters, hits, label)
            verdicts.extend(batch)
            accepted = {v.id for v in batch if v.valid}
            valid.extend(hit for hit in hits if hit.id in accepted)
            if len(valid) >= target or not accepted:
                break
        logger.info(
            "step validation",
            extra={
                "io": "output",
                "checked": len(verdicts),
                "valid_ids": [hit.id for hit in valid],
                "target": target,
            },
        )
        return valid[:target], verdicts

    def _next_batch_size(self, needed: int, valid: int, checked: int) -> int:
        """Ask for enough hits to cover `needed` at the valid rate seen so far, up to one batch.

        First batch: `needed` (at most 15). Later: needed / rate, so a low valid rate fetches a
        full batch instead of shrinking batches that use up the call limit.
        """
        cap = self._settings.validation_batch_size
        if checked == 0 or valid == 0:
            return min(cap, needed)
        return min(cap, math.ceil(needed * checked / valid))

    def _validate(
        self, question: str, filters: SearchFilters, hits: Sequence[SearchHit], label: str
    ) -> list[CandidateValidation]:
        prompt = self._prompts.get(PROMPT_NAME, _variables(question, filters, hits), label)
        answer = self._llm.complete(prompt, ValidationAnswer).output
        check_coverage(answer, [hit.id for hit in hits])
        return answer.candidates


def check_coverage(answer: ValidationAnswer, hit_ids: Sequence[str]) -> None:
    """Every hit judged exactly once, no other ID, every reason non-empty."""
    ids = [c.id for c in answer.candidates]
    repeated = sorted(i for i, count in Counter(ids).items() if count > 1)
    unknown = sorted(set(ids) - set(hit_ids))
    missing = [i for i in hit_ids if i not in set(ids)]
    empty = [c.id for c in answer.candidates if not c.reason.strip()]
    for problem, values in (
        ("repeated", repeated),
        ("unknown", unknown),
        ("missing", missing),
        ("without a reason", empty),
    ):
        if values:
            raise GroundingFailure(f"validation answer has {problem} candidates: {values}")


def _variables(question: str, filters: SearchFilters, hits: Sequence[SearchHit]) -> dict[str, str]:
    applied = filters.model_dump(mode="json", exclude_defaults=True)
    records = [{"id": hit.id, "title": hit.title, "snippet": hit.snippet} for hit in hits]
    return {
        "question": question,
        "filters": json.dumps(applied, ensure_ascii=False) if applied else "none",
        "incidents": json.dumps(records, indent=2, ensure_ascii=False),
    }
