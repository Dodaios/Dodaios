"""The Prompt tab's rewrite: the user's prompt, a model they picked, the repo as context.

Pinned here: the goal-not-implementation rule reaches the writer whatever
instruction the user typed, the writer sees the repository of the pane the
prompt is meant for, and a failure is reported as one. There is no template
fallback, because the user's own prompt is still in front of them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.agentic_ide import prompt_improver, writer
from jarvis.agentic_ide.prompt_blueprint import GOAL_NOT_IMPLEMENTATION_RULE
from jarvis.agentic_ide.prompt_improver import (
    DEFAULT_INSTRUCTION,
    ImproverFailed,
    ImproverUnavailable,
    improve,
    repo_context,
    system_prompt,
)


class _Brain:
    """Answers with ``reply`` and keeps the requests it was sent."""

    name = "fake-writer"

    def __init__(self, reply: str = "Make the login form accessible.") -> None:
        self.reply = reply
        self.requests: list[object] = []

    async def complete(self, request):  # noqa: ANN001, ANN202 - protocol fake
        self.requests.append(request)
        yield type("Delta", (), {"content": self.reply})()


class _DeadBrain:
    name = "dead-writer"

    async def complete(self, request):  # noqa: ANN001, ANN202 - protocol fake
        raise RuntimeError("401 secret provider body")
        yield  # pragma: no cover - makes this an async generator


def test_the_default_instruction_is_one_sentence_plus_the_goal_rule() -> None:
    prompt = system_prompt()
    assert prompt.startswith(DEFAULT_INSTRUCTION)
    assert GOAL_NOT_IMPLEMENTATION_RULE in prompt


def test_the_users_instruction_replaces_the_default_but_never_the_goal_rule() -> None:
    prompt = system_prompt("  Translate it to\nEnglish and tighten it. ")
    assert prompt.startswith("Translate it to English and tighten it.")
    assert DEFAULT_INSTRUCTION not in prompt
    assert GOAL_NOT_IMPLEMENTATION_RULE in prompt


def test_the_repository_notes_describe_the_folder(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/feature/login\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (tmp_path / "src").mkdir()

    context = repo_context(str(tmp_path), "fix the login")

    assert str(tmp_path) in context
    assert "feature/login" in context
    assert "src" in context


def test_no_folder_means_no_repository_notes() -> None:
    assert repo_context("", "anything") == ""


async def test_the_writer_gets_the_repo_and_the_prompt_and_its_answer_comes_back(
    tmp_path: Path,
) -> None:
    (tmp_path / "frontend").mkdir()
    brain = _Brain("  Make the login form accessible.\n")

    result = await improve("login form barrierefrei machen", folder=str(tmp_path), brain=brain)

    assert result.text == "Make the login form accessible."
    assert result.writer == "fake-writer"
    request = brain.requests[0]
    block = request.messages[0].content
    assert "PROMPT TO IMPROVE\nlogin form barrierefrei machen" in block
    assert str(tmp_path) in block and "frontend" in block
    assert GOAL_NOT_IMPLEMENTATION_RULE in request.system


async def test_a_code_fence_around_the_whole_answer_is_dropped() -> None:
    brain = _Brain("```markdown\nShip the export.\nKeep the CSV columns.\n```")
    result = await improve("export", brain=brain)
    assert result.text == "Ship the export.\nKeep the CSV columns."


async def test_an_empty_prompt_is_refused_before_any_model_is_asked() -> None:
    brain = _Brain()
    with pytest.raises(ValueError):
        await improve("   ", brain=brain)
    assert brain.requests == []


async def test_an_empty_answer_is_a_failure_not_an_improvement() -> None:
    with pytest.raises(ImproverFailed):
        await improve("fix it", brain=_Brain("   "))


async def test_a_failed_call_reports_its_type_and_never_the_providers_text() -> None:
    with pytest.raises(ImproverFailed) as caught:
        await improve("fix it", brain=_DeadBrain())
    assert "RuntimeError" in str(caught.value)
    assert "secret provider body" not in str(caught.value)


async def test_no_pick_and_no_brief_writer_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(writer, "resolve_writer", lambda **_kwargs: (None, ""))
    with pytest.raises(ImproverUnavailable):
        await improve("fix it")


async def test_no_pick_uses_the_ides_brief_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    brain = _Brain("Fix the flaky upload test.")
    monkeypatch.setattr(writer, "resolve_writer", lambda **_kwargs: (brain, "tool_model:fake"))

    result = await improve("upload test flaky")

    assert result.text == "Fix the flaky upload test."
    assert result.source == "tool_model:fake"


async def test_a_provider_the_app_does_not_offer_is_refused() -> None:
    with pytest.raises(ImproverUnavailable):
        await improve("fix it", provider="no-such-provider")


async def test_a_picked_provider_is_built_as_that_seat(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pick resolves to exactly that provider and model, on its own runner."""
    from jarvis.agent_chat import catalog, service
    from jarvis.society import seat_brain

    brain = _Brain("Rename the config key.")
    built: list[object] = []

    async def _seat_brain(_config: object, seat: object, *, caller: str) -> _Brain:
        built.append((seat, caller))
        return brain

    monkeypatch.setattr(catalog, "offers", lambda surface, provider: provider == "picked")
    monkeypatch.setattr(service, "resolve_runner", lambda provider, **_kwargs: "api")
    monkeypatch.setattr(seat_brain, "seat_brain", _seat_brain)
    monkeypatch.setattr(prompt_improver, "_load_config", lambda: object())

    result = await improve("rename it", provider="picked", model="model-x")

    seat, caller = built[0]
    assert (seat.provider, seat.model, seat.runner) == ("picked", "model-x", "api")
    assert caller == "prompt_improver"
    assert result.source == "provider:picked"
