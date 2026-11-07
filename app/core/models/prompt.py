"""Contracts between Langfuse (prompts), OpenAI (LLM, embeddings) and services."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMConfig(BaseModel):
    """OpenAI settings stored in the Langfuse prompt `config`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str
    max_output_tokens: int = Field(gt=0)
    text: dict[str, Any]
    reasoning: dict[str, Any] | None = None
    temperature: float | None = None

    @field_validator("text")
    @classmethod
    def _require_json_schema(cls, text: dict[str, Any]) -> dict[str, Any]:
        fmt = text.get("format", {})
        if fmt.get("type") != "json_schema" or not fmt.get("name") or not fmt.get("schema"):
            raise ValueError("text.format must be a json_schema with name and schema")
        return text

    @property
    def schema_name(self) -> str:
        return self.text["format"]["name"]


class CompiledPrompt(BaseModel):
    """A Langfuse text prompt with variables filled in."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    version: int
    label: str
    text: str
    config: LLMConfig
    # The Langfuse prompt object, kept so the generation links to the prompt version.
    source: Any = Field(default=None, exclude=True, repr=False)


class LLMResult[OutputT: BaseModel](BaseModel):
    """Parsed LLM output plus usage."""

    model_config = ConfigDict(frozen=True)

    output: OutputT
    model: str
    input_tokens: int
    output_tokens: int


class EmbeddingResult(BaseModel):
    """One vector per input text, in input order."""

    model_config = ConfigDict(frozen=True)

    vectors: list[list[float]]
    model: str
    total_tokens: int
