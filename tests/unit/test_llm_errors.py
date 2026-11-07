"""OpenAI SDK exceptions mapped to domain errors with messages that say what to check."""

import httpx
import openai
import pytest

from app.core.errors import EmbeddingUnavailable, LLMTimeout, LLMUnavailable, Unavailable
from app.support.llm.errors import OPENAI_SECRET, is_request_rejected, to_domain_error

REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")
STATUS_ERRORS: dict[int, type[openai.APIStatusError]] = {
    400: openai.BadRequestError,
    401: openai.AuthenticationError,
    403: openai.PermissionDeniedError,
    404: openai.NotFoundError,
    409: openai.ConflictError,
    422: openai.UnprocessableEntityError,
    429: openai.RateLimitError,
    500: openai.InternalServerError,
    503: openai.InternalServerError,
}


def status_error(status: int) -> openai.APIStatusError:
    """The SDK subclass the client raises for this status."""
    response = httpx.Response(status, request=REQUEST)
    return STATUS_ERRORS[status]("rejected", response=response, body=None)


@pytest.mark.parametrize("status", [400, 404, 409, 422])
def test_request_faults_are_rejections(status: int) -> None:
    assert is_request_rejected(status_error(status))


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_key_rate_limit_and_server_errors_are_not_rejections(status: int) -> None:
    assert not is_request_rejected(status_error(status))


def test_connection_error_is_not_a_rejection() -> None:
    assert not is_request_rejected(openai.APIConnectionError(request=REQUEST))


@pytest.mark.parametrize(("seconds", "shown"), [(30.0, "30 s"), (2.5, "2.5 s")])
def test_timeout_names_the_setting_and_the_limit(seconds: float, shown: str) -> None:
    error = to_domain_error(openai.APITimeoutError(request=REQUEST), LLMUnavailable, seconds)

    assert isinstance(error, LLMTimeout)
    assert "LLM_TIMEOUT_SECONDS" in error.detail
    assert shown in error.detail


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_key_names_the_secret(status: int) -> None:
    error = to_domain_error(status_error(status), LLMUnavailable, 30)

    assert isinstance(error, LLMUnavailable)
    assert OPENAI_SECRET in error.detail


@pytest.mark.parametrize("status", [429, 500, 503])
def test_status_error_reports_the_status(status: int) -> None:
    error = to_domain_error(status_error(status), LLMUnavailable, 30)

    assert isinstance(error, LLMUnavailable)
    assert f"OpenAI returned {status}" in error.detail


def test_connection_error_says_unreachable() -> None:
    error = to_domain_error(openai.APIConnectionError(request=REQUEST), LLMUnavailable, 30)

    assert isinstance(error, LLMUnavailable)
    assert "unreachable (APIConnectionError)" in error.detail


@pytest.mark.parametrize("unavailable", [LLMUnavailable, EmbeddingUnavailable])
def test_caller_chooses_the_unavailable_type(unavailable: type[Unavailable]) -> None:
    error = to_domain_error(openai.APIConnectionError(request=REQUEST), unavailable, 30)

    assert type(error) is unavailable
