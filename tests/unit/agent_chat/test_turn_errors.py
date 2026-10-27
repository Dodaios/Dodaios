"""The failed-turn card gets a short reason; raw runtime output stays redacted details."""

from __future__ import annotations

import asyncio
import os

import pytest

from dodaios.agent_chat import turn_errors
from dodaios.agent_chat.turn_errors import (
    APP_RESTARTED,
    RUNTIME_UPDATING,
    STILL_STARTING,
    readable_turn_error,
    redact,
    stall_reason,
)

HOME = os.path.expanduser("~")

HERMES_DUMP = "\n".join(
    [
        "2026-10-27 17:05:19 [INFO] tools.tool_search: tool_search activated (tier 1): "
        "10 core/visible tools kept, 381 deferred",
        "2026-10-27 17:05:19 [INFO] acp_adapter.server: New session 6d5a "
        f"(cwd={HOME}\\Desktop\\Personal Jarvis\\data\\society\\qa-hermes-local\\workspace)",
        "2026-10-27 17:05:21 [INFO] acp_adapter.server: Prompt on session 6d5a: <jarvis_identity>",
        "## You are QA Hermes local",
        "Tier: specialist. Permission ceiling: ask. You do not",
        "2026-10-27 17:05:21 [INFO] agent.turn_context: conversation turn: session=6d5a "
        "model=qwen3.5:9b msg='<jarvis_identity> ## You are QA Hermes local  Tier: spec...'",
        "2026-10-27 17:05:25 [INFO] run_agent: OpenAI client created provider=custom "
        "base_url=http://127.0.0.1:47821/api/runtime-gateway/v1 model=qwen3.5:9b",
    ]
)


def test_a_raw_stderr_dump_becomes_a_short_reason_with_redacted_details() -> None:
    reason, details = readable_turn_error(HERMES_DUMP, runner="hermes-cli", provider="ollama")
    assert reason == "Hermes stopped with an error. Try again."
    assert details is not None
    for leak in (
        "<jarvis_identity>",
        "You are QA Hermes",
        "Permission ceiling",
        "127.0.0.1:47821",
        "runtime-gateway",
        HOME,
    ):
        assert leak not in details, leak
    assert "tool_search activated" in details
    assert "[url]" in details


def test_redact_strips_prompt_blocks_urls_secrets_and_home() -> None:
    text = (
        "<jarvis_identity>secret persona</jarvis_identity> ok "
        "https://api.example.com/v1?token=abc sk-abcdefghijklmnop "
        f"{HOME}/projects/x /home/someone/y C:\\Users\\Other\\z"
    )
    out = redact(text)
    assert "secret persona" not in out
    assert "token=abc" not in out and "[url]" in out
    assert "sk-abcdefghijklmnop" not in out
    assert HOME not in out and "someone" not in out and "Other" not in out
    assert out.startswith("[agent instructions removed] ok")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "Internal error: UNAVAILABLE: OpenClaw agent database C:/x/state.db uses schema "
            "version 3; run openclaw doctor --fix to migrate persisted media before using it.",
            RUNTIME_UPDATING,
        ),
        (
            "Agent main has not completed startup inspection and preparation. busy",
            STILL_STARTING,
        ),
    ],
)
def test_gateway_unavailable_replies_read_as_reasons(raw: str, expected: str) -> None:
    reason, details = readable_turn_error(raw, runner="openclaw-cli")
    assert reason == expected
    assert details and details.startswith(raw[:20])  # the raw reply, redacted, stays apart


def test_acp_error_text_translates_unavailable_details_without_exposing_them() -> None:
    from dodaios.agent_runtimes.acp import _error_text

    error = {
        "message": "Internal error",
        "data": {"details": "Agent main has not completed startup inspection and preparation."},
    }
    assert _error_text(error) == STILL_STARTING
    error = {
        "message": "Internal error",
        "data": {"details": "state db uses schema version 9; run openclaw doctor --fix first"},
    }
    assert _error_text(error) == RUNTIME_UPDATING
    # Anything else stays the bare wrapper.
    assert _error_text({"message": "Internal error", "data": {"details": "x"}}) == "Internal error"


def test_a_bare_internal_error_names_the_runtime() -> None:
    reason, details = readable_turn_error("Internal error", runner="openclaw-cli")
    assert reason == "OpenClaw hit an internal error and stopped this turn. Try again."
    assert details is None


