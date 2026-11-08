"""Settings.from_env: defaults, overrides by upper-case env var, and type checks."""

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


def test_unset_env_keeps_the_defaults() -> None:
    assert Settings.from_env() == Settings()


def test_defaults_match_the_spec() -> None:
    settings = Settings.from_env()

    assert settings.embedding_model == "text-embedding-3-small"
    assert settings.embedding_dimensions == 1536
    assert settings.embedding_batch_size == 100
    assert settings.ingest_max_items == 500
    assert (settings.seed_min_incidents, settings.seed_max_incidents) == (200, 999)
    assert settings.seed_repeats == 1
    assert settings.ivfflat_max_lists == 10


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        ("LLM_TIMEOUT_SECONDS", "0.01", 0.01),
        ("SEED_REPEATS", "3", 3),
        ("AWS_REGION", "eu-west-1", "eu-west-1"),
        ("EMBEDDING_MODEL", "text-embedding-3-large", "text-embedding-3-large"),
    ],
)
def test_env_var_overrides_and_is_coerced(
    monkeypatch: pytest.MonkeyPatch, name: str, raw: str, expected: object
) -> None:
    monkeypatch.setenv(name, raw)

    assert getattr(Settings.from_env(), name.lower()) == expected


def test_invalid_env_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEED_REPEATS", "two")

    with pytest.raises(ValidationError):
        Settings.from_env()


def test_settings_are_frozen() -> None:
    settings = Settings()

    with pytest.raises(ValidationError):
        settings.seed = 7  # type: ignore[misc]
