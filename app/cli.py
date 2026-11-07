"""Setup commands, run over SSH on EC2: python -m app.cli schema | catalog | seed | schemas."""

import argparse
import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.container import Container, build_container
from app.core.app_env import DEFAULT_APP_ENV
from app.core.errors import AppError, ConfigurationError
from app.core.settings import Settings
from app.services.assist.models.answer import AssistAnswer
from app.services.assist.models.validation import ValidationAnswer
from app.services.catalog.models.batch import CatalogBatch
from app.services.catalog.models.request import CatalogRequest
from app.support.llm.schemas import schema_name, strict_json_schema
from app.support.tracing.context import correlation_scope
from app.support.tracing.correlation import new_correlation_id
from app.support.tracing.endpoint import root_observation
from app.support.tracing.logging import configure_logging

OUTPUT_MODELS: tuple[type[BaseModel], ...] = (AssistAnswer, ValidationAnswer, CatalogBatch)


def _schema(container: Container, _: argparse.Namespace) -> Any:
    container.schema.create()
    return {"schema": "created"}


def _catalog(container: Container, args: argparse.Namespace) -> Any:
    fields: dict[str, Any] = {}
    if args.services:
        fields["services"] = args.services.split(",")
    if args.events:
        fields["events_per_service"] = args.events
    catalog = container.catalog.generate(CatalogRequest(**fields), label=DEFAULT_APP_ENV)
    return {"services": len(catalog.root), "events": catalog.total_events()}


def _seed(container: Container, _: argparse.Namespace) -> Any:
    return container.seed.seed().model_dump(mode="json", exclude_none=True)


COMMANDS: dict[str, Callable[[Container, argparse.Namespace], Any]] = {
    "schema": _schema,
    "catalog": _catalog,
    "seed": _seed,
}


def _schemas() -> dict[str, Any]:
    """Strict JSON schemas to paste into the Langfuse prompt configs (text.format)."""
    return {
        schema_name(model): {
            "type": "json_schema",
            "name": schema_name(model),
            "strict": True,
            "schema": strict_json_schema(model),
        }
        for model in OUTPUT_MODELS
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("schema", help="create tables and indexes (never drops)")
    catalog = sub.add_parser("catalog", help="generate data/service_catalog.json with the LLM")
    catalog.add_argument("--services", help="comma-separated service names")
    catalog.add_argument("--events", type=int, help="events per service")
    sub.add_parser("seed", help="drop and rebuild the incident tables from the catalog")
    sub.add_parser("schemas", help="print the LLM output JSON schemas")
    return parser


def _run(args: argparse.Namespace) -> Any:
    if args.command == "schemas":
        return _schemas()
    container = build_container(Settings.from_env())
    configure_logging(logging.INFO, container.langfuse)
    correlation_id = new_correlation_id()
    try:
        with (
            correlation_scope(correlation_id),
            root_observation(
                container.langfuse, f"cli {args.command}", DEFAULT_APP_ENV, correlation_id
            ) as root,
        ):
            result = COMMANDS[args.command](container, args)
            root.update(output=result)
        return {"correlation_id": correlation_id, **result}
    finally:
        container.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    configure_logging(logging.INFO)
    try:
        result = _run(args)
    except (AppError, ConfigurationError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
