"""Grounded assist: validated candidates, one relevance call, guardrails, never padded."""

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
from app.services.assist.models.response import (
    AssistResponse,
    RelatedIncident,
    RelevantIncident,
)
from app.services.assist.models.validation import CandidateValidation
from app.services.assist.screening import CandidateScreener
from app.services.incidents.service import IncidentService
from app.support.tracing.span import traced

logger = logging.getLogger(__name__)

PROMPT_NAME = "incident-assist"
# Asked when search finds nothing, so no LLM call is made.
NO_MATCH_QUESTIONS = (
    "What is the exact error message?",
    "When did the problem start?",
    "Which service and environment are affected?",
)
# Fewer groups (distinct problems) than this get an explicit note instead of padding.
FEW_RESULTS = 3


class AssistService:
    """Answers a question using only incidents retrieved through SearchService."""

    def __init__(
        self,
        screener: CandidateScreener,
        incidents: IncidentService,
        prompts: PromptProvider,
        llm: LLMClient,
        settings: Settings,
    ) -> None:
        self._screener = screener
        self._incidents = incidents
        self._prompts = prompts
        self._llm = llm
        self._settings = settings

    @traced(name="AssistService.assist")
    def assist(self, request: AssistRequest, label: str) -> AssistResponse:
        filters = request.filters()
        k = request.candidate_multiplier * self._settings.assist_max_results
        hits, validation = self._screener.screen(request.question, filters, k, label)
        if not hits:
            logger.info(
                "step selected_ids",
                extra={"io": "output", "selected_ids": [], "relevant_count": 0},
            )
            return _no_match(validation)
        incidents = self._incidents.get_many([hit.id for hit in hits])
        prompt = self._prompts.get(
            PROMPT_NAME, _prompt_variables(request.question, filters, incidents), label
        )
        answer = self._llm.complete(prompt, AssistAnswer).output
        groups = self._select(answer, [incident.id for incident in incidents])
        by_id = {incident.id: incident for incident in incidents}
        relevant = [_relevant_incident(group, by_id) for group in groups]
        return AssistResponse(
            status="answered" if relevant else "no_relevant_incidents",
            relevant_incidents=relevant,
            note=_note(len(relevant)),
            candidates=answer.candidates,
            next_steps=answer.next_steps,
            customer_draft=answer.customer_draft,
            missing_info=answer.missing_info,
            validation=validation,
            prompt_version=prompt.version,
        )

    @traced(name="guardrails")
    def _select(
        self, answer: AssistAnswer, candidate_ids: Sequence[str]
    ) -> list[list[CandidateAssessment]]:
        groups = guardrails.validate(answer, candidate_ids, self._settings.assist_max_results)
        logger.info(
            "step selected_ids",
            extra={
                "io": "output",
                "selected_ids": [group[0].id for group in groups],
                "groups": {group[0].group: [c.id for c in group] for group in groups},
                "relevant_count": sum(c.relevant for c in answer.candidates),
            },
        )
        return groups


def _no_match(validation: list[CandidateValidation]) -> AssistResponse:
    """No valid candidate: no assist call; the validation verdicts explain why."""
    return AssistResponse(
        status="no_relevant_incidents",
        relevant_incidents=[],
        candidates=[],
        next_steps=[],
        customer_draft="",
        missing_info=list(NO_MATCH_QUESTIONS),
        validation=validation,
    )


def _note(group_count: int) -> str | None:
    if group_count == 1:
        return "only 1 distinct problem found"
    if 1 < group_count < FEW_RESULTS:
        return f"only {group_count} distinct problems found"
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


def _relevant_incident(
    group: Sequence[CandidateAssessment], by_id: dict[str, Incident]
) -> RelevantIncident:
    """The group's best-ranked incident, with the rest of the group as `related`."""
    lead, *rest = group
    return RelevantIncident(
        group=lead.group,
        rank=lead.rank,
        id=lead.id,
        title=by_id[lead.id].title,
        reason=lead.reason,
        rank_justification=lead.rank_justification,
        group_reason=lead.group_reason,
        environment=by_id[lead.id].environment,
        severity=by_id[lead.id].severity,
        created_at=by_id[lead.id].created_at,
        related=[_related_incident(c, by_id[c.id]) for c in rest],
    )


def _related_incident(candidate: CandidateAssessment, incident: Incident) -> RelatedIncident:
    return RelatedIncident(
        rank=candidate.rank,
        id=incident.id,
        title=incident.title,
        reason=candidate.reason,
        group_reason=candidate.group_reason,
        environment=incident.environment,
        severity=incident.severity,
        created_at=incident.created_at,
    )
