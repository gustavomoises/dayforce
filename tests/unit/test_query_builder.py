"""Query building: filters become bound parameters, never SQL text."""

from app.core.models.filters import SearchFilters
from app.core.models.incident import Environment, Severity
from app.core.models.search import SearchQuery
from app.support.database.query_builder import build_count, build_search


def query(filters: SearchFilters, text: str | None = "pool exhausted", vector=None) -> SearchQuery:
    return SearchQuery(
        filters=filters,
        text=text,
        vector=vector,
        limit=10,
        branch_limit=50,
        min_similarity=0.3,
        rrf_k=60,
    )


def test_filters_are_bound_as_parameters() -> None:
    filters = SearchFilters(
        environment=Environment("prod"),
        service="payments-api",
        severity=Severity("high"),
        tags=("db", "pool", "db"),
    )

    built = build_search(query(filters))

    assert "e.code = %(environment)s" in built.sql
    assert "s.code = %(service)s" in built.sql
    assert "v.code = %(severity)s" in built.sql
    assert built.params["environment"] == "prod"
    assert built.params["service"] == "payments-api"
    assert built.params["severity"] == "high"
    assert built.params["tags"] == ["db", "pool"]
    assert built.params["tag_count"] == 2


def test_user_text_never_reaches_the_sql() -> None:
    hostile = "x'); DROP TABLE incidents; --"

    built = build_search(query(SearchFilters(service=hostile), text=hostile))

    assert hostile not in built.sql
    assert built.params["text"] == hostile
    assert built.params["service"] == hostile


def test_no_filters_match_every_row() -> None:
    built = build_search(query(SearchFilters()))

    assert "WHERE TRUE" in built.sql
    assert "%(environment)s" not in built.sql


def test_text_search_uses_both_branches_and_a_stable_order() -> None:
    built = build_search(query(SearchFilters(), vector=[0.1] * 3))

    assert "fts AS (" in built.sql
    assert "vec AS (" in built.sql
    assert "ORDER BY fused.score DESC, fused.id" in built.sql


def test_no_text_lists_newest_first() -> None:
    built = build_search(query(SearchFilters(), text="  "))

    assert "fused" not in built.sql
    assert "ORDER BY created_at DESC, id" in built.sql


def test_count_ignores_the_page_limit() -> None:
    built = build_count(query(SearchFilters(), vector=[0.1] * 3))

    assert "LIMIT" not in built.sql
    assert "search_vector @@" in built.sql
    assert "embedding IS NOT NULL" in built.sql
