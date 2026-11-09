"""OpenCode brain provider: event parsing, argv, model pick and catalog wiring."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dodaios.plugins.brain import opencode as oc

_TEXT = (
    '{"type":"step_start","part":{"type":"step-start"}}\n'
    '{"type":"text","part":{"type":"text","text":"Hello there."}}\n'
    '{"type":"step_finish","part":{"type":"step-finish","reason":"stop"}}\n'
)
_ERROR = (
    '{"type":"error","error":{"name":"UnknownError",'
    '"data":{"message":"Unexpected server error."}}}\n'
)


def test_parse_events_collects_text() -> None:
    assert oc.parse_events(_TEXT) == ("Hello there.", None)


def test_parse_events_joins_several_text_parts_and_skips_noise() -> None:
    out = 'log line\n{"type":"text","part":{"text":"A"}}\nnot json {\n' + (
        '{"type":"text","part":{"text":"B"}}\n'
    )
    assert oc.parse_events(out) == ("A\n\nB", None)


def test_parse_events_reports_error() -> None:
    assert oc.parse_events(_ERROR) == ("", "Unexpected server error.")


def test_parse_events_empty() -> None:
    assert oc.parse_events("") == ("", None)


def test_argv_is_read_only_json_and_gates_optional_flags() -> None:
    argv = oc._build_argv(["opencode"], "opencode/big-pickle", frozenset({"--pure"}))
    assert argv[:6] == ["opencode", "run", "--format", "json", "--agent", "plan"]
    assert "--pure" in argv
    assert argv[-2:] == ["--model", "opencode/big-pickle"]
    old_cli = oc._build_argv(["opencode"], "x/y", frozenset())
    assert "--pure" not in old_cli


def test_pick_free_model_prefers_big_pickle_then_first_free() -> None:
    ids = ["google/gemini-3", "opencode/glm-free", "opencode/big-pickle"]
    assert oc.pick_free_model(ids) == "opencode/big-pickle"
    assert oc.pick_free_model(["opencode/a-free", "opencode/b-free"]) == "opencode/a-free"
    # A keyed model is never picked on its own.
    assert oc.pick_free_model(["google/gemini-3", "opencode/paid-model"]) is None


def test_conversational_prompt_carries_recent_turns() -> None:
    req = SimpleNamespace(
        system="",
        messages=[SimpleNamespace(role="user", content="What time is it?")],
    )
    prompt = oc._build_cli_prompt(req)  # type: ignore[arg-type]
    assert "User: What time is it?" in prompt
    assert prompt.endswith("Assistant:")


def test_complete_without_any_model_fails_honestly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oc, "_argv_prefix", lambda: ["opencode"])
    monkeypatch.setattr(oc, "_probe_flags", lambda prefix: frozenset())
    monkeypatch.setattr(oc, "_installed_free_model", lambda: None)
    brain = oc.OpenCodeBrain()
    req = SimpleNamespace(system="", messages=[])

    async def run() -> None:
        async for _ in brain.complete(req):  # type: ignore[arg-type]
            pass

    with pytest.raises(RuntimeError, match="no model"):
        asyncio.run(run())


def test_brain_is_a_cli_brain() -> None:
    brain = oc.OpenCodeBrain(structured_prompts=True, cli_timeout_s=30)
    assert brain.name == "opencode"
    assert brain.can_call_tools() is False
    assert oc.OpenCodeBrain.native_system_prompt is False
    assert brain.estimate_cost(SimpleNamespace()) == 0.0  # type: ignore[arg-type]


def test_provider_card_is_a_subscription_cli_and_never_the_main_brain() -> None:
    from dodaios.ui.web.provider_spec import PROVIDERS, get_spec, provider_billing

    spec = get_spec("opencode")
    assert spec is not None
    assert spec.tier == "brain"
    assert spec.auth_mode == "opencode"
    assert spec.secret_keys == ()
    assert spec.brain_switchable is False
    assert provider_billing(spec) == "subscription"
    # Last of the CLI brains, so the subscription resolver only reaches it when
    # no signed-in sibling with a system channel exists.
    cli_ids = [
        s.id for s in PROVIDERS if s.tier == "brain" and provider_billing(s).startswith("sub")
    ]
    assert cli_ids[-1] == "opencode"


def test_credential_follows_the_installed_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.agent_chat import runner_cli
    from dodaios.brain.app_control import is_credential_present
    from dodaios.ui.web.provider_spec import get_spec

    spec = get_spec("opencode")
    monkeypatch.setattr(runner_cli, "cli_installed", lambda runner: runner == "opencode-cli")
    assert is_credential_present(spec) is True
    monkeypatch.setattr(runner_cli, "cli_installed", lambda runner: False)
    assert is_credential_present(spec) is False


def test_model_picker_lists_the_installed_cli_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from dodaios.agent_chat import runner_cli
    from dodaios.brain import model_catalog

    monkeypatch.setattr(
        runner_cli,
        "read_opencode_models",
        lambda: [{"id": "google/gemini-3"}, {"id": "opencode/big-pickle"}],
    )
    spec = model_catalog.catalog_spec("opencode")
    assert spec is not None and spec.live is False
    result = asyncio.run(model_catalog.ModelCatalog().list_models("opencode"))
    ids = [m.id for m in result.models]
    assert ids[0] == "opencode/big-pickle"
    assert "google/gemini-3" in ids
