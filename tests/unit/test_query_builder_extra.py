"""More query building: missing query vectors, id tiebreaks, tags and paging params."""

from app.core.models.filters import SearchFilters
from app.core.models.search import SearchQuery
from app.support.database.query_builder import build_count, build_search


def search_query(
    text: str | None = "pool exhausted",
    vector: list[float] | None = None,
    tags: tuple[str, ...] = (),
    limit: int = 13,
    offset: int = 0,
) -> SearchQuery:
    return SearchQuery(
        filters=SearchFilters(tags=tags),
        text=text,
        vector=vector,
        limit=limit,
        offset=offset,
        branch_limit=50,
        min_similarity=0.3,
        rrf_k=60,
    )


def test_no_query_vector_means_full_text_only() -> None:
    built = build_search(search_query(vector=None))

    assert "fts AS (" in built.sql
    assert "vec AS (" not in built.sql
    assert "FROM vec" not in built.sql
    assert built.params["vector"] is None


def test_no_query_vector_counts_full_text_matches_only() -> None:
    built = build_count(search_query(vector=None))

    assert "search_vector @@" in built.sql
    assert "embedding" not in built.sql.split("WHERE search_vector")[1]


def test_vector_branch_skips_rows_without_embedding() -> None:
    built = build_search(search_query(vector=[0.1, 0.2, 0.3]))

    assert "i.embedding IS NOT NULL" in built.sql


def test_listing_without_text_ignores_the_vector() -> None:
    built = build_search(search_query(text=None, vector=[0.1, 0.2, 0.3]))

    assert "vec AS (" not in built.sql
    assert "ORDER BY created_at DESC, id" in built.sql


def test_count_without_text_has_no_condition() -> None:
    assert "WHERE search_vector" not in build_count(search_query(text=None)).sql


def test_both_branches_rank_with_an_id_tiebreak() -> None:
    sql = build_search(search_query(vector=[0.1, 0.2, 0.3])).sql

    assert "ORDER BY ts_rank(search_vector, q) DESC, id" in sql
    assert "ORDER BY similarity DESC, id" in sql
    assert "ORDER BY fused.score DESC, fused.id" in sql


def test_tags_are_deduplicated_and_sorted() -> None:
    params = build_search(search_query(tags=("pool", "db", "pool", "auth"))).params

    assert params["tags"] == ["auth", "db", "pool"]
    assert params["tag_count"] == 3


def test_limit_and_offset_are_bound_as_params() -> None:
    built = build_search(search_query(limit=13, offset=37))

    assert "LIMIT %(limit)s OFFSET %(offset)s" in built.sql
    assert (built.params["limit"], built.params["offset"]) == (13, 37)
    assert "37" not in built.sql


def test_listing_binds_limit_and_offset() -> None:
    built = build_search(search_query(text=None, limit=13, offset=37))

    assert "LIMIT %(limit)s OFFSET %(offset)s" in built.sql
    assert (built.params["limit"], built.params["offset"]) == (13, 37)
