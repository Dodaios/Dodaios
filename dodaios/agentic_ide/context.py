"""The context block that turns focus mode into an actual coding mode.

When the user flips the Agentic IDE into focus mode, every turn should be
answered *inside* the open workspace: Jarvis should know which folder is open,
what kind of codebase it is, which skills that repo defines, which agents are
running in which pane, and what each of them last printed. Without that, "is T2
stuck?" is unanswerable and the assistant guesses — the failure mode this block
exists to prevent.

Two things live here, and the distinction matters:

* **A role directive.** Focus mode is not a hint, it is a different assistant:
  an agentic-coding partner for this one repository. It plans work with the
  user, decides which pane should do what, and hands the work over — it does not
  do the coding itself and does not start invisible background agents. Stating
  that explicitly is what stopped the live 2026-07-25 failure, where "let Kai do
  a deep dive" dispatched a background mission while Kai sat idle. The
  deterministic guards (``intent.owns_turn``, consulted by the router's
  force-spawn check and the spawn gate) are the enforcement; this text is what
  makes the model *want* the right thing in the first place, so a phrasing the
  regex misses still lands correctly.
* **The facts.** Folder, stack, branch, panes, and what each pane last printed.

Cost discipline (AP-9 / AP-26): building the block touches nothing but
in-memory state — the session's cached project profile and each terminal's ring
buffer. No disk read, no subprocess, no network. The project profile was
computed ONCE when the session started, precisely so this path stays free.
"""

from __future__ import annotations

import time

# Per-terminal output shown in the block. Enough to say what an agent is doing,
# small enough that ten panes do not crowd out the conversation. Past
# _CROWDED_AT panes the per-pane share shrinks: the block is hard-capped at
# _MAX_CHARS, and six lines each meant the cap silently dropped the LAST panes
# entirely — three lines each keeps every pane visible AND costs fewer of the
# ~1 100 uncacheable input tokens this block adds to every turn.
_LINES_PER_TERMINAL = 6
_LINES_PER_TERMINAL_CROWDED = 3
_CROWDED_AT = 5
_MAX_CHARS = 4500

_HEADER = (
    "[AGENTIC IDE — focused coding mode is ON]\n"
    "The user is coding in the repository below with agents in terminals T1, T2, ... "
    "(grid order, left to right). To instruct a terminal, call agentic-ide-prompt with "
    "the user's words whole, every constraint and file included; a prompt writer that "
    "has read the repo builds the brief, so do not summarise or rewrite. To see what an "
    "agent did, call agentic-ide-terminal-report. A pane marked STILL BEING WRITTEN has "
    "received nothing yet. Name the terminal in your answer (\"T2 is on it\"). No "
    "background workers for terminal work.\n"
    "Live workspace state:"
)


def _terminal_block(  # noqa: ANN001 - Terminal, avoid import cycle
    term,
    tail_lines: int = _LINES_PER_TERMINAL,
    *,
    writing_for_s: float | None = None,
) -> list[str]:
    status = term.status
    bits = [f"{term.name} ({term.display_name}) — {status}"]
    if writing_for_s is not None:
        # Stated before the receipt count on purpose: the counted prompts are
        # what the model turned into "I have prompted T5" while this one was
        # still being written (live 2026-08-13 11:20:12).
        bits.append(
            f"A BRIEF IS STILL BEING WRITTEN for it ({int(writing_for_s)}s so "
            f"far) — nothing has reached {term.name} yet"
        )
    if status == "live" and term.last_output_at:
        idle = max(0, int(time.time() - term.last_output_at))
        bits.append(f"last output {idle}s ago")
    if status == "exited" and term.exit_code is not None:
        bits.append(f"exit code {term.exit_code}")
    if status == "error" and term.error:
        bits.append(term.error)
    if term.prompts_sent:
        bits.append(f"{term.prompts_sent} prompt(s) sent from Dodaios")
    lines = [f"- {', '.join(bits)}"]
    if term.last_prompt:
        lines.append(f'  last prompt sent: "{term.last_prompt[:200]}"')
    tail = term.transcript.tail(tail_lines)
    if tail:
        lines.append("  recent output:")
        lines.extend(f"    {line[:200]}" for line in tail)
    return lines


def focus_context_block(max_chars: int = _MAX_CHARS) -> str:
    """Workspace-awareness block for this turn, or "" when focus mode is off."""
    try:
        from .session import get_registry

        session = get_registry().session
    except Exception:  # noqa: BLE001 - never let awareness break a turn
        return ""
    if session is None or not session.focus_mode:
        return ""

    parts: list[str] = [_HEADER, ""]
    parts.extend(session.profile.summary_lines())
    parts.append("")
    visible = session.contextual_terminal()
    if visible is not None:
        parts.append(
            f"Chat view is on screen with {visible.name} as the one visible terminal. "
            f"Deictic references such as 'this terminal', 'the terminal here', "
            f"or 'what is it doing?' mean {visible.name}, unless the user "
            "explicitly names another call-sign."
        )
        parts.append("")
    if session.terminals:
        tail_lines = (
            _LINES_PER_TERMINAL
            if len(session.terminals) < _CROWDED_AT
            else _LINES_PER_TERMINAL_CROWDED
        )
        # Which panes have a brief ON THE WAY. The one workspace fact that
        # exists nowhere else: a pane with a 20 s composition running looks
        # exactly like an idle pane that was prompted an hour ago, and the model
        # answered from the older receipt.
        try:
            from .fanout import in_flight_briefs

            writing = dict(in_flight_briefs(session))
        except Exception:  # noqa: BLE001 - a missing fact never costs the block
            writing = {}
        parts.append(f"Terminals in this workspace ({len(session.terminals)}):")
        for term in session.terminals:
            parts.extend(_terminal_block(term, tail_lines, writing_for_s=writing.get(term.name)))
    else:
        parts.append("No terminals are open in this workspace yet.")

    block = "\n".join(parts)
    if len(block) > max_chars:
        block = block[: max_chars - 1] + "…"
    return block


__all__ = ["focus_context_block"]
