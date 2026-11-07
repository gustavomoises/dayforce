"""Domain errors. Each carries the HTTP status it maps to in the exception handler."""


class ConfigurationError(Exception):
    """Startup cannot continue (for example a missing secret key)."""


class AppError(Exception):
    """Base for errors returned to clients as {error, detail, correlation_id}."""

    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InvalidInput(AppError):
    status_code = 422
    code = "invalid_input"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class TraceNotReady(NotFound):
    code = "trace_not_ready"


class UpstreamInvalid(AppError):
    """An external service answered, but the answer is unusable."""

    status_code = 502
    code = "upstream_invalid"


class LLMOutputInvalid(UpstreamInvalid):
    code = "llm_output_invalid"


class GroundingFailure(UpstreamInvalid):
    code = "grounding_failure"


class EmbeddingInvalid(UpstreamInvalid):
    code = "embedding_invalid"


class Unavailable(AppError):
    """An external service or its configuration is not usable right now."""

    status_code = 503
    code = "unavailable"


class LangfuseUnavailable(Unavailable):
    code = "langfuse_unavailable"


class PromptLabelMissing(Unavailable):
    code = "prompt_label_missing"


class PromptConfigInvalid(Unavailable):
    code = "prompt_config_invalid"


class LLMUnavailable(Unavailable):
    code = "llm_unavailable"


class EmbeddingUnavailable(Unavailable):
    code = "embedding_unavailable"


class LLMTimeout(AppError):
    status_code = 504
    code = "llm_timeout"
