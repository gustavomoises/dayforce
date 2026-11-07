"""Map the request's incident environment to the Langfuse label and trace environment."""

from app.core.models.incident import Environment

DEFAULT_APP_ENV = "production"

_LANGFUSE_NAMES = {Environment.PROD: "production"}


def resolve_app_env(environment: Environment | None) -> str:
    """dev/qa/stage as is, prod -> production, none -> production."""
    if environment is None:
        return DEFAULT_APP_ENV
    return _LANGFUSE_NAMES.get(environment, environment.value)
