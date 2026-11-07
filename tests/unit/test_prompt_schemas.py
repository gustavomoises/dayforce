"""Every prompt config in `prompts/` declares the strict schema of its output model."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from app.core.models.prompt import LLMConfig
from app.services.assist.models.answer import AssistAnswer
from app.services.assist.models.validation import ValidationAnswer
from app.services.catalog.models.batch import CatalogBatch
from app.support.llm.schemas import schema_name, strict_json_schema

PROMPTS = Path(__file__).resolve().parents[2] / "prompts"
CONFIGS: dict[str, type[BaseModel]] = {
    "incident-assist.config.json": AssistAnswer,
    "incident-validation.config.json": ValidationAnswer,
    "incident-catalog.config.json": CatalogBatch,
}


def text_format(file_name: str) -> dict[str, Any]:
    return json.loads((PROMPTS / file_name).read_text(encoding="utf-8"))["text"]["format"]


def test_every_prompt_config_is_covered() -> None:
    assert {path.name for path in PROMPTS.glob("*.config.json")} == set(CONFIGS)


@pytest.mark.parametrize("file_name", CONFIGS)
def test_config_is_a_valid_llm_config(file_name: str) -> None:
    config = json.loads((PROMPTS / file_name).read_text(encoding="utf-8"))

    assert LLMConfig.model_validate(config).schema_name == schema_name(CONFIGS[file_name])


@pytest.mark.parametrize("file_name", CONFIGS)
def test_config_format_is_strict_json_schema(file_name: str) -> None:
    fmt = text_format(file_name)

    assert (fmt["type"], fmt["strict"]) == ("json_schema", True)


@pytest.mark.parametrize("file_name", CONFIGS)
def test_config_schema_matches_the_output_model(file_name: str) -> None:
    assert text_format(file_name)["schema"] == strict_json_schema(CONFIGS[file_name])
