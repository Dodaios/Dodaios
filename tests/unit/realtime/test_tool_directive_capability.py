"""The delegate tool directive must match the transport's real capabilities.

A transport that cannot receive tool declarations (``supports_direct_tools``
False, e.g. ChatGPT-Live through the Codex app-server) must never be promised
a callable ``jarvis_action`` or ``end_call``: the model can only "comply" by
speaking the call, which a live session shows as the assistant voicing
"Could you look up the weather…" as its own answer. Capability decides the
wording (AP-21), never a provider name.
"""

from __future__ import annotations

from types import SimpleNamespace

import dodaios.realtime.session as session_mod


def _bare_session(provider: object) -> session_mod.RealtimeVoiceSession:
    """A session shell carrying exactly what ``_tool_directive`` reads."""
    session = session_mod.RealtimeVoiceSession.__new__(
        session_mod.RealtimeVoiceSession
    )
    session._delegate_enabled = True
    session._tool_bridge = None
    session._provider = provider
    return session


def test_handoff_variant_never_promises_a_callable_function() -> None:
    for text in (
        session_mod._DELEGATE_ROLE_DIRECTIVE_HANDOFF,
        session_mod._DELEGATE_DISCOURAGED_DIRECTIVE_HANDOFF,
    ):
        assert "jarvis_action" not in text
        assert "end_call" not in text
        assert "handoff" in text.lower()


def test_handoff_variant_keeps_the_load_bearing_rules() -> None:
    text = session_mod._DELEGATE_ROLE_DIRECTIVE_HANDOFF
    # The routing and honesty rules survive the mechanism swap; the
    # announcement ban lives once in the shared voice contract.
    assert "request a handoff" in text.lower()
    assert "general knowledge and chat yourself" in text.lower()
    assert "claim you lack access" in text.lower()
    assert "Never announce an action" in session_mod._session_instructions(
        "en", tool_directive=text
    )


def test_capability_limited_provider_gets_the_handoff_directive() -> None:
    limited = SimpleNamespace(supports_direct_tools=False)
    directive = _bare_session(limited)._tool_directive()
    assert directive.startswith(session_mod._DELEGATE_ROLE_DIRECTIVE_HANDOFF)
    assert "jarvis_action" not in directive

    directive = _bare_session(limited)._tool_directive(delegate_discouraged=True)
    assert directive.startswith(session_mod._DELEGATE_ROLE_DIRECTIVE_HANDOFF)
    assert directive.endswith(session_mod._DELEGATE_DISCOURAGED_DIRECTIVE_HANDOFF)
    assert "jarvis_action" not in directive


def test_direct_tool_provider_keeps_the_function_directive() -> None:
    capable = SimpleNamespace(supports_direct_tools=True)
    directive = _bare_session(capable)._tool_directive()
    assert directive.startswith(session_mod._DELEGATE_ROLE_DIRECTIVE)
    assert "jarvis_action" in directive


def test_open_probes_the_candidate_provider_not_the_last_active_one() -> None:
    """During ``_open`` the directive must follow the provider being opened."""
    active_capable = SimpleNamespace(supports_direct_tools=True)
    candidate_limited = SimpleNamespace(supports_direct_tools=False)
    session = _bare_session(active_capable)
    directive = session._tool_directive(provider=candidate_limited)
    assert directive.startswith(session_mod._DELEGATE_ROLE_DIRECTIVE_HANDOFF)
    assert "jarvis_action" not in directive
