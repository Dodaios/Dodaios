"""Fresh agent knowledge reaches a resumed vendor conversation."""

from dodaios.agent_chat.dodaios_harness import COMPACT_MAX_CHARS, Identity, society_memory_refresh
from dodaios.agent_chat.runner_cli import _REFRESH_EVERY, _with_identity
from dodaios.core.response_style import CREDENTIAL_GUIDANCE


def test_resumed_cli_gets_current_rules_memory_and_skills_without_old_transcript():
    text = (
        "## You are Scout\nResearcher\n\n"
        "## Standing instructions\nDraft only.\n\n"
        "## Your memory\nCurrent durable fact.\n\n"
        "## Learned working instructions\nCheck source dates.\n\n"
        "## Your learned skills (run one with society_run_skill)\n- verification\n\n"
        "## This conversation so far\nOLD TRANSCRIPT\n"
    )
    identity = Identity(session_id="society:scout", text=text, compact=text)
    prompt = _with_identity("Next task", identity, "vendor-session")
    for value in ["Draft only.", "Current durable fact.", "Check source dates.", "verification"]:
        assert value in prompt
    assert "OLD TRANSCRIPT" not in prompt
    assert prompt.endswith("Next task")


def test_normal_cli_sessions_keep_their_resume_behavior():
    identity = Identity(session_id="normal-chat", text="Original identity", compact="Original")
    assert _with_identity("Next task", identity, "vendor-session") == "Next task"


def test_compact_transport_retains_argv_budget_and_reports_omissions():
    output = society_memory_refresh("## Your memory\n" + "Long entry.\n" * 3000, compact=True)
    assert len(output) < COMPACT_MAX_CHARS
    assert "Omitted entries are not deletions" in output


def test_cleared_memory_explicitly_replaces_previous_snapshot():
    output = society_memory_refresh("## You are Scout\n## Your memory\nNothing remembered yet.")
    assert "Nothing remembered yet." in output
    assert "An absent section has no current entries" in output


def test_resumed_cli_gets_the_current_turn_state_without_the_contract():
    text = (
        "## You are Finn\nDiscord moderator\n\n## Standing instructions\nModerate.\n"
        "\nClient timezone for this turn: Europe/Berlin."
        "\nStored credentials: none."
    )
    identity = Identity(session_id="society:finn", text=text, compact=text)
    prompt = _with_identity("Use a token, please.", identity, "vendor-session")
    assert "Stored credentials: none." in prompt
    assert "Client timezone for this turn: Europe/Berlin." in prompt
    assert CREDENTIAL_GUIDANCE not in prompt


def test_unchanged_refresh_is_not_resent():
    text = "## You are Scout\n\n## Your memory\nA fact.\n\nStored credentials: none."
    identity = Identity(session_id="society:scout", text=text, compact=text)
    first = _with_identity("Hello.", identity, None)
    assert first.startswith("<jarvis_identity>")
    again = _with_identity("Next.", identity, "vendor-session")
    assert "<current_agent_memory>" not in again
    state = "<jarvis_turn_context>\nStored credentials: none.\n</jarvis_turn_context>"
    assert again == state + "\n\nNext."
    changed = Identity(
        session_id="society:scout", text=text.replace("A fact.", "A new fact."), compact=text
    )
    assert "A new fact." in _with_identity("Then.", changed, "vendor-session")
    assert "<current_agent_memory>" not in _with_identity("Later.", changed, "vendor-session")


def test_an_unchanged_refresh_is_resent_now_and_then():
    text = "## You are Scout\n\n## Your memory\nA fact."
    identity = Identity(session_id="society:scout", text=text, compact=text)
    _with_identity("Hello.", identity, None)
    sent = [
        "<current_agent_memory>" in _with_identity("Next.", identity, "vendor-session")
        for _ in range(_REFRESH_EVERY)
    ]
    assert sent == [False] * (_REFRESH_EVERY - 1) + [True]
