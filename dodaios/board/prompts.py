"""Prompt templates for the BioGenerator (AI profile on the Board page).

The prompt is English; the bio is written in the language passed to
``render_bio_prompt`` (the caller resolves it through the one output-language
resolver).
"""
from __future__ import annotations

from typing import Any

BIO_SYSTEM_PROMPT = """\
You are the user's personal assistant and write the short profile on the Board \
page: one paragraph of 3-5 sentences in {language}, first person ("I have been \
watching you for N days"), sharp and teasing but affectionate, aimed at \
behaviour, not flaws. Plain text: no Markdown, lists, greeting, advice or \
question; end on an observation. Use only the facts given. With a previous bio, \
say what changed since. With a cold-start note, write 2-3 tentative sentences \
ending as it says."""


BIO_USER_TEMPLATE = """CONTEXT
Observed for {days_observed} days since the first activity.

{cold_start_hint}

STATS (last 30 days):
{stats_block}

{episodes_block}{missions_block}{self_mod_block}{previous_bio_block}{feedback_vector_block}"""


# ----------------------------------------------------------------------
# Renderer
# ----------------------------------------------------------------------

def render_bio_prompt(facts: dict[str, Any], *, language: str = "English") -> tuple[str, str]:
    """Builds (system_prompt, user_prompt) from the facts.

    Returns a tuple so the caller can place both parts separately into a
    ``BrainRequest`` (system + messages[BrainMessage]). ``language`` is the
    English name of the language the bio is written in.

    Fields in the ``facts`` dict (all optional):

    - ``days_observed``      : int   — days since the first activity data row.
    - ``top_tools``          : list  — tool names sorted by days used.
    - ``tasks_completed``    : int
    - ``tasks_failed``       : int
    - ``voice_first_try_rate``: float | None
    - ``peak_hour``          : int | None
    - ``streak_days``        : int
    - ``episodes``           : list[str]    — top-3 salience-weighted awareness episodes.
    - ``missions``           : dict | None  — keys ``approved``, ``failed``, ``aborted``, ``open_overdue``.
    - ``self_mod``           : dict[str,int] | None — path → number of mutations.
    - ``previous_bio``       : str   — full text of the previous bio (or "").
    - ``feedback_vector``    : dict[str,int] — counts from the last 4 weeks.
    - ``memory_excerpt``     : str   — short MEMORY.md excerpt.
    - ``soul_excerpt``       : str   — short SOUL.md excerpt.

    Missing fields are silently resolved to empty blocks — the LLM simply
    sees less context. No crash, no null values in the prompt.
    """
    days_observed = int(facts.get("days_observed", 0) or 0)

    user_prompt = BIO_USER_TEMPLATE.format(
        days_observed=days_observed,
        cold_start_hint=_render_cold_start(days_observed),
        stats_block=_render_stats(facts),
        episodes_block=_render_episodes(facts.get("episodes")),
        missions_block=_render_missions(facts.get("missions")),
        self_mod_block=_render_self_mod(facts.get("self_mod")),
        previous_bio_block=_render_previous_bio(facts.get("previous_bio", "")),
        feedback_vector_block=_render_feedback(facts.get("feedback_vector")),
    )
    return BIO_SYSTEM_PROMPT.format(language=language), user_prompt


# ----------------------------------------------------------------------
# Block renderers
# ----------------------------------------------------------------------

def _render_cold_start(days_observed: int) -> str:
    if days_observed >= 7:
        return ""
    remaining = max(1, 7 - days_observed)
    return (
        f"COLD START: you have known the user for {days_observed} days. "
        f"End with: More in {remaining} {'day' if remaining == 1 else 'days'}.\n"
    )


