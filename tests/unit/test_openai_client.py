"""OpenAIClient: prompt config passed to the Responses API, output parsing, error mapping."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, ClassVar

import httpx
import openai
import pytest
from openai.types.responses import Response
from pydantic import BaseModel, ConfigDict, SecretStr

from app.core.errors import LLMOutputInvalid, LLMTimeout, LLMUnavailable, PromptConfigInvalid
from app.core.models.prompt import CompiledPrompt, LLMConfig
from app.core.secrets import DatabaseCredentials, Secrets
from app.core.settings import Settings
from app.support.llm import openai_client
from app.support.llm.errors import OPENAI_SECRET
from app.support.llm.openai_client import OpenAIClient, create_openai

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")
PROMPT_SOURCE = object()


class Verdict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_name: ClassVar[str] = "verdict"

    summary: str
    score: int


class FakeResponses:
    def __init__(self, result: Response | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Response:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeOpenAI:
    def __init__(self, result: Response | Exception) -> None:
        self.responses = FakeResponses(result)


class FakeGeneration:
    def __init__(self) -> None:
        self.updates: list[dict[str, Any]] = []

    def update(self, **kwargs: Any) -> None:
        self.updates.append(kwargs)


class FakeLangfuse:
    def __init__(self) -> None:
        self.generation = FakeGeneration()
        self.started: list[dict[str, Any]] = []

    @contextmanager
    def start_as_current_observation(self, **kwargs: Any) -> Iterator[FakeGeneration]:
        self.started.append(kwargs)
        yield self.generation


@pytest.fixture(autouse=True)
def langfuse(monkeypatch: pytest.MonkeyPatch) -> FakeLangfuse:
    fake = FakeLangfuse()
    monkeypatch.setattr(openai_client, "get_client", lambda: fake)
    return fake


def response(
    text: str = '{"summary": "db pool", "score": 3}',
    status: str = "completed",
    content: dict[str, Any] | None = None,
    usage: bool = True,
) -> Response:
    message_content = content or {"type": "output_text", "text": text, "annotations": []}
    return Response.model_validate(
        {
            "id": "resp-1",
            "created_at": 0,
            "model": "gpt-test-2026",
            "object": "response",
            "status": status,
            "incomplete_details": {"reason": "max_output_tokens"}
            if status != "completed"
            else None,
            "output": [
                {
                    "type": "message",
                    "id": "msg-1",
                    "role": "assistant",
                    "status": "completed",
                    "content": [message_content],
                }
            ],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
            "usage": {
                "input_tokens": 120,
                "output_tokens": 30,
                "total_tokens": 150,
                "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            }
            if usage
            else None,
        }
    )


def prompt(**config: Any) -> CompiledPrompt:
    llm_config = {
        "model": "gpt-test",
        "max_output_tokens": 800,
        "text": {"format": {"type": "json_schema", "name": "verdict", "schema": {"x": 1}}},
        **config,
    }
    return CompiledPrompt(
        name="incident-assist",
        version=4,
        label="qa",
        text="compiled prompt text",
        config=LLMConfig.model_validate(llm_config),
        source=PROMPT_SOURCE,
    )


def complete(result: Response | Exception, compiled: CompiledPrompt | None = None) -> Any:
    client = OpenAIClient(FakeOpenAI(result), Settings())
    return client.complete(compiled or prompt(), Verdict)


def sent(result: Response, compiled: CompiledPrompt) -> dict[str, Any]:
    fake = FakeOpenAI(result)
    OpenAIClient(fake, Settings()).complete(compiled, Verdict)
    [call] = fake.responses.calls
    return call


def test_config_is_passed_to_the_responses_api() -> None:
    compiled = prompt(reasoning={"effort": "medium"}, temperature=0.2)

    call = sent(response(), compiled)

    assert call == {
        "model": "gpt-test",
        "input": "compiled prompt text",
        "text": compiled.config.text,
        "max_output_tokens": 800,
        "reasoning": {"effort": "medium"},
        "temperature": 0.2,
        "timeout": 30.0,
    }


def test_unset_reasoning_and_temperature_are_omitted() -> None:
    call = sent(response(), prompt())

    assert call["reasoning"] is openai.omit
    assert call["temperature"] is openai.omit


def test_output_is_parsed_into_the_output_model_with_usage() -> None:
    result = complete(response())

    assert result.output == Verdict(summary="db pool", score=3)
    assert (result.model, result.input_tokens, result.output_tokens) == ("gpt-test-2026", 120, 30)


def test_missing_usage_counts_as_zero_tokens() -> None:
    result = complete(response(usage=False))

    assert (result.input_tokens, result.output_tokens) == (0, 0)


def test_call_is_recorded_as_a_generation_linked_to_the_prompt(langfuse: FakeLangfuse) -> None:
    complete(response())

    [started] = langfuse.started
    assert started["as_type"] == "generation"
    assert started["prompt"] is PROMPT_SOURCE
    assert started["metadata"] == {"prompt": "incident-assist", "version": "4", "label": "qa"}
    [update] = langfuse.generation.updates
    assert update["usage_details"] == {"input": 120, "output": 30}


@pytest.mark.parametrize(
    ("result", "problem"),
    [
        (response(text="not json"), "Invalid JSON"),
        (response(text='{"summary": "x"}'), "score: Field required"),
        (response(text='{"summary": "x", "score": "high"}'), "score: Input should be"),
        (response(text='{"summary": "x", "score": 1, "extra": 2}'), "extra: Extra inputs"),
        (response(status="incomplete"), "response incomplete (max_output_tokens)"),
        (response(content={"type": "refusal", "refusal": "cannot help"}), "refused: cannot help"),
    ],
    ids=["invalid-json", "missing-field", "wrong-type", "extra-field", "incomplete", "refusal"],
)
def test_unusable_output_is_llm_output_invalid(result: Response, problem: str) -> None:
    with pytest.raises(LLMOutputInvalid) as caught:
        complete(result)

    assert "does not match `Verdict`" in caught.value.detail
    assert problem in caught.value.detail


def test_schema_name_mismatch_fails_before_calling_openai() -> None:
    fake = FakeOpenAI(response())
    other = prompt(text={"format": {"type": "json_schema", "name": "assist", "schema": {"x": 1}}})

    with pytest.raises(PromptConfigInvalid, match="schema `assist` does not match `Verdict`"):
        OpenAIClient(fake, Settings()).complete(other, Verdict)

    assert fake.responses.calls == []


def test_rejected_request_is_a_prompt_config_error() -> None:
    rejected = openai.BadRequestError(
        "Unsupported parameter: 'reasoning'",
        response=httpx.Response(400, request=REQUEST),
        body=None,
    )

    with pytest.raises(PromptConfigInvalid) as caught:
        complete(rejected)

    assert "`incident-assist` v4 rejected by OpenAI" in caught.value.detail
    assert "Unsupported parameter" in caught.value.detail


def test_timeout_is_llm_timeout() -> None:
    with pytest.raises(LLMTimeout, match="LLM_TIMEOUT_SECONDS"):
        complete(openai.APITimeoutError(request=REQUEST))


def test_rejected_key_is_llm_unavailable() -> None:
    rejected = openai.AuthenticationError(
        "bad key", response=httpx.Response(401, request=REQUEST), body=None
    )

    with pytest.raises(LLMUnavailable, match=OPENAI_SECRET):
        complete(rejected)


def secrets(openai_key: str) -> Secrets:
    return Secrets(
        database=DatabaseCredentials(
            host="h", port=5432, dbname="d", username="u", password=SecretStr("p")
        ),
        openai_api_key=SecretStr(openai_key),
        langfuse_public_key=SecretStr("pk"),
        langfuse_secret_key=SecretStr("sk"),
    )


def test_empty_api_key_is_unavailable_and_names_the_secret() -> None:
    with pytest.raises(LLMUnavailable, match=OPENAI_SECRET):
        create_openai(secrets(""), Settings())


def test_client_uses_the_llm_timeout_and_one_retry() -> None:
    client = create_openai(secrets("sk-test"), Settings(llm_timeout_seconds=12))

    assert (client.timeout, client.max_retries) == (12, 1)
