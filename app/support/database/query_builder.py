"""Pure builders for the hybrid search SQL. Every value is bound as a named parameter."""

from dataclasses import dataclass
from typing import Any

from pgvector import Vector

from app.core.models.filters import SearchFilters
from app.core.models.search import SearchQuery

# Snippet length for rows without a full-text hit (and for filter-only listings).
SNIPPET_CHARS = 200

_TSQUERY = "websearch_to_tsquery('english', %(text)s)"
_SIMILARITY = "round((1 - (embedding <=> %(vector)s))::numeric, 6)"
_INCIDENTS_WITH_TYPES = """FROM incidents i
    JOIN environment_types e ON e.id = i.environment_id
    JOIN service_types s ON s.id = i.service_id
    JOIN severity_types v ON v.id = i.severity_id"""
_TAGS_CONDITION = """i.id IN (
        SELECT it.incident_id FROM incident_tags it JOIN tags t ON t.id = it.tag_id
        WHERE t.name = ANY(%(tags)s)
        GROUP BY it.incident_id
        HAVING count(*) = %(tag_count)s
    )"""


@dataclass(frozen=True)
class BuiltQuery:
    sql: str
    params: dict[str, Any]


def build_search(query: SearchQuery) -> BuiltQuery:
    """The page of hits: fused hybrid ranking, or newest first when there is no text."""
    if not has_text(query):
        sql = f"WITH {_filtered_cte(query.filters)}\n{_listing_select()}"
        return BuiltQuery(sql, _params(query))
    branches = _branch_ctes(query)
    ctes = ",\n".join([_filtered_cte(query.filters), *branches.values(), _fused_cte(branches)])
    return BuiltQuery(f"WITH {ctes}\n{_fused_select()}", _params(query))


def build_count(query: SearchQuery) -> BuiltQuery:
    """Real total: distinct rows matching either branch, without the branch cap."""
    conditions = []
    if has_text(query):
        conditions.append(f"search_vector @@ {_TSQUERY}")
        if query.vector is not None:
            conditions.append(
                f"(embedding IS NOT NULL AND {_SIMILARITY} >= %(min_similarity)s::numeric)"
            )
    where = f"\nWHERE {' OR '.join(conditions)}" if conditions else ""
    sql = f"WITH {_filtered_cte(query.filters)}\nSELECT count(*) FROM filtered{where}"
    return BuiltQuery(sql, _params(query))


def has_text(query: SearchQuery) -> bool:
    return bool(query.text and query.text.strip())


def _params(query: SearchQuery) -> dict[str, Any]:
    filters = query.filters
    tags = sorted(set(filters.tags))
    return {
        "environment": filters.environment.value if filters.environment else None,
        "service": filters.service,
        "severity": filters.severity.value if filters.severity else None,
        "tags": tags,
        "tag_count": len(tags),
        "text": query.text,
        "vector": Vector(query.vector) if query.vector is not None else None,
        "min_similarity": query.min_similarity,
        "branch_limit": query.branch_limit,
        "rrf_k": query.rrf_k,
        "limit": query.limit,
        "snippet_chars": SNIPPET_CHARS,
    }


def _filter_conditions(filters: SearchFilters) -> list[str]:
    conditions = []
    if filters.environment is not None:
        conditions.append("e.code = %(environment)s")
    if filters.service is not None:
        conditions.append("s.code = %(service)s")
    if filters.severity is not None:
        conditions.append("v.code = %(severity)s")
    if filters.tags:
        conditions.append(_TAGS_CONDITION)
    return conditions


def _where(conditions: list[str]) -> str:
    return "\n    AND ".join(conditions) or "TRUE"


def _filtered_cte(filters: SearchFilters) -> str:
    return f"""filtered AS (
    SELECT i.id, i.title, i.description, i.created_at, i.search_vector, i.embedding
    {_INCIDENTS_WITH_TYPES}
    WHERE {_where(_filter_conditions(filters))}
)"""


def _branch_ctes(query: SearchQuery) -> dict[str, str]:
    branches = {"fts": _fts_cte()}
    if query.vector is not None:
        branches["vec"] = _vector_cte(query.filters)
    return branches


def _fts_cte() -> str:
    return f"""fts AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank(search_vector, q) DESC, id) AS rank
    FROM filtered, {_TSQUERY} AS q
    WHERE search_vector @@ q
    ORDER BY rank
    LIMIT %(branch_limit)s
)"""


def _vector_cte(filters: SearchFilters) -> str:
    """Nearest rows by cosine distance straight from `incidents`, so the IVFFlat index applies.

    `ORDER BY embedding <=> vector LIMIT n` is the shape pgvector can serve from the index;
    the id tiebreak and the similarity threshold are applied to those n rows.
    """
    conditions = ["i.embedding IS NOT NULL", *_filter_conditions(filters)]
    return f"""vec AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY similarity DESC, id) AS rank
    FROM (
        SELECT i.id, round((1 - (i.embedding <=> %(vector)s))::numeric, 6) AS similarity
        {_INCIDENTS_WITH_TYPES}
        WHERE {_where(conditions)}
        ORDER BY i.embedding <=> %(vector)s
        LIMIT %(branch_limit)s
    ) AS nearest
    WHERE similarity >= %(min_similarity)s::numeric
)"""


def _fused_cte(branches: dict[str, str]) -> str:
    ranked = " UNION ALL ".join(f"SELECT id, rank FROM {name}" for name in branches)
    return f"""fused AS (
    SELECT id, sum(1.0 / (%(rrf_k)s + rank)) AS score
    FROM ({ranked}) AS ranked
    GROUP BY id
)"""


def _fused_select() -> str:
    return f"""SELECT f.id, f.title,
    CASE WHEN fts.id IS NULL THEN left(f.description, %(snippet_chars)s)
         ELSE ts_headline('english', f.description, {_TSQUERY}, 'MaxFragments=1, MaxWords=30')
    END AS snippet,
    fused.score::float8 AS score
FROM fused
JOIN filtered f ON f.id = fused.id
LEFT JOIN fts ON fts.id = fused.id
ORDER BY fused.score DESC, fused.id
LIMIT %(limit)s"""


def _listing_select() -> str:
    return """SELECT id, title, left(description, %(snippet_chars)s) AS snippet,
    0.0::float8 AS score
FROM filtered
ORDER BY created_at DESC, id
LIMIT %(limit)s"""