def _render_stats(facts: dict[str, Any]) -> str:
    lines = [
        f"- Top tools: {_fmt_tools(facts.get('top_tools'))}",
        f"- Tasks: {_fmt_ratio(facts.get('tasks_completed', 0), facts.get('tasks_failed', 0))}",
        f"- Voice first-try rate: {_fmt_rate(facts.get('voice_first_try_rate'))}",
        f"- Most active hour: {_fmt_peak(facts.get('peak_hour'))}",
        f"- Streak: {facts.get('streak_days', 0)} days",
    ]
    memory = _excerpt(facts.get("memory_excerpt", ""), 300)
    soul = _excerpt(facts.get("soul_excerpt", ""), 300)
    if memory and memory != "—":
        lines.append(f"- MEMORY excerpt: {memory}")
    if soul and soul != "—":
        lines.append(f"- SOUL excerpt: {soul}")
    return "\n".join(lines)


def _render_episodes(episodes: Any) -> str:
    if not episodes:
        return ""
    if not isinstance(episodes, list):
        return ""
    items = [str(e).strip() for e in episodes if str(e).strip()][:3]
    if not items:
        return ""
    body = "\n".join(f"- {item[:200]}" for item in items)
    return f"\nEPISODES (last 7 days, top 3):\n{body}\n"


def _render_missions(missions: Any) -> str:
    if not isinstance(missions, dict):
        return ""
    approved = int(missions.get("approved", 0) or 0)
    failed = int(missions.get("failed", 0) or 0)
    aborted = int(missions.get("aborted", 0) or 0)
    overdue = missions.get("open_overdue") or []
    if approved + failed + aborted == 0 and not overdue:
        return ""
    parts = [
        "\nMISSIONS (last 30 days):",
        f"- Done: {approved} | Failed: {failed} | Aborted: {aborted}",
    ]
    if overdue:
        previews = ", ".join(str(t)[:60] for t in overdue[:3])
        parts.append(f"- Open for over 7 days: {previews}")
    return "\n".join(parts) + "\n"


def _render_self_mod(self_mod: Any) -> str:
    if not isinstance(self_mod, dict) or not self_mod:
        return ""
    items = sorted(self_mod.items(), key=lambda kv: -int(kv[1]))
    body = ", ".join(f"{path}: {count}x" for path, count in items[:6])
    return f"\nCONFIG CHANGES (last 7 days): {body}\n"


def _render_previous_bio(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    snippet = text[:600] + ("..." if len(text) > 600 else "")
    return f"\nPREVIOUS BIO:\n\"{snippet}\"\n"


def _render_feedback(feedback: Any) -> str:
    if not isinstance(feedback, dict) or not feedback:
        return ""
    # ``trifft`` / ``trifft_nicht`` / ``haerter`` are the API/DB keys.
    trifft = int(feedback.get("trifft", 0) or 0)
    trifft_nicht = int(feedback.get("trifft_nicht", 0) or 0)  # i18n-allow: API/DB key
    haerter = int(feedback.get("haerter", 0) or 0)
    if trifft + trifft_nicht + haerter == 0:  # i18n-allow: same API/DB contract identifiers
        return ""
    parts = [
        "\nFEEDBACK (last 4 weeks): "
        f"on point {trifft} | off {trifft_nicht} | asked sharper {haerter}"
    ]
    if haerter > 0:
        parts.append("- TONE: SHARPER. Lower the politeness threshold, keep to the facts.")
    if trifft_nicht > trifft:  # i18n-allow: API/DB contract identifiers
        parts.append(
            "- TONE: past character reads missed. Stay closer to the data, interpret less."
        )
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------------
# Stat formatters (carried over from the old implementation)
# ----------------------------------------------------------------------

def _fmt_tools(tools: Any) -> str:
    if not tools:
        return "— (no tool use yet)"
    if isinstance(tools, list):
        return ", ".join(str(t) for t in tools[:8])
    return str(tools)


def _fmt_ratio(completed: int, failed: int) -> str:
    completed = int(completed or 0)
    failed = int(failed or 0)
    if completed + failed <= 0:
        return "— (no tasks yet)"
    return f"{completed} ok / {failed} fail"


def _fmt_rate(rate: float | None) -> str:
    if rate is None:
        return "— (too little data)"
    return f"{int(round(float(rate) * 100))} %"


def _fmt_peak(hour: int | None) -> str:
    if hour is None:
        return "— (too little data)"
    return f"{int(hour):02d}:00"


def _excerpt(text: str, max_chars: int) -> str:
    if not text:
        return "—"
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"
