"""Mapping of the incident environment to the Langfuse app environment."""

import pytest

from app.core.app_env import resolve_app_env
from app.core.models.incident import Environment


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        (Environment.DEV, "dev"),
        (Environment.QA, "qa"),
        (Environment.STAGE, "stage"),
        (Environment.PROD, "production"),
        (None, "production"),
    ],
)
def test_environment_maps_to_app_env(environment: Environment | None, expected: str) -> None:
    assert resolve_app_env(environment) == expected
