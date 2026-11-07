"""TraceReader: read a trace back from Langfuse by correlation_id, unchanged."""

import httpx
from langfuse import Langfuse
from langfuse.api.core.api_error import ApiError

from app.core.errors import LangfuseUnavailable, TraceNotReady
from app.core.models.trace import TraceView
from app.core.settings import Settings
from app.support.langfuse.client import UNREACHABLE

# metadata carries the step log fields (q, filters, hits, top_ids, selected_ids).
_FIELDS = "core,basic,io,metadata"
_PAGE_LIMIT = 1000  # the API maximum; one request covers any trace this app produces


class LangfuseTraceReader:
    """Rebuilds the trace id from the correlation_id and returns Langfuse's observations."""

    def __init__(self, langfuse: Langfuse, settings: Settings) -> None:
        self._langfuse = langfuse
        self._host = settings.langfuse_host

    def get(self, correlation_id: str) -> TraceView:
        trace_id = Langfuse.create_trace_id(seed=correlation_id)
        try:
            page = self._langfuse.api.observations.get_many(
                trace_id=trace_id, fields=_FIELDS, limit=_PAGE_LIMIT
            )
            if not page.data:
                raise TraceNotReady(
                    "trace not available yet; Langfuse can take a few seconds, retry shortly"
                )
            url = self._langfuse.get_trace_url(trace_id=trace_id)
        except (ApiError, httpx.HTTPError) as exc:
            raise LangfuseUnavailable(UNREACHABLE) from exc
        return TraceView(
            correlation_id=correlation_id,
            trace_id=trace_id,
            # Without a project id the SDK returns None; Langfuse redirects /trace/<id>.
            langfuse_url=url or f"{self._host}/trace/{trace_id}",
            observations=[
                observation.model_dump(mode="json", by_alias=True, exclude_unset=True)
                for observation in page.data
            ],
        )
