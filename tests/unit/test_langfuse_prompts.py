"""LangfusePromptProvider: label fetch without cache, compile, config checks, error mapping."""

from typing import Any

import httpx
import pytest
from langfuse.api import NotFoundError, Prompt_Chat, Prompt_Text
from langfuse.api.core.api_error import ApiError
from langfuse.model import ChatPromptClient, PromptClient, TextPromptClient

from app.core.errors import LangfuseUnavailable, PromptConfigInvalid, PromptLabelMissing
from app.core.models.prompt import LLMConfig
from app.support.langfuse.prompts import LangfusePromptProvider

VALID_CONFIG: dict[str, Any] = {
    "model": "gpt-test",
    "reasoning": {"effort": "low"},
    "max_output_tokens": 500,
    "text": {"format": {"type": "json_schema", "name": "assist_answer", "schema": {"a": 1}}},
}


class FakeLangfuse:
    """Returns or raises a fixed result from get_prompt and records the calls."""

    def __init__(self, result: PromptClient | Exception) -> None:
        self.result = result
        self.fetches: list[tuple[str, dict[str, Any]]] = []
        self.span_updates: list[dict[str, Any]] = []

    def get_prompt(self, name: str, **kwargs: Any) -> PromptClient:
        self.fetches.append((name, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def update_current_span(self, **kwargs: Any) -> None:
        self.span_updates.append(kwargs)


@pytest.fixture(autouse=True)
def offline_tracing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without keys, the client behind `@traced` is disabled and sends nothing."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)


def text_prompt(config: Any = VALID_CONFIG) -> TextPromptClient:
    return TextPromptClient(
        Prompt_Text(
            name="incident-assist",
            version=7,
            prompt="Question: {{question}}",
            config=config,
            labels=["qa"],
            tags=[],
        )
    )


def get_error(result: PromptClient | Exception) -> Exception:
    with pytest.raises(Exception) as caught:
        LangfusePromptProvider(FakeLangfuse(result)).get("incident-assist", {}, "qa")
    return caught.value


def test_prompt_is_fetched_by_label_as_text_without_cache() -> None:
    langfuse = FakeLangfuse(text_prompt())

    LangfusePromptProvider(langfuse).get("incident-assist", {"question": "q"}, "stage")

    assert langfuse.fetches == [
        ("incident-assist", {"label": "stage", "type": "text", "cache_ttl_seconds": 0})
    ]


def test_prompt_is_compiled_with_version_and_config() -> None:
    prompt = text_prompt()

    compiled = LangfusePromptProvider(FakeLangfuse(prompt)).get(
        "incident-assist", {"question": "db down"}, "qa"
    )

    assert compiled.text == "Question: db down"
    assert (compiled.name, compiled.version, compiled.label) == ("incident-assist", 7, "qa")
    assert compiled.config == LLMConfig.model_validate(VALID_CONFIG)
    assert compiled.source is prompt


def test_missing_label_names_the_prompt_and_label() -> None:
    error = get_error(NotFoundError(body="not found"))

    assert isinstance(error, PromptLabelMissing)
    assert "`incident-assist` has no label `qa`" in str(error)


@pytest.mark.parametrize(
    "failure",
    [ApiError(status_code=500, body="boom"), ApiError(status_code=401), httpx.ConnectError("down")],
    ids=["server-error", "keys-rejected", "unreachable"],
)
def test_unreachable_langfuse_names_the_host_setting(failure: Exception) -> None:
    error = get_error(failure)

    assert isinstance(error, LangfuseUnavailable)
    assert "LANGFUSE_HOST" in str(error)


def test_chat_prompt_is_rejected() -> None:
    chat = ChatPromptClient(
        Prompt_Chat(
            name="incident-assist",
            version=1,
            prompt=[{"type": "chatmessage", "role": "system", "content": "hi"}],
            config=VALID_CONFIG,
            labels=["qa"],
            tags=[],
        )
    )

    error = get_error(chat)

    assert isinstance(error, PromptConfigInvalid)
    assert "chat prompt" in str(error)


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        ({k: v for k, v in VALID_CONFIG.items() if k != "model"}, "model"),
        ({**VALID_CONFIG, "max_output_tokens": 0}, "max_output_tokens"),
        ({**VALID_CONFIG, "text": {"format": {"type": "text"}}}, "json_schema"),
        ({**VALID_CONFIG, "top_p": 0.5}, "top_p"),
        ({}, "model"),
    ],
    ids=["no-model", "zero-tokens", "not-json-schema", "unknown-key", "empty"],
)
def test_invalid_config_names_prompt_version_and_field(config: dict[str, Any], reason: str) -> None:
    error = get_error(text_prompt(config))

    assert isinstance(error, PromptConfigInvalid)
    assert "`incident-assist` v7 config invalid" in str(error)
    assert reason in str(error)
