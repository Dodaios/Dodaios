"""Acknowledgment-text generator for the perceived-latency-reduction pattern.

Hauptjarvis emits a brief, task-specific spoken ack the moment it has decided
on a tool call so the user hears something within ~200ms instead of waiting
through the full reasoning + tool-execution roundtrip in silence. The
substantive answer follows after the tool finishes.

Design constraints:

* **No LLM call.** Phrases are deterministic pool lookups + one random pick.
  Render time must stay well under one millisecond, otherwise the latency
  win is gone.
* **Varied, never robotic.** Every tool family carries a POOL of phrase
  variants per language and a process-wide no-repeat memory
  (:class:`AckPhrasePicker`) guarantees consecutive acks never sound
  identical — the 2026-07-05 forensic finding was the same one-word
  German ack spoken three times in one session (once per utterance).
* **Tool-family-specific.** Per-tool handlers extract the most informative
  arg (search query, app name, skill name, CLI service) into the ack so the
  user knows the right intent was understood — generic "okay, one moment"
  variants only as fallback for tools whose args are too noisy to echo
  (raw shell commands, long harness tasks).
* **Skip-list.** Passive state reads (screen-snapshot,
  wiki lookups) and low-latency individual UI events (click, hotkey,
  type-text) return ``None`` because a chat-style ack would chatter or feel
  uncanny.
* **Trilingual de/en/es.** Language is picked per request from the resolved
  turn language; every pool exists for all three supported languages
  (runtime-output-language doctrine). User strings stay in their natural
  form (German with real umlauts) — only the surrounding code is English
  per the project's output-language policy.

Companion functions ``final_summary_marker`` and ``should_prepend_marker``
support the second half of the pattern: a short completion marker
prepended to the final response, unless the brain already self-confirmed.

.. note:: The phrase strings in this module are runtime voice/TTS product
   content (multilingual product surface). German lines carry inline
   ``i18n-allow`` markers.
"""
from __future__ import annotations

import random
import re
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from dodaios.i18n import catalog as i18n_catalog

__all__ = [
    "ACK_SKIP_TOOLS",
    "AckPhrasePicker",
    "describe_tool_action",
    "final_summary_marker",
    "generate_ack",
    "is_voice_control_utterance",
    "should_prepend_marker",
]


# Utterance-level skip patterns. Even if the brain decides to fire a tool
# call for one of these, the ack must stay silent — the user explicitly
# asked for these categories to be exempted in the dropdown spec, and the
# action itself (volume change, playback pause) is the confirmation.
#
# Kept as a module-level frozenset so the cost is one set lookup per match.
# Patterns cover: volume, stop/pause, mute. Bilingual de/en.
_VOICE_CONTROL_PATTERN = re.compile(
    # Full-match style: the entire utterance must be a voice-control command,
    # allowing only trailing politeness modifiers ("bitte", "mal", "jetzt",
    # "please") and punctuation. This stops narrative phrases like the German
    # "lauter Applaus war zu hoeren" ("loud applause could be heard") or
    # "still im Gespraech" ("quiet in conversation") from triggering.  # i18n-allow: quoted German input example
    r"^\s*(?:"
    # German
    r"(?:mach\s+)?(?:lauter|leiser|laut|leise)(?:\s+machen)?"
    r"|sei\s+(?:bitte\s+)?(?:still|leise|stiller)"
    r"|halt(?:\s+(?:die\s+)?klappe)?"
    r"|stop(?:p)?(?:\s+(?:sprechen|reden|talking))?"
    r"|pause(?:\s+(?:die\s+)?(?:wiedergabe|musik|sprache))?"  # i18n-allow: German voice-control input vocabulary, matched against the user's utterance
    r"|pausier(?:e|en|t)?"
    r"|stumm(?:\s+schalten)?"
    r"|schweig(?:e|en)?"
    r"|nicht\s+(?:so\s+)?(?:laut|leise)"  # i18n-allow: German voice-control input vocabulary
    # English
    r"|(?:be\s+)?quiet"
    r"|shut\s+up"
    r"|louder|quieter|softer"
    r"|volume\s+(?:up|down)"
    r"|(?:please\s+)?stop(?:\s+(?:speaking|talking))?"
    r"|mute(?:\s+yourself)?"
    r")"
    # Optional trailing politeness / acknowledgment modifier
    r"(?:\s+(?:bitte|mal|jetzt|please|now|please\s+now))?"
    # Possessive tail: ``\s*[!.?]?\s*`` let the engine try every split of a
    # long blank run before failing (CodeQL py/polynomial-redos). Same language.
    r"\s*+[!.?]?+\s*+$",
    re.IGNORECASE,
)


