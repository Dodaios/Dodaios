"""Generic, channel-agnostic confirmation phrasing for an ``ask``-tier tool run
through the two-turn confirmation flow.

Why this exists (forensic 2026-06-18, session 2995997b): an ``ask``-tier tool
(gmail send) invoked on the voice path blocks in ``ApprovalWorkflow.wait()`` for a
UI approval the voice user never gives. The 20 s no-first-frame ceiling then
beheads the working turn and Jarvis speaks the brain-timeout fallback. There is
no voice/chat path to APPROVE a consequential action today (``dodaios/speech``
never publishes ``ActionApproved``).

Instead of hanging, the brain now SPEAKS a short confirmation question on turn N
and the user's next "ja"/"nein" (classified by ``echo_confirmation.classify_
response``) resolves it on turn N+1. This module owns only the deterministic
PHRASING — no LLM call (AP-11), no I/O. The yes/no classifier is shared with the
self-mod flow (``dodaios.voice.echo_confirmation``).

Runtime Output Language doctrine: every spoken phrase table carries
de / en / es; an unrecognised tag resolves through ``DEFAULT_LOCALE`` — never an
empty string (AD-OE6 zero-silent-drop), never a per-layer hardcoded constant.
"""
from __future__ import annotations

from dodaios.core.turn_language import DEFAULT_LOCALE, normalize_language_tag
from dodaios.i18n import catalog as i18n_catalog

_PHRASE_LANGS: frozenset[str] = frozenset({"de", "en", "es", "pt"})


def _phrase_lang(language: str | None) -> str:
    """Normalize a language tag to a phrase key ("de"/"en"/"es"/"pt"), else default."""
    code = normalize_language_tag(language)
    return code if code in _PHRASE_LANGS else DEFAULT_LOCALE


# ----------------------------------------------------------------------
# Confirmation questions (End-Focus: the action sits late so an STT misshear
# is obvious to the user before they say "ja").
# ----------------------------------------------------------------------

# Tool-specific questions keyed by tool name → {lang: question}. A tool that is
# not mapped here falls back to the generic question below.
_TOOL_QUESTIONS: dict[str, dict[str, str]] = i18n_catalog.nested_table(
    "voice.tool_confirmation.tool_questions"
)

_GENERIC_QUESTION: dict[str, str] = i18n_catalog.table("voice.tool_confirmation.generic_question")


# Impact-aware questions for shell commands (explain layer, 2026-08-08): a
# non-technical user hears WHAT the command would do, not just "run that?".
# ``{commands}`` is DATA (the classified command words, e.g. "rm"), not
# re-localized phrasing — same doctrine as the failed-outcome detail below.
_IMPACT_QUESTIONS: dict[str, dict[str, str]] = i18n_catalog.nested_table(
    "voice.tool_confirmation.impact_questions"
)

_IMPACT_COMMANDS_MAX_CHARS = 60


def format_tool_confirmation(
    tool_name: str,
    *,
    language: str = "en",
    impact_level: str | None = None,
    impact_commands: str | None = None,
) -> str:
    """Render the spoken/written confirmation question for ``tool_name``.

    When the deferring tool supplied an impact classification (see
    ``describe_args`` in ``dodaios/plugins/tool/run_shell.py``), the question
    states in plain language what the command would do. An unknown
    ``impact_level`` is ignored — phrasing must never fail. Falls back to a
    tool-specific, then a generic question, and to ``DEFAULT_LOCALE`` for an
    unrecognised language tag. Never returns "".
    """
    lang = _phrase_lang(language)
    if impact_level in _IMPACT_QUESTIONS:
        template = _IMPACT_QUESTIONS[impact_level][lang]
        commands = " ".join((impact_commands or "").split())
        commands = commands[:_IMPACT_COMMANDS_MAX_CHARS].strip()
        if commands:
            return template.format(commands=commands)
        return template.replace(" ({commands})", "")
    table = _TOOL_QUESTIONS.get(tool_name)
    if table is not None and lang in table:
        return table[lang]
    return _GENERIC_QUESTION[lang]


# ----------------------------------------------------------------------
# Outcome phrasing (spoken on turn N+1 after the user answers).
# ----------------------------------------------------------------------

_OUTCOME: dict[str, dict[str, str]] = i18n_catalog.nested_table("voice.tool_confirmation.outcome")


_FAILED_DETAIL_MAX_CHARS = 160


def format_confirm_outcome(
    kind: str, tool_name: str, *, language: str = "en", detail: str | None = None
) -> str:
    """Render the outcome phrase after the user answered a confirmation.

    ``kind`` ∈ {"done", "vetoed", "timeout", "failed", "unclear"}. ``tool_name``
    is accepted for future tool-specific wording; the current phrasing is generic
    but always non-empty (AD-OE6) and covers de/en/es/pt.

    ``detail`` is appended only on ``kind="failed"``: a confirmed action that
    fails with a bare "that didn't work" gives the user nothing to correct
    with (forensic 2026-07-13 18:33 — the actionable "no MCP server named
    'github'" reason was swallowed). The detail is DATA (like a filename),
    not re-localized phrasing; it is whitespace-collapsed and bounded.
    """
    lang = _phrase_lang(language)
    table = _OUTCOME.get(kind)
    if table is None:  # unknown kind — honest, never empty
        table = _OUTCOME["failed"]
    phrase = table.get(lang, table[DEFAULT_LOCALE])
    if kind == "failed" and detail:
        cleaned = " ".join(str(detail).split())[:_FAILED_DETAIL_MAX_CHARS].strip()
        if cleaned:
            phrase = f"{phrase} {cleaned}"
    return phrase


def format_approval_unavailable(
    tool_name: str, *, language: str = DEFAULT_LOCALE
) -> str:
    """Render why a consequential action did not run when NOBODY could approve.

    Used by ``ToolExecutor`` on an unattended surface (a scheduled workflow, a
    cron run, a one-shot CLI call), where the two-turn confirmation above has
    no second turn to happen in. Deliberately a sibling of
    ``format_confirm_outcome`` over the same table: "the user said no",
    "nobody answered in time", and "there was nobody to ask" are three
    different facts, and the wording keeps them apart.

    ``tool_name`` is accepted for future tool-specific wording and is NOT
    interpolated today — a raw internal identifier ("gmail_rest") explains
    nothing to a person and has no place in a spoken line.
    """
    return format_confirm_outcome("unavailable", tool_name, language=language)
