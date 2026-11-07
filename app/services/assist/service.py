"""Grounded assist: search candidates, one LLM call, guardrails, top results never padded."""

import json
import logging
from collections.abc import Sequence

from app.core.models.filters import SearchFilters
from app.core.models.incident import Incident
from app.core.ports import LLMClient, PromptProvider
from app.core.settings import Settings
from app.services.assist import guardrails
from app.services.assist.models.answer import AssistAnswer, CandidateAssessment
from app.services.assist.models.request import AssistRequest
from app.services.assist.models.response import AssistResponse, RelevantIncident
from app.services.incidents.service import IncidentService
from app.services.search.service import SearchService
from app.support.tracing.span import traced

logger = logging.getLogger(__name__)

PROMPT_NAME = "incident-assist"
# Asked when search finds nothing, so no LLM call is made.
NO_MATCH_QUESTIONS = (
    "What is the exact error message?",
    "When did the problem start?",
    "Which service and environment are affected?",
)
# Fewer relevant incidents than this get an explicit note instead of padding.
FEW_RESULTS = 3


class AssistService:
    """Answers a question using only incidents retrieved through SearchService."""

    def __init__(
        self,
        search: SearchService,
        incidents: IncidentService,
        prompts: PromptProvider,
        llm: LLMClient,
        settings: Settings,
    ) -> None:
        self._search = search
        self._incidents = incidents
        self._prompts = prompts
        self._llm = llm
        self._settings = settings

    @traced(name="AssistService.assist")
    def assist(self, request: AssistRequest, label: str) -> AssistResponse:
        filters = request.filters()
        k = request.candidate_multiplier * self._settings.assist_max_results
        hits = self._search.candidates(filters, request.question, k).results
        if not hits:
            logger.info("step selected_ids", extra={"selected_ids": [], "relevant_count": 0})
            return _no_match()
        incidents = self._incidents.get_many([hit.id for hit in hits])
        prompt = self._prompts.get(
            PROMPT_NAME, _prompt_variables(request.question, filters, incidents), label
        )
        answer = self._llm.complete(prompt, AssistAnswer).output
        selected = self._select(answer, [incident.id for incident in incidents])
        titles = {incident.id: incident.title for incident in incidents}
        relevant = [_relevant_incident(c, titles[c.id]) for c in selected]
        return AssistResponse(
            status="answered" if relevant else "no_relevant_incidents",
            relevant_incidents=relevant,
            note=_note(len(relevant)),
            candidates=answer.candidates,
            next_steps=answer.next_steps,
            customer_draft=answer.customer_draft,
            missing_info=answer.missing_info,
            prompt_version=prompt.version,
        )

    @traced(name="guardrails")
    def _select(
        self, answer: AssistAnswer, candidate_ids: Sequence[str]
    ) -> list[CandidateAssessment]:
        selected = guardrails.validate(answer, candidate_ids, self._settings.assist_max_results)
        logger.info(
            "step selected_ids",
            extra={
                "selected_ids": [c.id for c in selected],
                "relevant_count": sum(c.relevant for c in answer.candidates),
            },
        )
        return selected


def _no_match() -> AssistResponse:
    return AssistResponse(
        status="no_relevant_incidents",
        relevant_incidents=[],
        candidates=[],
        next_steps=[],
        customer_draft="",
        missing_info=list(NO_MATCH_QUESTIONS),
    )


def _note(relevant_count: int) -> str | None:
    if 0 < relevant_count < FEW_RESULTS:
        return f"only {relevant_count} relevant incidents found"
    return None


def _prompt_variables(
    question: str, filters: SearchFilters, incidents: Sequence[Incident]
) -> dict[str, str]:
    applied = filters.model_dump(mode="json", exclude_defaults=True)
    return {
        "question": question,
        "filters": json.dumps(applied, ensure_ascii=False) if applied else "none",
        "incidents": json.dumps(
            [_incident_record(incident) for incident in incidents], indent=2, ensure_ascii=False
        ),
    }


def _incident_record(incident: Incident) -> dict[str, object]:
    return {
        "id": incident.id,
        "service": incident.service,
        "environment": incident.environment.value,
        "severity": incident.severity.value,
        "created_at": incident.created_at.isoformat(),
        "title": incident.title,
        "description": incident.description,
        "resolution_summary": incident.resolution_summary,
        "tags": list(incident.tags),
    }


def _relevant_incident(candidate: CandidateAssessment, title: str) -> RelevantIncident:
    return RelevantIncident(
        rank=candidate.rank,
        id=candidate.id,
        title=title,
        reason=candidate.reason,
        rank_justification=candidate.rank_justification,
    )
