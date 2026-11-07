"""Read the four app secrets from AWS Secrets Manager with exact keys."""

import json
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.errors import ConfigurationError
from app.core.secrets import DatabaseCredentials, Secrets

DB_SECRET = "incident-triage/db-credentials"
OPENAI_SECRET = "incident-triage/openai-api-key"
LANGFUSE_PUBLIC_SECRET = "incident-triage/langfuse-public-key"
LANGFUSE_SECRET_SECRET = "incident-triage/langfuse-secret-key"

DB_KEYS = ("host", "port", "dbname", "username", "password")


def load_secrets(region: str, client: Any | None = None) -> Secrets:
    """Load all secrets. Raises ConfigurationError naming the secret and key, never a value."""
    client = client or boto3.client("secretsmanager", region_name=region)
    db = _read(client, DB_SECRET, DB_KEYS)
    return Secrets(
        database=DatabaseCredentials(**db),
        openai_api_key=_read(client, OPENAI_SECRET, ("OPENAI_API_KEY",))["OPENAI_API_KEY"],
        langfuse_public_key=_read(client, LANGFUSE_PUBLIC_SECRET, ("LANGFUSE_PUBLIC_KEY",))[
            "LANGFUSE_PUBLIC_KEY"
        ],
        langfuse_secret_key=_read(client, LANGFUSE_SECRET_SECRET, ("LANGFUSE_SECRET_KEY",))[
            "LANGFUSE_SECRET_KEY"
        ],
    )


def _read(client: Any, name: str, keys: tuple[str, ...]) -> dict[str, Any]:
    try:
        raw = client.get_secret_value(SecretId=name)["SecretString"]
    except (ClientError, BotoCoreError) as exc:
        raise ConfigurationError(f"secret {name} is not readable: {type(exc).__name__}") from None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ConfigurationError(f"secret {name} is not JSON") from None
    if not isinstance(data, dict):
        raise ConfigurationError(f"secret {name} must be a JSON object")
    missing = [key for key in keys if key not in data]
    if missing:
        raise ConfigurationError(f"secret {name} is missing key {', '.join(missing)}")
    return {key: data[key] for key in keys}
