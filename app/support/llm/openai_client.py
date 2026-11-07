"""LLMClient on the OpenAI Responses API, recorded as a Langfuse generation."""

import logging

import openai
from langfuse import get_client
from openai.types.responses import Response
from pydantic import BaseModel, ValidationError

from app.core.errors import LLMOutputInvalid, LLMUnavailable, PromptConfigInvalid
from app.core.models.prompt import CompiledPrompt, LLMResult
from app.core.secrets import Secrets
from app.core.settings import Settings
from app.support.llm.errors import OPENAI_SECRET, is_request_rejected, to_domain_error
from app.support.llm.schemas import schema_name

logger = logging.getLogger(__name__)

MAX_RETRIES = 1
MAX_REPORTED_ERRORS = 5


def create_openai(secrets: Secrets, settings: Settings) -> openai.OpenAI:
    """Build the shared sync OpenAI client used by the LLM and embedding clients."""
    api_key = secrets.openai_api_key.get_secret_value()
    if not api_key:
        raise LLMUnavailable(f"OpenAI API key is empty; check secret `{OPENAI_SECRET}`")
    return openai.OpenAI(
        api_key=api_key, timeout=settings.llm_timeout_seconds, max_retries=MAX_RETRIES
    )


class OpenAIClient:
    """Run a compiled Langfuse prompt and parse the answer into its output model."""

    def __init__(self, client: openai.OpenAI, settings: Settings) -> None:
        self._client = client
        self._timeout = settings.llm_timeout_seconds

    def complete[OutputT: BaseModel](
        self, prompt: CompiledPrompt, output_model: type[OutputT]
    ) -> LLMResult[OutputT]:
        _check_schema_name(prompt, output_model)
        with get_client().start_as_current_observation(
            name="openai.responses",
            as_type="generation",
            model=prompt.config.model,
            input=prompt.text,
            metadata={"prompt": prompt.name, "version": str(prompt.version), "label": prompt.label},
            prompt=prompt.source,
        ) as generation:
            response = self._create(prompt)
            input_tokens, output_tokens = _usage(response)
            generation.update(
                model=response.model,
                output=response.output_text,
                usage_details={"input": input_tokens, "output": output_tokens},
            )
            output = _parse(response, output_model)
        return LLMResult[output_model](
            output=output,
            model=response.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _create(self, prompt: CompiledPrompt) -> Response:
        config = prompt.config
        try:
            return self._client.responses.create(
                model=config.model,
                input=prompt.text,
                text=config.text,
                max_output_tokens=config.max_output_tokens,
                reasoning=config.reasoning if config.reasoning is not None else openai.omit,
                temperature=config.temperature if config.temperature is not None else openai.omit,
                timeout=self._timeout,
            )
        except openai.OpenAIError as exc:
            if is_request_rejected(exc):
                raise PromptConfigInvalid(
                    f"prompt `{prompt.name}` v{prompt.version} rejected by OpenAI: {exc.message}"
                ) from exc
            raise to_domain_error(exc, LLMUnavailable, self._timeout) from exc


def _check_schema_name(prompt: CompiledPrompt, output_model: type[BaseModel]) -> None:
    if prompt.config.schema_name != schema_name(output_model):
        raise PromptConfigInvalid(
            f"prompt `{prompt.name}` v{prompt.version} schema `{prompt.config.schema_name}` "
            f"does not match `{output_model.__name__}`"
        )


def _usage(response: Response) -> tuple[int, int]:
    if response.usage is None:
        return 0, 0
    return response.usage.input_tokens, response.usage.output_tokens


def _parse[OutputT: BaseModel](response: Response, output_model: type[OutputT]) -> OutputT:
    problem = _unusable_reason(response)
    if problem is None:
        try:
            return output_model.model_validate_json(response.output_text)
        except ValidationError as exc:
            problem = _field_errors(exc)
    logger.warning("llm output invalid", extra={"model": output_model.__name__, "problem": problem})
    raise LLMOutputInvalid(f"LLM output does not match `{output_model.__name__}`: {problem}")


def _unusable_reason(response: Response) -> str | None:
    if response.status != "completed":
        details = response.incomplete_details
        reason = details.reason if details and details.reason else "no reason given"
        return f"response {response.status} ({reason})"
    refusals = [
        content.refusal
        for item in response.output
        if item.type == "message"
        for content in item.content
        if content.type == "refusal"
    ]
    return f"model refused: {refusals[0]}" if refusals else None


def _field_errors(exc: ValidationError) -> str:
    errors = exc.errors(include_url=False, include_input=False)[:MAX_REPORTED_ERRORS]
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or '<root>'}: {e['msg']}" for e in errors)
