---
inclusion: always
---

# Code standards (all agents)

Time is short and reviewers judge maintainable design. Write pristine code: simple, effective, idiomatic. Be smart and concise.

## Source of truth

- Build only what `.kiro/specs/incident-triage-api/` (requirements, design, tasks) and `architecture.md`, `database-architecture.md`, `trace-architecture.md` specify. No extra features, no speculative abstractions.
- Respect the layers: entry → services → support; all may use `app/core`. Imports only point down. Services use support only through `app/core/ports.py` Protocols.
- A model lives in the lowest layer that uses it.
- Ignore the old `src/dayforce_task` stub; the app lives in `main.py` and `app/`.
- If the spec is ambiguous or wrong, stop and report it. Do not guess silently.

## Parallel work

- `app/core` (models, ports, settings, errors) is frozen after task 1. Do not change it; report the change you need.
- Each stream edits only its own folders: database → `app/support/database/`, `app/services/{schema,seed,ingest}/`; Langfuse → `app/support/langfuse/`, `app/support/tracing/`; OpenAI → `app/support/llm/`, LLM output models. Shared files (`container.py`, `api/`, `cli.py`) are written in task 5.
- Nothing is created at import time: no clients, pools or connections at module level. Everything is built in `app/container.py`.

## Style

- Python 3.12, PEP 8, line length 100, type hints on every function signature, modern syntax (`str | None`, `list[str]`).
- **Sync everywhere:** `def` routes, sync psycopg pool, sync OpenAI and Langfuse clients. No `async def` unless a library forces it.
- Pydantic v2 for all request, response, config and LLM output models. Frozen models for values that should not change.
- Small functions with one job. Prefer pure functions for logic (normalize, fingerprint, query building, guardrails).
- Clear names over comments. Comment only the why. One short docstring per public class or function.
- No dead code, no commented-out code, no `print`, no TODOs left behind, no unused imports.
- Constants and defaults in `app/core/settings.py`, not scattered literals.
- Datetimes are timezone-aware UTC.
- Prefer the standard library and the chosen dependencies (fastapi, pydantic, psycopg, pgvector, boto3, openai, langfuse v5). Do not add libraries without asking.

## Patterns

- Dependency injection: clients and services are built in `app/container.py`; routes get services with `Depends`. Nothing builds its own client.
- Repository pattern for SQL; every query parameterized; no SQL outside `app/support/database/`. DDL lives in `.sql` files.
- Errors: support code converts library exceptions into domain errors from `app/core/errors.py`. Only the exception handler and `cli.py` catch broad exceptions. Never return stack traces.
- Logging: `logger = logging.getLogger(__name__)`; fixed messages, data in `extra={...}` (for example `logger.info("step tool:search output", extra={"hits": 12, "top_ids": [...]})`).
- Langfuse owns tracing: use Langfuse `@observe` (re-exported as `traced`); do not build trace stores or span trees.
- Timeouts on every external call. No silent fallbacks.
- Never log or return secret values.

## Done means

- `ruff format` and `ruff check` pass (config in `pyproject.toml`; ruff is dev-only, in `requirements-dev.txt`).
- Code runs, imports cleanly and matches the spec section it implements.
- Each file is short and readable on its own. If a file grows past ~200 lines, split it by responsibility.
- Report what was built, what was not, and any spec issue found, in a few lines.