def is_voice_control_utterance(utterance: str | None) -> bool:
    """True if the utterance is a Voice-Control command (skip-category 3).

    These bypass the ack pattern entirely — the spec is explicit that
    "lauter / leiser / stop / pause" must not get a spoken ack because
    the action itself is the confirmation. Pure regex match, no LLM call.
    """
    if not utterance:
        return False
    return bool(_VOICE_CONTROL_PATTERN.match(utterance.strip()))

# Tools that must NOT emit an ack. Two reasons:
#   (a) Passive state reads — there is no user-visible action to confirm,
#       and the fast ones (wiki lookup: ~70 ms) would ack a sub-100 ms read.
#   (b) Low-latency individual UI events — a per-event chat ack would
#       generate dozens of TTS interruptions during a single keypress
#       sequence (type-text streams characters; click is single-pixel).
ACK_SKIP_TOOLS: frozenset[str] = frozenset({
    # passive observations
    "screen_snapshot",
    "whoami",
    # looking up which tool to use is not something to announce
    "find_tools",
    # fast passive memory reads (2026-07-06: wiki-recall answered in 72 ms —
    # a spoken "one moment" for that is pure chatter)
    "wiki_recall",
    "wiki_search",
    # low-latency UI events
    "click",
    "hotkey",
    "move_mouse",
    "type_text",
    # silent meta tools (Phase 7.3 read-only)
    "list_mutable_settings",
    "get_config_value",
})

_FINAL_MARKERS: dict[str, str] = i18n_catalog.table("brain.ack.final_markers")

# A brain text that already opens with one of these is treated as
# self-confirming, so we don't double up with "Erledigt. Okay, ..."
_ALREADY_CONFIRMING_RE = re.compile(
    r"^\s*(erledigt|fertig|okay|ok|alright|done|got\s+it|verstanden|in\s+ordnung|sure)\b",  # i18n-allow: bilingual (de/en) self-confirmation matching data, checked against generated brain text
    re.IGNORECASE,
)


class AckPhrasePicker:
    """Phrase selection with a short no-repeat memory.

    The 2026-07-05 forensic complaint was not "an ack existed" but "the SAME
    ack, three times in a row". The picker keeps the last few spoken phrases
    (global across tool families — repetition is the irritant regardless of
    family) and never picks one of them again while an alternative exists.
    A pool smaller than the memory still always yields a phrase (falls back
    to the full pool), so the ack can never be silenced by its own memory.

    Phrase variety, not cryptography — ``random.choice`` is deliberate.
    """

    def __init__(self, memory: int = 4) -> None:
        self._recent: deque[str] = deque(maxlen=memory)

    def pick(self, pool: Sequence[str]) -> str:
        """Return one phrase from ``pool``, avoiding the most recent picks.

        Guarantee: for any pool with at least two entries, two CONSECUTIVE
        picks are never identical — when the whole pool sits in memory (pool
        smaller than the memory), the fallback still excludes the very last
        pick before resorting to the full pool.
        """
        last = self._recent[-1] if self._recent else None
        candidates = (
            [p for p in pool if p not in self._recent]
            or [p for p in pool if p != last]
            or list(pool)
        )
        choice = random.choice(candidates)  # noqa: S311 — variety, not security
        self._recent.append(choice)
        return choice


# Process-wide default memory: consecutive utterances in one session share it,
# which is exactly the scope of the "three identical acks in a row" bug.
_DEFAULT_PICKER = AckPhrasePicker()


def _normalize_tool_name(name: str) -> str:
    """Tool calls arrive as either 'dispatch-to-harness' or 'dispatch_to_harness'.

    Internally we key everything off the underscore form; this normalizes
    both spellings + lowercases + strips whitespace.
    """
    return (name or "").replace("-", "_").lower().strip()


