"""Search response shared by GET /search and AssistService."""

from pydantic import BaseModel, ConfigDict

from app.core.models.search import SearchHit


class SearchResult(BaseModel):
    """`total` is the real match count; `results` is the requested page."""

    model_config = ConfigDict(frozen=True)

    total: int
    results: list[SearchHit]
