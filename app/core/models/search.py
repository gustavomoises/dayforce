"""Search request and result shared by SearchService and the repository."""

from pydantic import BaseModel, ConfigDict

from app.core.models.filters import SearchFilters


class SearchQuery(BaseModel):
    """Everything the repository needs to run one hybrid search."""

    model_config = ConfigDict(frozen=True)

    filters: SearchFilters
    text: str | None
    vector: list[float] | None
    limit: int
    offset: int = 0
    branch_limit: int
    min_similarity: float
    rrf_k: int


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    snippet: str
    score: float


class SearchPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    hits: list[SearchHit]
