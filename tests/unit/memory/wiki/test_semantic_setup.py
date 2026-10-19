"""Switching semantic search on and off: honest states, retryable failures."""
from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from dodaios.memory.wiki import semantic_model, semantic_search, semantic_setup
from tests.fakes.fake_semantic_encoder import FakeSemanticEncoder


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(semantic_setup, "_run", semantic_setup._Run())
    semantic_search.deactivate()
    yield
    semantic_search.deactivate()


@pytest.fixture()
def config(tmp_path: Path) -> SimpleNamespace:
    vault = tmp_path / "vault"
    (vault / "entities").mkdir(parents=True)
    (vault / "entities" / "anna.md").write_text(
        "---\ntype: entity\n---\n# Anna\n\n- My sister\n- Birthday on 4 May\n", encoding="utf-8"
    )
    return SimpleNamespace(
        wiki_context=SimpleNamespace(semantic_search=True),
        wiki_integration=SimpleNamespace(vault_root=vault),
        memory=SimpleNamespace(data_dir=str(tmp_path / "data")),
    )


class _Machine:
    """The parts of this computer the setup touches, under the test's control."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.runtime = True
        self.model_on_disk = False
        self.downloads = 0
        self.download_error: Exception | None = None
        self.hold_download = threading.Event()
        self.hold_download.set()
        self.encoder = FakeSemanticEncoder()
        real_activate = semantic_search.activate

        def download(_data_dir: Any = None, *, progress: Any = None) -> None:
            self.downloads += 1
            self.hold_download.wait(timeout=5)
            if self.download_error is not None:
                raise self.download_error
            if progress is not None:
                progress(1, 2)  # raises when the run was switched off meanwhile
            self.model_on_disk = True

        def activate(vault_root: Path, **kwargs: Any) -> Any:
            return real_activate(vault_root, **{**kwargs, "encoder": self.encoder})

        monkeypatch.setattr(semantic_model, "runtime_available", lambda: self.runtime)
        monkeypatch.setattr(semantic_model, "model_present", lambda _d=None: self.model_on_disk)
        monkeypatch.setattr(semantic_model, "download_model", download)
        monkeypatch.setattr(semantic_search, "activate", activate)


@pytest.fixture()
def machine(monkeypatch: pytest.MonkeyPatch) -> _Machine:
    return _Machine(monkeypatch)


def _finish() -> None:
    thread = semantic_setup._run.thread
    assert thread is not None
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_it_is_off_until_the_user_switches_it_on(
    config: SimpleNamespace, machine: _Machine
) -> None:
    config.wiki_context.semantic_search = False
    semantic_setup.resume(config)

    report = semantic_setup.status(config)

    assert report["enabled"] is False
    assert report["state"] == "off"
    assert machine.downloads == 0, "nothing is fetched that nobody asked for"
    assert semantic_search.get_active() is None


def test_switching_it_on_downloads_once_and_encodes_the_vault(
    config: SimpleNamespace, machine: _Machine
) -> None:
    assert semantic_setup.start(config) is True
    _finish()

    report = semantic_setup.status(config)
    assert report["state"] == "ready"
    assert report["model_present"] is True
    assert (report["pages"], report["passages"]) == (1, 2)
    assert machine.downloads == 1
    assert semantic_search.get_active() is not None


def test_a_restart_with_the_model_on_disk_downloads_nothing(
    config: SimpleNamespace, machine: _Machine
) -> None:
    machine.model_on_disk = True
    semantic_setup.resume(config)
    _finish()

    assert machine.downloads == 0
    assert semantic_setup.status(config)["state"] == "ready"


def test_a_failed_download_is_reported_and_can_be_retried(
    config: SimpleNamespace, machine: _Machine
) -> None:
    machine.download_error = httpx.ConnectError("no route to host")
    semantic_setup.start(config)
    _finish()

    report = semantic_setup.status(config)
    assert report["state"] == "error"
    assert "internet connection" in report["message"]
    assert semantic_search.get_active() is None

    machine.download_error = None
    semantic_setup.start(config)
    _finish()
    assert semantic_setup.status(config)["state"] == "ready"


def test_a_system_without_the_runtime_says_so_and_fetches_nothing(
    config: SimpleNamespace, machine: _Machine
) -> None:
    machine.runtime = False

    assert semantic_setup.start(config) is False

    report = semantic_setup.status(config)
    assert report["available"] is False
    assert report["state"] == "error"
    assert "word search keeps working" in report["message"]
    assert machine.downloads == 0


def test_a_missing_wiki_folder_is_an_honest_error(
    config: SimpleNamespace, machine: _Machine, tmp_path: Path
) -> None:
    config.wiki_integration.vault_root = tmp_path / "nowhere"
    assert semantic_setup.start(config) is False
    assert semantic_setup.status(config)["state"] == "error"
    assert machine.downloads == 0


def test_switching_it_off_during_the_download_never_activates_it(
    config: SimpleNamespace, machine: _Machine
) -> None:
    machine.hold_download.clear()
    semantic_setup.start(config)
    assert semantic_setup.status(config)["state"] == "downloading"

    config.wiki_context.semantic_search = False
    semantic_setup.stop()
    machine.hold_download.set()
    _finish()

    assert semantic_search.get_active() is None
    assert semantic_setup.status(config)["state"] == "off"


def test_switching_it_off_releases_the_model(
    config: SimpleNamespace, machine: _Machine
) -> None:
    semantic_setup.start(config)
    _finish()

    semantic_setup.stop()

    assert semantic_search.get_active() is None
    assert machine.encoder.closed == 1


def test_a_second_start_joins_the_run_in_flight(
    config: SimpleNamespace, machine: _Machine
) -> None:
    machine.hold_download.clear()
    semantic_setup.start(config)
    first = semantic_setup._run.thread
    semantic_setup.start(config)
    assert semantic_setup._run.thread is first
    machine.hold_download.set()
    _finish()
    assert machine.downloads == 1


def test_off_and_on_again_during_the_download_still_ends_ready(
    config: SimpleNamespace, machine: _Machine
) -> None:
    machine.hold_download.clear()
    semantic_setup.start(config)
    first = semantic_setup._run.thread

    semantic_setup.stop()
    semantic_setup.start(config)
    assert semantic_setup._run.thread is not first, "an overtaken run is not joined"

    machine.hold_download.set()
    _finish()
    assert first is not None and not first.is_alive()
    assert semantic_setup.status(config)["state"] == "ready"
    assert semantic_search.get_active() is not None


class _HoldingEncoder(FakeSemanticEncoder):
    """Blocks inside the first page until the test lets it go."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def encode(self, texts, *, wait=True):  # type: ignore[no-untyped-def]
        self.entered.set()
        self.release.wait(timeout=5)
        return super().encode(texts, wait=wait)


