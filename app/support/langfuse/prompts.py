"""PromptProvider backed by Langfuse text prompts; the prompt config holds the LLM settings."""

import httpx
from langfuse import Langfuse
from langfuse.api import NotFoundError
from langfuse.api.core.api_error import ApiError
from langfuse.model import PromptClient, TextPromptClient
from pydantic import ValidationError

from app.core.errors import LangfuseUnavailable, PromptConfigInvalid, PromptLabelMissing
from app.core.models.prompt import CompiledPrompt, LLMConfig
from app.support.langfuse.client import UNREACHABLE
from app.support.tracing.span import traced


class LangfusePromptProvider:
    """Fetches a text prompt by label (no cache), compiles it and validates its config."""

    def __init__(self, langfuse: Langfuse) -> None:
        self._langfuse = langfuse

    @traced(name="Langfuse.get_prompt", capture_input=False, capture_output=False)
    def get(self, name: str, variables: dict[str, str], label: str) -> CompiledPrompt:
        self._langfuse.update_current_span(input={"name": name, "label": label})
        prompt = self._fetch(name, label)
        if not isinstance(prompt, TextPromptClient):
            raise PromptConfigInvalid(f"prompt `{name}` is a chat prompt; recreate it as text")
        compiled = CompiledPrompt(
            name=prompt.name,
            version=prompt.version,
            label=label,
            text=prompt.compile(**variables),
            config=_parse_config(prompt),
            source=prompt,
        )
        self._langfuse.update_current_span(output={"version": compiled.version})
        return compiled

    def _fetch(self, name: str, label: str) -> PromptClient:
        try:
            return self._langfuse.get_prompt(name, label=label, type="text", cache_ttl_seconds=0)
        except NotFoundError as exc:
            raise PromptLabelMissing(
                f"prompt `{name}` has no label `{label}`; add it in Langfuse"
            ) from exc
        except (ApiError, httpx.HTTPError) as exc:
            raise LangfuseUnavailable(UNREACHABLE) from exc


def _parse_config(prompt: TextPromptClient) -> LLMConfig:
    try:
        return LLMConfig.model_validate(prompt.config)
    except ValidationError as exc:
        raise PromptConfigInvalid(
            f"prompt `{prompt.name}` v{prompt.version} config invalid: {_reason(exc)}"
        ) from exc


def _reason(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(map(str, error['loc'])) or 'config'}: {error['msg']}" for error in exc.errors()
    )
