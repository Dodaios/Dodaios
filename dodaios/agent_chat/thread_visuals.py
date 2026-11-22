"""What a coding agent is told about pictures in its thread.

A coding CLI is built for a terminal, where nothing can be drawn: it explains
a flow in words, saves a chart and names the file. A thread of the Agentic
IDE draws what an answer shows:

* a fenced ``mermaid`` block as a diagram;
* a fenced ``svg`` or ``html`` block as a figure (``RenderedFence.tsx``),
  inert until the person asks for its scripts;
* a picture or a self-contained HTML page linked with image syntax, from the
  thread's folder or the computer's temp folder (``media.py``).

None of that needs a vendor's cooperation, so every CLI can use it. It only
has to know. :data:`VISUALS_GUIDE` says it: Claude Code reads it in its system
prompt (:func:`tell_claude_code`), every other CLI in front of the message,
next to the question block it is told about the same way
(``turn_prompts.ASK_PROTOCOL``).

The guide travels on the command line. Behind a Windows ``.cmd`` shim that
line is read by ``cmd.exe``: a line break ends it and ``%`` or a double quote
changes it. The guide is one paragraph without any of them; a test holds it
to that.
"""

from __future__ import annotations

from typing import Any, Final

#: The fence languages a thread draws; ``visualFenceLanguage`` in
#: ``src/lib/visualFence.ts`` reads the same names (a parity test keeps them equal).
VISUAL_FENCES: Final[tuple[str, ...]] = ("mermaid", "svg", "html")

#: The colours a visual can name instead of fixing its own, so it reads in the
#: light and the dark palette (``VISUAL_TOKENS`` in ``RenderedFence.tsx``).
VISUAL_TOKENS: Final[tuple[str, ...]] = (
    "fg",
    "muted",
    "line",
    "surface",
    "accent",
    "ok",
    "warn",
    "bad",
)

_COLOURS: Final[str] = ", ".join(f"`var(--{name})`" for name in VISUAL_TOKENS)

VISUALS_GUIDE: Final[str] = (
    "Visuals: this chat draws what you show, so explain with a picture when one says it "
    "better than a paragraph: how parts connect, a flow, a comparison, numbers, a layout. "
    "A fenced `mermaid` block is drawn as a diagram; prefer it for flows, sequences and "
    "structures. A fenced `svg` or `html` block is drawn in place as a figure instead of "
    "being shown as code: write a complete `<svg>` with a viewBox, or a self-contained "
    "HTML fragment with inline CSS, no external files, at most about 700px wide. Scripts "
    "in it run only after the person clicks, so draw with static HTML, CSS and SVG. For "
    f"colours use {_COLOURS} and set no background of your own, then it reads in light "
    "and dark; a visual with fixed colours is shown on a white page. A picture or a "
    "self-contained HTML page you saved is shown where you write `![short title](path)`: "
    "save it in the system temp folder, or in this folder when the person wants to keep "
    "it. One visual per point, after a sentence that says what it shows; never repeat "
    "its markup as text, and add none where a sentence is enough."
)

#: Claude Code's flag for text added to its system prompt.
_APPEND_FLAG: Final[str] = "--append-system-prompt"


def draws_visuals(session: Any) -> bool:
    """Whether ``session`` is a coding thread, the one place that is told the guide."""
    from dodaios.agent_chat.surface_kits import kit_for

    return bool(kit_for(str(getattr(session, "surface", "") or "agent")).turn_prompts)


def tell_claude_code(argv: list[str], session: Any) -> None:
    """Add the guide to a Claude Code thread's system prompt, in place.

    The planner may already append text (the Dodaios tools' preamble); the
    guide joins it, since the flag counts once. A turn whose prompt comes from
    a file (an assistant's identity) is no coding thread and is left alone.
    """
    if not draws_visuals(session) or "--append-system-prompt-file" in argv:
        return
    if _APPEND_FLAG in argv:
        at = argv.index(_APPEND_FLAG) + 1
        if at < len(argv) and VISUALS_GUIDE not in argv[at]:
            argv[at] = f"{argv[at]} {VISUALS_GUIDE}"
        return
    argv += [_APPEND_FLAG, VISUALS_GUIDE]


__all__ = ["VISUALS_GUIDE", "VISUAL_FENCES", "VISUAL_TOKENS", "draws_visuals", "tell_claude_code"]