def test_a_stall_uses_the_display_name_and_suspects_a_local_model() -> None:
    cloud = stall_reason("openclaw-cli", 300, provider="openai-codex")
    assert cloud.startswith("OpenClaw got no reply from the model for 5 minutes")
    assert "openclaw-cli" not in cloud
    local = stall_reason("openclaw-cli", 300, provider="ollama")
    assert "local model" in local and "busy" in local
    legacy, _ = readable_turn_error(
        "openclaw-cli stopped responding (nothing for 5 minutes); the turn was stopped.",
        runner="openclaw-cli",
        provider="ollama",
    )
    assert legacy == local


def test_an_app_restart_says_so_in_old_and_new_wording() -> None:
    for text in (
        "Dodaios restarted while this turn was running. Everything after the last step "
        "shown here was not captured.",
        "Jarvis restarted while this turn was running.",
    ):
        assert readable_turn_error(text)[0] == APP_RESTARTED


def test_deliberate_reasons_pass_through_unchanged() -> None:
    for text in (
        "The ChatGPT subscription reached its usage limit: the plan's allowance is used up "
        "until it resets (it resets at 2026-11-18T17:19:20Z). Until then, choose another "
        "connected model in the agent's settings. No fallback provider was called.",
        "Ollama is not reachable. If it is a model server on this computer, start it.",
        "mandated_tool_unfulfilled",
    ):
        assert readable_turn_error(text, runner="openclaw-cli") == (text, None)
    assert readable_turn_error("openclaw-cli exited with code 1.") == (
        "OpenClaw exited with code 1.",
        None,
    )
    assert readable_turn_error(None) == (None, None)


def test_the_service_publishes_the_reason_and_keeps_details_apart(tmp_path) -> None:
    from dodaios.agent_chat.events import make_event
    from dodaios.agent_chat.service import AgentChatService
    from dodaios.agent_chat.store import AgentChatStore

    store = AgentChatStore(tmp_path / "chat.db")
    service = AgentChatService(store)
    session = store.create_session(
        provider="ollama",
        model="qwen3.5:9b",
        effort="",
        cwd=str(tmp_path),
        surface="society",
        runtime="hermes",
    )
    seen: list[dict] = []

    async def run() -> None:
        queue = service.subscribe(session.session_id)
        service._publish_event(
            session.session_id,
            make_event(
                "turn_finished",
                {"turn_id": "t1", "status": "error", "usage": {}, "error": HERMES_DUMP},
            ),
        )
        seen.append(queue.get_nowait())

    asyncio.run(run())
    payload = seen[0]["payload"]
    assert "jarvis_identity" not in payload["error"]
    assert payload["error"] == "Hermes stopped with an error. Try again."
    assert "You are QA Hermes" not in payload["error_details"]
    stored = [e for e in store.list_events(session.session_id) if e["kind"] == "turn_finished"]
    assert stored and stored[0]["payload"]["error"] == payload["error"]


def test_runner_labels_cover_every_cli_runner() -> None:
    from typing import get_args

    from dodaios.agent_chat.catalog import Runner

    for runner in get_args(Runner):
        assert turn_errors.runner_label(runner) and "-cli" not in turn_errors.runner_label(runner)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "2026-10-27 17:05:19 [ERROR] provider: HTTP 429 usage limit reached, "
            "resets at 2026-10-28T15:04:00Z",
            "The usage limit for this model is used up. It resets at 2026-10-28T15:04:00Z.",
        ),
        (
            "You've hit your usage limit. " + "Upgrade for more. " * 40
            + "try again at Oct 15th, 2026 3:37 PM",
            "The usage limit for this model is used up. "
            "You can try again at Oct 15th, 2026 3:37 PM.",
        ),
        (
            "Internal error: usage limit reached; resets at 2026-10-28T15:04:00Z",
            "The usage limit for this model is used up. It resets at 2026-10-28T15:04:00Z.",
        ),
        (
            "error:\nrequest failed\nstatus 400\ncontext_length_exceeded: prompt is too long",
            "The conversation no longer fits this model's context window.",
        ),
    ],
)
def test_a_dump_naming_a_spent_allowance_or_full_window_keeps_that_meaning(
    raw: str, expected: str
) -> None:
    # The card hides Retry until the reset and offers the context action, so a
    # long or logged usage-limit error must not become the generic crash reason.
    reason, details = readable_turn_error(raw, runner="openclaw-cli")
    assert reason == expected
    assert details


def test_redact_hides_a_profile_folder_with_spaces() -> None:
    out = redact("C:/Users/First Last/proj/a.py and /home/first last/b")
    assert "Last" not in out and "last" not in out
    assert out == "~/proj/a.py and ~/b"
