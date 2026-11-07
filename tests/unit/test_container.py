"""Container wiring, and the API lifespan and CLI building the same container."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import main
from app import cli
from app import container as container_module
from app.core.errors import ConfigurationError
from app.core.settings import Settings


class FakeClient:
    """Stands in for Langfuse, the pool and OpenAI; records close and flush."""

    def __init__(self) -> None:
        self.closed = False
        self.flushed = False

    def close(self) -> None:
        self.closed = True

    def flush(self) -> None:
        self.flushed = True


class FakeContainer:
    """What the entry points need from a Container."""

    def __init__(self) -> None:
        self.langfuse = FakeClient()
        self.schema = SimpleNamespace(create=self._create_schema)
        self.schema_created = False
        self.closed = False
        self.settings: Settings | None = None

    def _create_schema(self) -> None:
        self.schema_created = True

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def clients(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the client factories so build_container touches no AWS, database or network."""
    built: dict[str, Any] = {"langfuse": FakeClient(), "pool": FakeClient(), "openai": FakeClient()}

    def load_secrets(region: str) -> SimpleNamespace:
        built["region"] = region
        return SimpleNamespace(database=None)

    monkeypatch.setattr(container_module, "load_secrets", load_secrets)
    monkeypatch.setattr(container_module, "create_langfuse", lambda s, _: built["langfuse"])
    monkeypatch.setattr(container_module, "create_pool", lambda db, _: built["pool"])
    monkeypatch.setattr(container_module, "create_openai", lambda s, _: built["openai"])
    return built


@pytest.fixture
def fake_builder(monkeypatch: pytest.MonkeyPatch) -> FakeContainer:
    fake = FakeContainer()

    def build(settings: Settings) -> FakeContainer:
        fake.settings = settings
        return fake

    for module in (main, cli):
        monkeypatch.setattr(module, "build_container", build)
        monkeypatch.setattr(module, "configure_logging", lambda *args: None)
    return fake


@contextmanager
def fake_root(*args: Any) -> Iterator[SimpleNamespace]:
    yield SimpleNamespace(update=lambda **fields: None)


def test_api_and_cli_import_the_same_builder() -> None:
    assert main.build_container is container_module.build_container
    assert cli.build_container is container_module.build_container


def test_secrets_are_read_from_the_configured_region(clients: dict[str, Any]) -> None:
    container_module.build_container(Settings(aws_region="eu-west-1"))

    assert clients["region"] == "eu-west-1"


def test_services_share_one_repository_and_one_set_of_clients(clients: dict[str, Any]) -> None:
    built = container_module.build_container(Settings())

    assert (built.langfuse, built.pool, built.openai) == (
        clients["langfuse"],
        clients["pool"],
        clients["openai"],
    )
    assert built.search._repository is built.repository
    assert built.incidents._repository is built.repository
    assert built.ingest._embedder is built.search._embedder
    assert built.assist._screener._search is built.search
    assert built.assist._incidents is built.incidents
    assert built.assist._llm is built.catalog._llm is built.assist._screener._llm


def test_close_flushes_traces_and_releases_clients(clients: dict[str, Any]) -> None:
    container_module.build_container(Settings()).close()

    assert clients["langfuse"].flushed
    assert clients["pool"].closed
    assert clients["openai"].closed


def test_api_lifespan_builds_the_container_once_and_closes_it(
    fake_builder: FakeContainer,
) -> None:
    app = main.create_app()

    with TestClient(app):
        assert app.state.container is fake_builder
        assert not fake_builder.closed

    assert fake_builder.closed
    assert isinstance(fake_builder.settings, Settings)


def test_cli_runs_the_command_on_the_same_container(
    fake_builder: FakeContainer,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "root_observation", fake_root)

    assert cli.main(["schema"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["schema"] == "created"
    assert output["correlation_id"]
    assert fake_builder.schema_created and fake_builder.closed
    assert isinstance(fake_builder.settings, Settings)


def test_cli_reports_configuration_errors_without_a_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(settings: Settings) -> None:
        raise ConfigurationError("secret incident-triage/openai-api-key: missing OPENAI_API_KEY")

    monkeypatch.setattr(cli, "build_container", fail)
    monkeypatch.setattr(cli, "configure_logging", lambda *args: None)

    assert cli.main(["schema"]) == 1

    err = capsys.readouterr().err
    assert err.startswith("error: secret incident-triage/openai-api-key")
    assert "Traceback" not in err


def test_cli_schemas_needs_no_container(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(settings: Settings) -> None:
        raise AssertionError("schemas must not build the container")

    monkeypatch.setattr(cli, "build_container", fail)
    monkeypatch.setattr(cli, "configure_logging", lambda *args: None)

    assert cli.main(["schemas"]) == 0

    assert set(json.loads(capsys.readouterr().out)) == {
        "assist_answer",
        "validation_answer",
        "catalog_batch",
    }
