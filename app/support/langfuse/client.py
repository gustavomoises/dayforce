"""Build the Langfuse client. Called from the container, never at import time."""

from langfuse import Langfuse

from app.core.secrets import Secrets
from app.core.settings import Settings


def create_langfuse(secrets: Secrets, settings: Settings) -> Langfuse:
    """Langfuse client for the configured host, keys from Secrets Manager."""
    return Langfuse(
        public_key=secrets.langfuse_public_key.get_secret_value(),
        secret_key=secrets.langfuse_secret_key.get_secret_value(),
        base_url=settings.langfuse_host,
    )
