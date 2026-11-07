"""Map OpenAI SDK exceptions to domain errors. Messages name what to check, never secrets."""

import openai

from app.core.errors import AppError, LLMTimeout, Unavailable

OPENAI_SECRET = "incident-triage/openai-api-key"
_NOT_REQUEST_FAULTS = (401, 403, 429)


def is_request_rejected(exc: openai.OpenAIError) -> bool:
    """True for a 4xx caused by the request itself, not by the key or the rate limit."""
    return (
        isinstance(exc, openai.APIStatusError)
        and 400 <= exc.status_code < 500
        and exc.status_code not in _NOT_REQUEST_FAULTS
    )


def to_domain_error(
    exc: openai.OpenAIError, unavailable: type[Unavailable], timeout_seconds: float
) -> AppError:
    """Timeout -> LLMTimeout; key rejected, network, rate limit or 5xx -> `unavailable`."""
    if isinstance(exc, openai.APITimeoutError):
        return LLMTimeout(
            f"OpenAI did not answer within {timeout_seconds:g} s; retry, or raise "
            "LLM_TIMEOUT_SECONDS (embeddings: EMBEDDING_TIMEOUT_SECONDS) and restart the API"
        )
    if isinstance(exc, openai.AuthenticationError | openai.PermissionDeniedError):
        return unavailable(f"OpenAI rejected the API key; check secret `{OPENAI_SECRET}`")
    if isinstance(exc, openai.APIStatusError):
        return unavailable(f"OpenAI returned {exc.status_code}; retry later")
    return unavailable(f"OpenAI is unreachable ({type(exc).__name__}); check the network")