def _normalize_language(language: str | None) -> str:
    """Reduce any language hint to a supported code ('de', 'en', 'es' or 'pt').

    The caller resolves the authoritative turn language through the ONE
    resolver (dodaios/core/turn_language.py) and passes a concrete code, so
    'es'/'pt' must survive here — collapsing them to another language would
    flip a Spanish turn's ack (a runtime-output-language doctrine violation).
    Anything unrecognised falls back to English (``DEFAULT_LOCALE``), the one
    fallback language of every system phrase.
    """
    from dodaios.core.turn_language import normalize_language_tag
    from dodaios.i18n import phrase_locale

    return phrase_locale(normalize_language_tag(language))


def _trim_to_words(text: str, max_chars: int) -> str:
    """Trim ``text`` to ``max_chars`` at the nearest word boundary, ellipsizing."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",;:.")
    return cut + "..."


# ---------------------------------------------------------------------------
# Phrase pools
# ---------------------------------------------------------------------------
#
# Every entry: language code -> tuple of variants. All three supported
# languages are present in every pool (runtime-output-language doctrine).
# German strings are runtime voice product content (i18n-allow). Phrases are
# promissory ("I'm on it"), never completion claims — the tool has not run yet.

_GENERIC_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.generic_ack")

_SHELL_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.shell_ack")

# {service} is interpolated with a human-readable CLI service name
# (cli_gh -> "GitHub"). See _CLI_SERVICE_NAMES / _cli_pool.
_CLI_SERVICE_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table(
    "brain.ack.cli_service_ack"
)

# Human service names for cli_<name> tools. Unknown suffixes are title-cased
# ("cli_foo_bar" -> "Foo Bar") — still informative, never wrong.
_CLI_SERVICE_NAMES: dict[str, str] = {
    "aws": "AWS",
    "az": "Azure",
    "docker": "Docker",
    "firebase": "Firebase",
    "fly": "Fly.io",
    "gcloud": "Google Cloud",
    "gh": "GitHub",
    "github": "GitHub",
    "kubectl": "Kubernetes",
    "netlify": "Netlify",
    "npm": "npm",
    "railway": "Railway",
    "stripe": "Stripe",
    "supabase": "Supabase",
    "vercel": "Vercel",
}

_HARNESS_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.harness_ack")

_SEARCH_TOPIC_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table(
    "brain.ack.search_topic_ack"
)

_SEARCH_GENERIC_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table(
    "brain.ack.search_generic_ack"
)

_MULTI_SPAWN_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table(
    "brain.ack.multi_spawn_ack"
)

_OPEN_APP_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.open_app_ack")

_RUN_SKILL_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.run_skill_ack")

_GMAIL_READ_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.gmail_read_ack")

_CALENDAR_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.calendar_ack")

_REMEMBER_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.remember_ack")

_VERIFY_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.verify_ack")

_SERVER_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.server_ack")

_SET_CONFIG_ACK: dict[str, tuple[str, ...]] = i18n_catalog.variant_table("brain.ack.set_config_ack")


# ---------------------------------------------------------------------------
# Per-tool pool handlers
# ---------------------------------------------------------------------------
#
# Each handler takes the tool's arg dict + the resolved language code and
# returns a tuple of candidate phrases. Handlers must never raise — the
# dispatcher falls back to ``_GENERIC_ACK`` on any exception, so a broken
# template never silences the ack entirely.

def _interpolate(pool: tuple[str, ...], **kwargs: Any) -> tuple[str, ...]:
    """Format every variant in ``pool`` with ``kwargs``."""
    return tuple(p.format(**kwargs) for p in pool)


def _ack_dispatch_harness(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    return _HARNESS_ACK[lang]


def _ack_run_shell(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    return _SHELL_ACK[lang]


def _ack_search_web(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    query = str(args.get("query") or args.get("q") or "").strip()
    # Echo the topic only when it is topic-shaped (short, few words) — a full
    # question sentence read back sounds robotic.
    if query and len(query) <= 40 and len(query.split()) <= 4:
        topic = _trim_to_words(query, 40)
        return _interpolate(_SEARCH_TOPIC_ACK[lang], topic=topic)
    return _SEARCH_GENERIC_ACK[lang]


def _ack_spawn_sub_jarvis(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    # Sub-Jarvis spawns are the exact case the user complained about ("silent
    # pause before a long answer"). Keep the ack short and warm.
    return _HARNESS_ACK[lang]


def _ack_multi_spawn(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    tasks = args.get("tasks") or args.get("jobs") or []
    n = len(tasks) if isinstance(tasks, (list, tuple)) else 0
    if n >= 2:
        return _interpolate(_MULTI_SPAWN_ACK[lang], n=n)
    return _GENERIC_ACK[lang]


def _ack_open_app(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    app = str(
        args.get("app") or args.get("app_name") or args.get("name") or ""
    ).strip()
    if app and len(app) <= 30:
        return _interpolate(_OPEN_APP_ACK[lang], app=app)
    return _GENERIC_ACK[lang]


def _ack_run_skill(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    skill = str(
        args.get("skill") or args.get("skill_name") or args.get("name") or ""
    ).strip()
    if skill and len(skill) <= 40:
        return _interpolate(_RUN_SKILL_ACK[lang], skill=skill)
    return _GENERIC_ACK[lang]


def _ack_gmail(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    # Grounded per-tool ack for the email plugin (the user's slow-plugin
    # example). Action-aware so a SEND is not mis-announced as a read: a
    # ``send_message`` still goes through echo-confirmation, so it gets a
    # neutral filler, while reads get the specific "checking your mail" pool.
    action = str(args.get("action") or "list_messages").strip()
    if action == "send_message":
        return _GENERIC_ACK[lang]
    return _GMAIL_READ_ACK[lang]


def _ack_google_calendar(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    return _CALENDAR_ACK[lang]


def _ack_remember(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    return _REMEMBER_ACK[lang]


def _ack_verify(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    return _VERIFY_ACK[lang]


def _ack_start_preview_server(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    return _SERVER_ACK[lang]


def _ack_set_config(args: Mapping[str, Any], lang: str) -> tuple[str, ...]:
    return _SET_CONFIG_ACK[lang]


_TemplateFn = Callable[[Mapping[str, Any], str], tuple[str, ...]]

_TEMPLATES: dict[str, _TemplateFn] = {
    "dispatch_to_harness": _ack_dispatch_harness,
    "dispatch_with_review": _ack_dispatch_harness,
    "run_shell": _ack_run_shell,
    "search_web": _ack_search_web,
    "spawn_sub_jarvis": _ack_spawn_sub_jarvis,
    "multi_spawn": _ack_multi_spawn,
    "open_app": _ack_open_app,
    "run_skill": _ack_run_skill,
    "gmail": _ack_gmail,
    "google_calendar": _ack_google_calendar,
    "remember": _ack_remember,
    "verify_via_curl": _ack_verify,
    "verify_localhost": _ack_verify,
    "start_preview_server": _ack_start_preview_server,
    "set_config_value": _ack_set_config,
    # the generic CLI entry shares the shell-like content-free pool
    "cli_tools": _ack_run_shell,
}


def _cli_pool(norm_tool: str, lang: str) -> tuple[str, ...]:
    """Informative pool for a ``cli_<name>`` tool, naming the service.

    ``cli_gh`` resolves to "GitHub"; unknown suffixes are title-cased so the
    ack still names SOMETHING recognizable instead of a bare "one moment".
    """
    suffix = norm_tool[len("cli_"):].strip("_")
    if not suffix:
        return _SHELL_ACK[lang]
    service = _CLI_SERVICE_NAMES.get(
        suffix, suffix.replace("_", " ").title()
    )
    return _interpolate(_CLI_SERVICE_ACK[lang], service=service)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_ack(
    tool_name: str,
    tool_args: Mapping[str, Any] | None = None,
    *,
    language: str = "en",
    picker: AckPhrasePicker | None = None,
) -> str | None:
    """Render a short, task-specific ack string for the given tool call.

    Returns ``None`` if the tool is in :data:`ACK_SKIP_TOOLS` — the caller
    should treat that as "do not emit an announcement at all".

    The function is total: it never raises. Unknown tool names fall through
    to the generic pool rather than aborting. Selection is intentionally
    varied: the (process-wide) ``picker`` avoids repeating any of the last
    few phrases, so back-to-back acks never sound identical. Pass an
    explicit ``picker`` to isolate state (tests).
    """
    norm = _normalize_tool_name(tool_name)
    if not norm or norm in ACK_SKIP_TOOLS:
        return None
    lang = _normalize_language(language)
    chooser = picker if picker is not None else _DEFAULT_PICKER

    # cli_<name> aliases (cli_supabase, cli_gh, cli_vercel, ...) resolve a
    # human service name for an informative ack.
    if norm.startswith("cli_") and norm not in _TEMPLATES:
        try:
            return chooser.pick(_cli_pool(norm, lang))
        except Exception:  # noqa: BLE001 — never let a broken pool muzzle the ack
            return chooser.pick(_GENERIC_ACK[lang])

    handler = _TEMPLATES.get(norm)
    if handler is not None:
        try:
            pool = handler(tool_args or {}, lang)
            if pool:
                return chooser.pick(pool)
        except Exception:  # noqa: BLE001 — never let a broken template muzzle the ack
            pass
    return chooser.pick(_GENERIC_ACK[lang])


def describe_tool_action(
    tool_name: str, tool_args: Mapping[str, Any] | None = None
) -> str:
    """Compact ENGLISH description of what the tool call is about to do.

    Prompt input for the contextual interim composer (`ReadbackComposer`),
    NOT product surface — the composer answers in the resolved turn language.
    Extracts the most informative arg (query / app / skill / CLI service)
    without ever echoing raw shell commands. Total: never raises; unknown
    tools get a neutral "working on the request".
    """
    norm = _normalize_tool_name(tool_name)
    args: Mapping[str, Any] = tool_args or {}

    def _arg(*names: str, max_len: int = 60) -> str:
        for name in names:
            try:
                value = str(args.get(name) or "").strip()
            except Exception:  # noqa: BLE001 — garbage args must not break the ack
                value = ""
            if value:
                return _trim_to_words(value, max_len)
        return ""

    try:
        if norm.startswith("cli_") and norm != "cli_tools":
            suffix = norm[len("cli_"):].strip("_")
            service = _CLI_SERVICE_NAMES.get(
                suffix, suffix.replace("_", " ").title()
            )
            return f"querying {service}" if service else "running a quick lookup"
        if norm == "search_web":
            query = _arg("query", "q")
            return (
                f"running a web search for {query!r}" if query
                else "running a web search"
            )
        if norm in ("run_shell", "cli_tools"):
            return "running a quick check on the computer"
        if norm in ("dispatch_to_harness", "dispatch_with_review",
                    "spawn_sub_jarvis", "spawn_worker"):
            return "handing the task to a background helper"
        if norm == "multi_spawn":
            tasks = args.get("tasks") or args.get("jobs") or []
            n = len(tasks) if isinstance(tasks, (list, tuple)) else 0
            return (
                f"starting {n} tasks in parallel" if n >= 2
                else "starting background tasks"
            )
        if norm == "open_app":
            app = _arg("app", "app_name", "name", max_len=30)
            return f"opening {app}" if app else "opening an application"
        if norm == "run_skill":
            skill = _arg("skill", "skill_name", "name", max_len=40)
            return f"running the {skill} routine" if skill else "running a routine"
        if norm == "gmail":
            action = str(args.get("action") or "list_messages").strip()
            if action == "send_message":
                return "preparing an email"
            return "fetching the user's email"
        if norm == "google_calendar":
            return "checking the user's calendar"
        if norm == "remember":
            return "saving a note to memory"
        if norm in ("verify_via_curl", "verify_localhost"):
            return "verifying the result"
        if norm == "start_preview_server":
            return "starting the preview server"
        if norm == "set_config_value":
            return "updating a setting"
    except Exception:  # noqa: BLE001 — a description bug must not mute the ack
        pass
    return "working on the request"


def final_summary_marker(language: str = "en") -> str:
    """Return the short completion phrase ('Erledigt.' / 'Done.')."""
    return _FINAL_MARKERS[_normalize_language(language)]


def should_prepend_marker(brain_text: str | None) -> bool:
    """Decide whether to prefix a 'Erledigt.' marker to the brain's reply.

    ``True`` when the reply is empty (so the marker becomes the whole reply)
    or when it does not already open with a confirmation word. ``False``
    when the brain itself already self-confirmed — in that case prepending
    would produce 'Erledigt. Okay, ...' which sounds like a stutter.
    """
    if not brain_text or not brain_text.strip():
        return True
    return not bool(_ALREADY_CONFIRMING_RE.match(brain_text))
