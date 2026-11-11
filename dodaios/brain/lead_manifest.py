"""The lead's capability manifest: one definition of what the lead can do on every seat.

The lead (the person's one assistant, surface ``jarvis``) is reached three ways:
typed on a brain seat (an API model running Dodaios' own tool loop), typed on a
CLI seat (a vendor CLI whose hands are this app's MCP server) and by voice (a
live model with the gateway's tools). Before this manifest each seat had its own
list, and what the lead could do changed silently with the model picker.

The rule now: the lead's tools are ONE set, built in one place
(``BrainSupervisorToolGateway.lead_tools`` plus the session-bound hands), and
every seat gets it. A tool may be missing from a seat only when it is named here
with its reason:

* ``VOICE_ONLY_TOOLS``: primitives that only make sense inside a live call
  (screen, speech, the call's own notes). The typed lead never gets them.
* ``VOICE_SUPERSEDED_TOOLS``: the other direction. The live model operates the
  screen through ``computer`` (ADR-0039), so a voice call does not get the
  mission vehicle or the raw coordinate primitives the typed lead has.
* ``LEAD_ONLY_TOOLS``: read tools a live call replaces with a native one.
* ``BRAIN_SEAT_ONLY_TOOLS``: a brain seat has no file hands of its own and gets
  the folder tools; a CLI seat uses the vendor's file tools in the chat's folder.

``tests/unit/brain/test_lead_manifest_parity.py`` fails when the seats drift.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

#: Voice-only primitives, with why the typed lead does not get each one.
VOICE_ONLY_TOOLS: Final[Mapping[str, str]] = {
    "computer": "ADR-0039: the live model's own screen operator",
    "screen_snapshot": "a live call looks at the screen; a typed turn has Screen Context",
    "take_appshot": "the appshot shortcut's capture, with its effect and sound, in a call",
    "show_on_screen": "a voice says the takeaway and shows the exact content; typed is on screen",
    "update_soul": "the live model keeps SOUL.md current in a call; typed turns have the review",
    "remember": "a spoken 'remember this'; typed turns have the memory vault and the review",
}

#: What a live call does not get because it operates the screen through ``computer``
#: (ADR-0039): a second model's mission, and coordinate primitives in units the
#: live model never sees. The typed lead keeps them.
VOICE_SUPERSEDED_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "computer_use",
        "computer-use",
        "dispatch_to_harness",
        "dispatch-to-harness",
        "click",
        "move_mouse",
        "drag",
        "scroll",
        "type_text",
        "hotkey",
        "screenshot",
    }
)

#: Tools only the typed lead has: a read a live call answers with a native one
#: (``task_status``), and a card that needs a chat.
LEAD_ONLY_TOOLS: Final[Mapping[str, str]] = {
    "work_board": "the voice call's native task_status answers the same question",
    "society_request_connect": "the Connect card needs a chat to show it in",
    "request_browser_takeover": "the takeover card needs a chat to show it in",
    "team_thread": "a typed lead starts and steers team threads; a call hands that to the chat",
    "costs_summary": "a typed lead answers spend questions; a call opens the Costs section",
    "artifacts": "a typed lead lists and reads what the agents made; a call shows it on screen",
}

#: The folder tools: a brain seat's file hands. A CLI seat uses the vendor's own
#: file tools, which act in the chat's working folder.
BRAIN_SEAT_ONLY_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "Read",
        "Write",
        "Edit",
        "Ls",
        "Glob",
        "Grep",
        "RunCommand",
    }
)

#: The ambient-pane prompt tools pick a pane the model never named. The lead
#: addresses a pane by its stable id through ``workspace-orchestrate`` instead.
LEAD_DROPPED_TOOLS: Final[frozenset[str]] = frozenset({"agentic-ide-prompt", "agentic-ide-fanout"})

#: The delegation tools the lead has on every seat. A worker or a society seat
#: never gets them (a spawn vehicle there would start a worker that starts
#: another one, AP-5/AP-14). The older vehicles (``multi-spawn``,
#: ``dispatch-with-review``, ``dispatch-to-harness``, ``dispatch-to-admin``,
#: ``spawn-subagents``) stay withheld from every chat on purpose: the router set
#: leaves them out (``brain/factory.py``), and the CLI seat must not offer more
#: than the brain seat.
LEAD_SPAWN_TOOLS: Final[frozenset[str]] = frozenset({"spawn-worker", "spawn_worker"})


@dataclass(frozen=True)
class LeadCapabilityManifest:
    """The explicit exceptions between the lead's seats."""

    voice_only: Mapping[str, str]
    voice_superseded: frozenset[str]
    lead_only: Mapping[str, str]
    brain_seat_only: frozenset[str]
    dropped: frozenset[str]
    spawn_tools: frozenset[str]

    def expected_lead_from_voice(
        self, voice: Iterable[str], live: Iterable[str] = ()
    ) -> frozenset[str]:
        """The lead's tool names, derived from the voice set.

        The voice set minus what is voice-only, plus what only the typed lead
        has (``lead_only``, and the live tools a call supersedes).
        """
        names = set(voice) - set(self.voice_only)
        names |= {n for n in self.lead_only}
        names |= {n for n in live if n in self.voice_superseded}
        # A call drops every ``agentic-ide-*`` tool for ``workspace-orchestrate``; the lead
        # keeps the read ones (status, list) and drops only the ambient-pane prompt tools.
        names |= {n for n in live if n.startswith("agentic-ide-") and n not in self.dropped}
        return frozenset(names)


LEAD_MANIFEST: Final[LeadCapabilityManifest] = LeadCapabilityManifest(
    voice_only=VOICE_ONLY_TOOLS,
    voice_superseded=VOICE_SUPERSEDED_TOOLS,
    lead_only=LEAD_ONLY_TOOLS,
    brain_seat_only=BRAIN_SEAT_ONLY_TOOLS,
    dropped=LEAD_DROPPED_TOOLS,
    spawn_tools=LEAD_SPAWN_TOOLS,
)

__all__ = [
    "BRAIN_SEAT_ONLY_TOOLS",
    "LEAD_DROPPED_TOOLS",
    "LEAD_MANIFEST",
    "LEAD_ONLY_TOOLS",
    "LEAD_SPAWN_TOOLS",
    "VOICE_ONLY_TOOLS",
    "VOICE_SUPERSEDED_TOOLS",
    "LeadCapabilityManifest",
]
