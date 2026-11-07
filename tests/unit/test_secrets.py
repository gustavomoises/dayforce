"""Secrets loader: exact keys, clear errors, and secret values never in messages."""

import json
from typing import Any

import pytest
from botocore.exceptions import ClientError

from app.core.errors import ConfigurationError
from app.support.secrets.secrets_manager import (
    DB_SECRET,
    LANGFUSE_PUBLIC_SECRET,
    LANGFUSE_SECRET_SECRET,
    OPENAI_SECRET,
    load_secrets,
)

PASSWORD = "hunter2-db-password"
OPENAI_KEY = "sk-test-openai-value"


def valid_secrets() -> dict[str, str]:
    return {
        DB_SECRET: json.dumps(
            {
                "host": "db.internal",
                "port": "5432",
                "dbname": "incidents",
                "username": "triage",
                "password": PASSWORD,
            }
        ),
        OPENAI_SECRET: json.dumps({"OPENAI_API_KEY": OPENAI_KEY}),
        LANGFUSE_PUBLIC_SECRET: json.dumps({"LANGFUSE_PUBLIC_KEY": "pk-lf-value"}),
        LANGFUSE_SECRET_SECRET: json.dumps({"LANGFUSE_SECRET_KEY": "sk-lf-value"}),
    }


class FakeSecretsClient:
    """Stands in for the boto3 secretsmanager client."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    def get_secret_value(self, SecretId: str) -> dict[str, Any]:
        if SecretId not in self._secrets:
            raise ClientError(
                {"Error": {"Code": "AccessDeniedException", "Message": "denied"}},
                "GetSecretValue",
            )
        return {"SecretString": self._secrets[SecretId]}


def load_error(secrets: dict[str, str]) -> str:
    with pytest.raises(ConfigurationError) as caught:
        load_secrets("us-east-2", client=FakeSecretsClient(secrets))
    return str(caught.value)


def test_valid_secrets_are_loaded() -> None:
    secrets = load_secrets("us-east-2", client=FakeSecretsClient(valid_secrets()))

    assert secrets.database.port == 5432
    assert secrets.database.password.get_secret_value() == PASSWORD
    assert secrets.openai_api_key.get_secret_value() == OPENAI_KEY
    assert secrets.langfuse_secret_key.get_secret_value() == "sk-lf-value"


def test_secret_values_are_hidden_in_repr() -> None:
    secrets = load_secrets("us-east-2", client=FakeSecretsClient(valid_secrets()))

    assert PASSWORD not in repr(secrets)
    assert OPENAI_KEY not in repr(secrets)


def test_unreadable_secret_names_it_and_the_permission() -> None:
    secrets = valid_secrets()
    del secrets[OPENAI_SECRET]

    message = load_error(secrets)

    assert OPENAI_SECRET in message
    assert "secretsmanager:GetSecretValue" in message


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (OPENAI_KEY, "is not JSON"),
        (json.dumps(OPENAI_KEY), "must be a JSON object"),
        (json.dumps({"openai_api_key": OPENAI_KEY}), "is missing key OPENAI_API_KEY"),
    ],
    ids=["not-json", "not-object", "missing-key"],
)
def test_malformed_secret_is_named_without_its_value(raw: str, expected: str) -> None:
    message = load_error({**valid_secrets(), OPENAI_SECRET: raw})

    assert f"secret {OPENAI_SECRET} {expected}" in message
    assert OPENAI_KEY not in message


def test_missing_database_keys_are_listed_without_values() -> None:
    message = load_error({**valid_secrets(), DB_SECRET: json.dumps({"password": PASSWORD})})

    assert "host, port, dbname, username" in message
    assert PASSWORD not in message