def test_switching_it_off_while_the_vault_is_read_ends_the_run_at_that_page(
    config: SimpleNamespace, machine: _Machine
) -> None:
    vault = config.wiki_integration.vault_root
    for name in ("bea", "cleo", "dana"):
        (vault / "entities" / f"{name}.md").write_text(
            f"---\ntype: entity\n---\n# {name}\n\n- A friend of the family\n", encoding="utf-8"
        )
    machine.model_on_disk = True
    machine.encoder = _HoldingEncoder()
    semantic_setup.start(config)
    assert machine.encoder.entered.wait(timeout=5)
    assert semantic_setup.status(config)["state"] == "indexing"

    semantic_setup.stop()
    machine.encoder.release.set()
    _finish()

    assert len(machine.encoder.calls) == 1, "the other three pages were never encoded"
    assert semantic_search.get_active() is None
    assert semantic_setup.status(config)["state"] == "off"


def test_a_model_that_cannot_read_any_page_is_an_error_and_is_taken_down(
    config: SimpleNamespace, machine: _Machine
) -> None:
    class Dead(FakeSemanticEncoder):
        def encode(self, texts, *, wait=True):  # type: ignore[no-untyped-def]
            raise RuntimeError("the model file is damaged")

    machine.model_on_disk = True
    machine.encoder = Dead()
    semantic_setup.start(config)
    _finish()

    report = semantic_setup.status(config)
    assert report["state"] == "error"
    assert "could not be set up" in report["message"]
    assert semantic_search.get_active() is None, "no half-alive search behind a failed switch"


def test_a_wiki_that_is_switched_off_is_an_honest_error(
    config: SimpleNamespace, machine: _Machine
) -> None:
    config.wiki_integration.enabled = False
    assert semantic_setup.start(config) is False
    report = semantic_setup.status(config)
    assert report["state"] == "error"
    assert "wiki is switched off" in report["message"]
    assert machine.downloads == 0


def test_a_server_that_refuses_the_file_is_not_blamed_on_the_connection(
    config: SimpleNamespace, machine: _Machine
) -> None:
    request = httpx.Request("GET", "https://example.test/model")
    machine.download_error = httpx.HTTPStatusError(
        "gone", request=request, response=httpx.Response(404, request=request)
    )
    semantic_setup.start(config)
    _finish()

    message = semantic_setup.status(config)["message"]
    assert "server refused" in message
    assert "internet connection" not in message


def test_the_state_never_carries_an_exception_text(
    config: SimpleNamespace, machine: _Machine
) -> None:
    """The state is served over the API; an error text can hold local paths."""
    machine.download_error = PermissionError(13, "denied", "/home/someone/secret/model.part")
    semantic_setup.start(config)
    _finish()

    report = semantic_setup.status(config)
    assert report["state"] == "error"
    assert "stored on this disk" in report["message"]
    assert "someone" not in report["message"]
    assert "denied" not in report["message"]
