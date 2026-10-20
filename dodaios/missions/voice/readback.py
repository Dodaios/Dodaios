"""DE/EN voice templates for mission status.

Tone anchor: `dodaios/brain/DODAIOS_PERSONA.md` — butler register, no hardcoded
owner name. The spoken persona addresses the user by the name in their profile;
these mission-status templates stay name-neutral so a fresh clone never speaks
the maintainer's name. Hard cap of 280 characters per voice output (TTS latency
+ audio length).

Action/Observation invariant (ADR-0009 §1):
- Templates must **NEVER** read the raw LLM narrative directly.
- `summary_de` from `MissionApproved` payload is OK because it is signed
  by the **Kontrollierer** (source_actor=kontrollierer), not the LLM worker.
- `correction_instruction` from `WorkerCorrectionRequired` is NEVER
  read aloud — only "Iteration N running." as an acknowledgement.

Capability-Honesty (Capability Coupling spec, 2026-05-20):
- `render_approved` accepts an optional ``honesty_check`` parameter.
  When ``honesty_check.honesty_overridden`` is True the approval is a
  false-positive and we render the failure readback instead of a success
  message.  This is the last line of defence before text reaches TTS —
  the gate in ``runner.py`` (``enforce_capability_honesty``) should have
  already corrected the verdict, so this branch should rarely fire in
  production.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Final, Literal

from dodaios.i18n import catalog as i18n_catalog

if TYPE_CHECKING:
    from dodaios.missions.critic.runner import CapabilityHonestyCheck


# Every supported reply language (``SUPPORTED_REPLY_LANGUAGES`` minus "auto");
# all locales are equal, so every table below carries each of them.
Lang = Literal["de", "en", "es", "pt"]
TemplateKey = Literal[
    "approved",
    "failed",
    "timeout",
    "cancelled",
    "budget_warn_50",
    "budget_warn_80",
    "budget_exceeded",
    "injection_blocked",
    "path_guard_blocked",
    "destructive_confirm",
    "crash_recovery",
    "iteration_running",
]


MAX_VOICE_CHARS: Final[int] = 280


READBACK_TEMPLATES: Final[dict[TemplateKey, dict[Lang, list[str]]]] = {  # i18n-allow: German TTS voice-output templates (paired de/en)
    "approved": {
        "de": [
            "Fertig. {summary}",  # i18n-allow
            "Erledigt. {summary}",
            "Abgeschlossen. {summary}",
        ],
        "en": [
            "Done. {summary}",
            "Completed. {summary}",
        ],
        "es": [
            "Hecho. {summary}",  # i18n-allow: Spanish TTS
            "Listo. {summary}",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Feito. {summary}",  # i18n-allow: PT TTS
            "Pronto. {summary}",  # i18n-allow: PT TTS
        ],
    },
    "failed": {
        "de": [
            "Die Aufgabe ist gescheitert. Grund: {reason}",  # i18n-allow
            "Aufgabe gescheitert. {reason}",
            "Das hat nicht geklappt. {reason}",  # i18n-allow
        ],
        "en": [
            "The task failed. Reason: {reason}",
            "Task failed. {reason}",
        ],
        "es": [
            "La tarea ha fallado. Motivo: {reason}",  # i18n-allow: Spanish TTS
            "Tarea fallida. {reason}",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "A tarefa falhou. Motivo: {reason}",  # i18n-allow: PT TTS
            "Tarefa falhada. {reason}",  # i18n-allow: PT TTS
        ],
    },
    "timeout": {
        "de": [
            "Die Aufgabe ist in einen Timeout gelaufen.",  # i18n-allow
            "Zeitueberschreitung. Aufgabe abgebrochen.",
        ],
        "en": [
            "The task timed out.",
        ],
        "es": [
            "La tarea superó el tiempo límite.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "A tarefa excedeu o tempo limite.",  # i18n-allow: PT TTS
        ],
    },
    "cancelled": {
        "de": [
            "Aufgabe abgebrochen.",
            "Die Aufgabe wurde gestoppt.",  # i18n-allow
        ],
        "en": [
            "Task cancelled.",
        ],
        "es": [
            "Tarea cancelada.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Tarefa cancelada.",  # i18n-allow: PT TTS
        ],
    },
    "budget_warn_50": {
        "de": [
            "Halbes Budget verbraucht.",
            "Fuenfzig Prozent vom Budget weg.",
        ],
        "en": [
            "Half the budget used.",
        ],
        "es": [
            "La mitad del presupuesto está gastada.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Metade do orçamento já foi gasta.",  # i18n-allow: PT TTS
        ],
    },
    "budget_warn_80": {
        "de": [
            "Achtzig Prozent vom Budget weg.",
            "Das Budget wird knapp.",  # i18n-allow
        ],
        "en": [
            "Eighty percent of budget used.",
        ],
        "es": [
            "El ochenta por ciento del presupuesto está gastado.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Oitenta por cento do orçamento já foi gasto.",  # i18n-allow: PT TTS
        ],
    },
    "budget_exceeded": {
        "de": [
            "Budget aufgebraucht. Aufgabe abgebrochen.",
            "Das Limit ist erreicht. Stoppe die Aufgabe.",  # i18n-allow
        ],
        "en": [
            "Budget exhausted. Task aborted.",
        ],
        "es": [
            "Presupuesto agotado. Tarea cancelada.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Orçamento esgotado. Tarefa cancelada.",  # i18n-allow: PT TTS
        ],
    },
    "injection_blocked": {
        "de": [
            "Injection-Versuch erkannt. Aufgabe abgebrochen.",
            "Ein verdaechtiger Output wurde geblockt. Aufgabe gestoppt.",  # i18n-allow
        ],
        "en": [
            "Injection attempt detected. Task terminated.",
        ],
        "es": [
            "Intento de inyección detectado. Tarea detenida.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Tentativa de injeção detetada. Tarefa parada.",  # i18n-allow: PT TTS
        ],
    },
    "path_guard_blocked": {
        "de": [
            "Ein geschuetzter Pfad wurde angefasst. Aufgabe abgebrochen.",  # i18n-allow
            "Geblockter Pfad in der Aufgabe. Stoppe.",
        ],
        "en": [
            "A protected path was touched. Task aborted.",
        ],
        "es": [
            "Se tocó una ruta protegida. Tarea cancelada.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Foi tocado um caminho protegido. Tarefa cancelada.",  # i18n-allow: PT TTS
        ],
    },
    "destructive_confirm": {
        "de": [
            "Das wird {target} loeschen. Bist du sicher? Bitte in der UI bestaetigen.",  # i18n-allow
            "Destruktive Aktion: {target}. Bestaetigung erforderlich.",
        ],
        "en": [
            "This will destroy {target}. Are you sure? Please confirm in the UI.",
        ],
        "es": [
            "Esto eliminará {target}. ¿Seguro? Confírmalo en la interfaz.",  # i18n-allow
        ],
        "pt": [
            "Isto vai eliminar {target}. Tens a certeza? Confirma na interface.",  # i18n-allow
        ],
    },
    "crash_recovery": {
        "de": [
            "Eine vorherige Aufgabe wurde wegen Crash abgebrochen.",  # i18n-allow
            "Ich habe eine abgebrochene Aufgabe gefunden und sauber abgeschlossen.",  # i18n-allow
        ],
        "en": [
            "A previous task was aborted due to a crash.",
        ],
        "es": [
            "Una tarea anterior se canceló por un fallo.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Uma tarefa anterior foi cancelada devido a uma falha.",  # i18n-allow: PT TTS
        ],
    },
    "iteration_running": {
        "de": [
            "Iteration {n} laeuft.",  # i18n-allow
            "Naechster Versuch laeuft.",  # i18n-allow
        ],
        "en": [
            "Iteration {n} running.",
        ],
        "es": [
            "Iteración {n} en curso.",  # i18n-allow: Spanish TTS
        ],
        "pt": [
            "Iteração {n} em curso.",  # i18n-allow: PT TTS
        ],
    },
}


# Machine failure-reason code -> short human phrase. Single source shared
# with dodaios.missions.voice.announcer.MissionAnnouncer so the two voice
# readback paths (direct-TTS listener + announcer bridge) cannot drift apart
# (2026-05-27 hardening finding #7). Keys are the reasons emitted by the
# orchestrator / recovery sweep; the DE and EN sets must stay in parity.
# Keyed by language CODE (str), not the render-API ``Lang`` literal: ``es`` is
# an equal supported product-surface language and MUST be able
# to carry a phrase here even though the ``MissionReadback`` render methods
# themselves still default to the de/en ``Lang`` surface (widening that whole
# API to ``es`` is a separate, larger task). Lookups use ``.get(language, {})``
# so a code without an entry falls back cleanly. The de/en parity gate
# (``test_failure_reason_phrases_de_en_parity``) still guards those two; ``es``
# here carries only the keys that have been translated so far.
FAILURE_REASON_PHRASES: Final[dict[str, dict[str, str]]] = i18n_catalog.locale_maps(
    "missions.readback.failure_reason"
)


def approved_summary(payload: object, language: str) -> str:
    """The runtime-signed approval summary to speak in *language*.

    ``summary_de``/``summary_en`` cover German and English; ``summary_local``
    carries the dispatch language for every other locale. An event from
    before ``summary_local`` existed falls back to ``summary_en``.
    """
    if language == "de":
        return str(getattr(payload, "summary_de", "") or "")
    if language != "en":
        local = str(getattr(payload, "summary_local", "") or "")
        if local:
            return local
    return str(getattr(payload, "summary_en", "") or "")


def render_agent_brand(phrase: str) -> str:
    """Resolve the ``{agent}``/``{agents}`` placeholders to the live brand.

    The public agent-system name follows the wake-word-derived assistant name
    ("Ruben" -> "Ruben-Agent") for ANY configured wake word (2026-07-17
    rebrand). Read fresh per call so a wake-word change applies without a
    restart; any resolution failure falls back to the neutral
    "Assistant-Agent" — a spoken phrase must never carry a raw placeholder.
    """
    if "{agent" not in phrase:
        return phrase
    try:
        from dodaios.brain.assistant_name import agent_brand
        from dodaios.core.config import load_config

        brand = agent_brand(load_config())
    except Exception:  # noqa: BLE001 — never break a voice readback on config trouble
        from dodaios.brain.assistant_name import agent_brand_from_name

        brand = agent_brand_from_name("")
    return phrase.replace("{agents}", f"{brand}s").replace("{agent}", brand)


def failure_phrase_key(reason: str, error_class: str | None) -> str:
    """Pick the phrase-table key for a failed mission.

    A populated ``error_class`` (e.g. ``provider_auth``) is more specific
    than the mission-level ``reason`` (often the generic ``task_error``), so
    it wins whenever the table carries it. Falls back to the reason's short
    form. Single source for the announcer AND the direct-TTS listener.
    """
    ec = (error_class or "").strip()
    if ec and ec in FAILURE_REASON_PHRASES["en"]:
        return ec
    return (reason or "").split(":", 1)[0].strip()


# WAITING_CAPACITY readback (dodaios/missions/capacity.py). Built from runtime
# counts only — never worker text (ADR-0009 §1). Keys mirror
# CAPACITY_WAIT_REASONS in dodaios/missions/events.py; parity is guarded by
# tests/missions/test_capacity_wait_parity.py.
CAPACITY_WAIT_PHRASES: Final[dict[str, dict[str, str]]] = i18n_catalog.locale_maps(
    "missions.readback.capacity_wait_phrases"
)

_MAX_PROVIDER_CHARS: Final[int] = 40

# Display names for worker provider slugs in the capacity readback. A slug
# without an entry is spoken as-is.
_PROVIDER_DISPLAY: Final[dict[str, str]] = {
    "claude": "Claude",
    "claude-api": "Claude",
    "codex": "ChatGPT",
    "chatgpt": "ChatGPT",
    "openai": "OpenAI",
    "gemini": "Gemini",
    "antigravity": "Gemini",
    "grok": "Grok",
    "openrouter": "OpenRouter",
    "nvidia": "NVIDIA",
}


# Spoken name for a provider slug the runtime could not resolve.
_PROVIDER_FALLBACK_NAME: Final[dict[str, str]] = i18n_catalog.table(
    "missions.readback.provider_fallback_name"
)

# Spoken defaults for an empty summary / reason / destructive target.
_EMPTY_SUMMARY: Final[dict[str, str]] = i18n_catalog.table("missions.readback.empty_summary")
_UNKNOWN_REASON: Final[dict[str, str]] = i18n_catalog.table("missions.readback.unknown_reason")
_NO_TOOL_CALL: Final[dict[str, str]] = i18n_catalog.table("missions.readback.no_tool_call")
_DEFAULT_TARGET: Final[dict[str, str]] = i18n_catalog.table("missions.readback.default_target")


def _localized(table: dict[str, str], language: str) -> str:
    """Phrase for *language*; an unknown code speaks English."""
    return table.get(language, table["en"])


def render_capacity_wait(
    *,
    reason: str,
    provider: str | None,
    steps_done: int,
    steps_total: int,
    files_saved: int,
    checkpoint_saved: bool,
    language: Lang = "de",
) -> str:
    """Short readback for a mission parked in WAITING_CAPACITY: why it stopped,
    what is done, what is open, and the options (wait / approve paid use)."""
    table = CAPACITY_WAIT_PHRASES.get(language, CAPACITY_WAIT_PHRASES["en"])
    slug = (provider or "").strip()
    fallback = _PROVIDER_FALLBACK_NAME.get(language, _PROVIDER_FALLBACK_NAME["en"])
    name = (_PROVIDER_DISPLAY.get(slug.lower(), slug) or fallback)[:_MAX_PROVIDER_CHARS]
    head = [table.get(reason, table["provider_unavailable"]).format(provider=name)]
    if checkpoint_saved:
        head.append(table["saved"])
    tail = [table["wait_auth" if reason == "provider_auth" else "wait"], table["paid"]]
    progress = (
        table["progress"].format(
            done=steps_done, total=steps_total, open=max(steps_total - steps_done, 0),
        )
        if steps_total > 1
        else table["progress_single"]
    )
    files = (
        table["file"] if files_saved == 1
        else table["files"].format(files=files_saved) if files_saved > 1
        else ""
    )
    # Why it stopped and the options must survive the length cap; the file
    # count gives way first, then the step count.
    for optional in ([progress, files], [progress], []):
        text = " ".join([*head, *(o for o in optional if o), *tail])
        if len(text) <= MAX_VOICE_CHARS:
            return text
    return _truncate(text)


def _truncate(text: str, max_chars: int = MAX_VOICE_CHARS) -> str:
    """Truncate to max_chars; no suffix so TTS does not say '...'.

    We cut hard intentionally — voice templates should be short to begin
    with. If a {summary} insert is too long, this will be caught in
    the test (`test_render_*_truncates_long_summary`) and the insert
    should be capped BEFORE rendering.
    """
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    return cut


class MissionReadback:
    """Render methods for mission status voice outputs.

    Uses a dedicated PhrasePicker with anti_repeat_window=3 — prevents
    "Sir, done" from being spoken three times in a row when three
    missions complete in quick succession.
    """

    def __init__(self, *, anti_repeat_window: int = 3) -> None:
        self._window = anti_repeat_window
        # Per-(key, lang) deque of recently played templates
        self._recent: dict[tuple[str, str], deque[str]] = {}

    def _pick(self, key: TemplateKey, lang: Lang) -> str:
        """Choose a template, avoiding immediate repetition."""
        pool = READBACK_TEMPLATES.get(key, {}).get(lang, [])
        if not pool:
            # An unknown code speaks English, never German (AP-21: an
            # arbitrary user is not a German speaker).
            other: Lang = "de" if lang == "en" else "en"
            pool = READBACK_TEMPLATES.get(key, {}).get(other, [])
        if not pool:
            return ""

        cache_key = (key, lang)
        window = min(self._window, max(1, len(pool) - 1))
        recent = self._recent.setdefault(cache_key, deque(maxlen=window))
        candidates = [p for p in pool if p not in recent]
        if not candidates:
            candidates = pool
        # Deterministic for tests: first candidate. PhrasePicker
        # uses random.choice — we keep it simple + reproducible.
        choice = candidates[0]
        recent.append(choice)
        return choice

    # --- Render methods ---

    def render_approved(
        self,
        *,
        summary: str = "",
        language: Lang = "de",
        honesty_check: CapabilityHonestyCheck | None = None,
    ) -> str:
        """Render a success readback for an approved mission.

        Capability-Honesty guard: if ``honesty_check`` is provided and its
        ``honesty_overridden`` flag is ``True``, the approval is a false-
        positive (worker claimed success without making any tool call).  In
        that case we render the failure readback using the corrected
        ``summary_de`` from the overridden verdict instead of a success
        message.  This is a last-resort defence — the gate in
        ``runner.py:enforce_capability_honesty`` should already have
        overridden the verdict before the Kontrollierer signed the approval.
        """
        # --- Capability-Honesty last-resort check ---
        if honesty_check is not None and honesty_check.honesty_overridden:
            # The "approved" verdict is a false-positive: render failure.
            verdict = honesty_check.verdict
            # The corrected verdict text exists in de/en only; any other
            # language speaks its own fixed phrase rather than a German one.
            if language == "de":
                override_reason = verdict.summary_de or _localized(_NO_TOOL_CALL, "de")
            elif language == "en":
                override_reason = (
                    verdict.summary or _localized(_NO_TOOL_CALL, "en")
                )
            else:
                override_reason = _localized(_NO_TOOL_CALL, language)
            return self.render_failed(reason=override_reason, language=language)

        template = self._pick("approved", language)
        if not template:
            return ""
        # Insert cap so the final string does not exceed 280 chars
        max_insert = MAX_VOICE_CHARS - len(template) + len("{summary}")
        safe_summary = (summary or _localized(_EMPTY_SUMMARY, language)).strip()
        if len(safe_summary) > max_insert:
            safe_summary = safe_summary[:max_insert].rstrip()
        return _truncate(template.format(summary=safe_summary))

    def render_failed(
        self,
        *,
        reason: str = "",
        language: Lang = "de",
        error_class: str | None = None,
    ) -> str:
        short_reason = failure_phrase_key(reason, error_class)
        # crash_recovery and interrupted are swept/interrupted previous-session
        # missions, not live task failures — speak a dedicated non-alarming phrase
        # instead of framing them as "gescheitert. Grund: <reason>"
        # (2026-05-27 finding #7; interrupted added 2026-06-07 for commit 13b86605).
        if short_reason == "crash_recovery":
            return self.render_crash_recovery(language=language)
        if short_reason == "interrupted":
            phrase = FAILURE_REASON_PHRASES.get(language, {}).get("interrupted", "")
            if phrase:
                return _truncate(render_agent_brand(phrase))
            return self.render_crash_recovery(language=language)
        template = self._pick("failed", language)
        if not template:
            return ""
        # Map a known machine reason code to a friendly human phrase so a
        # raw snake_case token is never spoken. Shared with the announcer via
        # FAILURE_REASON_PHRASES. Unmapped reasons fall back to the raw text.
        mapped = FAILURE_REASON_PHRASES.get(language, {}).get(short_reason)
        if mapped:
            mapped = render_agent_brand(mapped)
        safe_reason = mapped if mapped else (
            reason or _localized(_UNKNOWN_REASON, language)
        ).strip()
        max_insert = MAX_VOICE_CHARS - len(template) + len("{reason}")
        if len(safe_reason) > max_insert:
            safe_reason = safe_reason[:max_insert].rstrip()
        return _truncate(template.format(reason=safe_reason))

    def render_timeout(self, *, language: Lang = "de") -> str:
        return _truncate(self._pick("timeout", language))

    def render_cancelled(self, *, language: Lang = "de") -> str:
        return _truncate(self._pick("cancelled", language))

    def render_budget_warn(self, *, pct: int, language: Lang = "de") -> str:
        if pct >= 80:
            key: TemplateKey = "budget_warn_80"
        else:
            key = "budget_warn_50"
        return _truncate(self._pick(key, language))

    def render_budget_exceeded(self, *, language: Lang = "de") -> str:
        return _truncate(self._pick("budget_exceeded", language))

    def render_injection_blocked(self, *, language: Lang = "de") -> str:
        return _truncate(self._pick("injection_blocked", language))

    def render_path_guard_blocked(self, *, language: Lang = "de") -> str:
        return _truncate(self._pick("path_guard_blocked", language))

    def render_destructive_confirm(
        self, *, target: str = "", language: Lang = "de"
    ) -> str:
        template = self._pick("destructive_confirm", language)
        if not template:
            return ""
        max_insert = MAX_VOICE_CHARS - len(template) + len("{target}")
        safe_target = (target or _localized(_DEFAULT_TARGET, language)).strip()
        if len(safe_target) > max_insert:
            safe_target = safe_target[:max_insert].rstrip()
        return _truncate(template.format(target=safe_target))

    def render_crash_recovery(self, *, language: Lang = "de") -> str:
        return _truncate(self._pick("crash_recovery", language))

    def render_iteration_running(self, *, n: int, language: Lang = "de") -> str:
        template = self._pick("iteration_running", language)
        if not template:
            return ""
        return _truncate(template.format(n=n))


__all__ = [
    "MAX_VOICE_CHARS",
    "MissionReadback",
    "READBACK_TEMPLATES",
    "approved_summary",
    "TemplateKey",
    "failure_phrase_key",
]
