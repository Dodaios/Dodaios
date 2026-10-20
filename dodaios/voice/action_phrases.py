"""Localized phrases for the deterministic computer-use / local-action paths.

These run OFF the LLM — the local-action fast path and the background
computer-use offload — so the brain's language-pin machinery (which only
governs LLM-generated replies) never touches them. Each phrase is spoken or
displayed VERBATIM, so it must be rendered in the turn's language HERE (live
bug 2026-06-15: an all-English computer-use turn ended with the German
"Erledigt." completion readback).

Pure dict lookups — no LLM, no IO (AP-9 / AP-11). Languages: de / en / es / pt;
an unknown language falls back to German (the historical default). The German
column is intentionally the same wording the paths used before, so a German
turn is byte-identical to the old behavior.
"""
from __future__ import annotations

import re

from dodaios.core.turn_language import resolve_turn_language
from dodaios.i18n import catalog as i18n_catalog

_DEFAULT = "en"
_SUPPORTED = ("de", "en", "es", "pt")

#: ``HarnessTask.env`` key carrying the turn's resolved output language (de/en/es/pt)
#: into the computer-use harness, so the in-harness verifier writes its spoken
#: ``proof`` in the user's language instead of defaulting to English (live bug
#: 2026-06-27: a German turn read back "Erledigt — The file explorer window is
#: open ..."). Set by the producers (``computer_use`` tool + local-action gate),
#: read by ``dodaios.harness.screenshot_only_loop`` — shared here so the three
#: sites cannot drift apart.
OUTPUT_LANGUAGE_ENV_KEY = "JARVIS_OUTPUT_LANGUAGE"

#: ``AnnouncementRequested.source_layer`` marker the router-tier ``computer_use``
#: TOOL stamps on its background-mission completion. The tool runs in its own
#: module with no access to ``BrainManager._history``, so it tags the outcome and
#: the manager mirrors it into the live conversation history (a desktop action
#: picked by the router / in text-chat must be grounded for the next turn too —
#: the same fix the voice fast-path gets inline). Shared here so the producer
#: (computer_use tool) and the consumer (BrainManager subscriber) cannot drift.
CU_TOOL_OUTCOME_LAYER = "brain.computer_use_tool"

# key -> {lang -> template}. Templates may carry named ``{fields}``.
_PHRASES: dict[str, dict[str, str]] = i18n_catalog.nested_table("voice.action.phrases")


def resolve_phrase_language(reply_language: str | None, user_text: str) -> str:
    """Resolve de/en/es/pt for a deterministic action phrase.

    An explicit ``brain.reply_language`` pin (de/en/es/pt) wins; otherwise the
    turn's language is detected from ``user_text``; ambiguous text keeps the
    historical German default. Mirrors ``BrainManager._direct_ack_language`` so
    every non-LLM spoken path resolves language the same way.
    """
    if reply_language in _SUPPORTED:
        return str(reply_language)
    return resolve_turn_language("unknown", user_text, default=_DEFAULT)


def resolve_ambient_language() -> str:
    """Output language for a phrase with NO turn text behind it.

    Scheduled routines, cron triggers and other unattended background work have
    no user utterance to detect a language from, so the ONE resolver is fed the
    only honest inputs there are: the explicit ``brain.reply_language`` pin, and
    otherwise ``DEFAULT_LOCALE``. This layer never guesses beyond that
    (— one resolver decides, no layer re-derives). Mirrors
    ``dodaios/cu/indicator/controller.py::_resolve_hint_language``, which needs
    the same answer for the same reason.
    """
    from dodaios.core.turn_language import (  # noqa: PLC0415
        DEFAULT_LOCALE,
        resolve_output_language,
    )

    pin = ""
    try:
        from dodaios.core.config import load_config  # noqa: PLC0415

        pin = str(getattr(load_config().brain, "reply_language", "") or "")
    except Exception:  # noqa: BLE001 — config trouble must not silence a report
        pin = ""
    return resolve_output_language(pin, "", "", default=DEFAULT_LOCALE)


def action_phrase(key: str, lang: str, **fmt: object) -> str:
    """Render the localized phrase ``key`` in ``lang`` (de/en/es).

    Unknown languages fall back to German. ``fmt`` fills any named template
    fields (e.g. ``error``, ``secs``, ``tool``).
    """
    variants = _PHRASES[key]
    template = variants.get(lang) or variants[_DEFAULT]
    return template.format(**fmt) if fmt else template


# A bare "exit N" token, optionally wrapped in brackets/whitespace, with nothing
# else of substance around it — the opaque string ``dispatch_to_harness`` emits
# (``f"exit {exit_code}"``). This must never be spoken to the user.
_BARE_EXIT_RE = re.compile(r"^\s*\(?\s*exit\s*\d+\s*\)?\s*$", re.IGNORECASE)
#: The harness CANCEL exit code (128 + SIGINT). Emitted ONLY when the
#: computer-use cancel token is tripped — i.e. the user hung up ("auflegen").
#: Mirrors ``_CANCEL_EXIT_CODE`` in dodaios/harness/screenshot_only_loop.py.
#: Exposed publicly so the background-offload path can recognise a
#: user-initiated abort and stay SILENT: the user just triggered the abort
#: themselves, so a "the action was cancelled" readback is redundant — and with
#: N parallel offloaded missions it would spam the phrase N times (live forensic
#: 2026-06-27). "auflegen" is a hard, immediately-silent kill-switch.
CU_CANCEL_EXIT_CODE: int = 130
#: Static map: harness exit code -> generic plain-language phrase key. Keep in
#: sync with the exit-code legend in dodaios/harness/screenshot_only_loop.py.
_EXIT_CODE_PHRASE: dict[int, str] = {
    1: "cu_exit_no_view",
    2: "cu_exit_confused",
    3: "cu_exit_no_provider",
    4: "cu_exit_too_many_steps",
    5: "cu_exit_gave_up",
    8: "cu_exit_action_failed",
    9: "cu_exit_needs_elevation",
    CU_CANCEL_EXIT_CODE: "cu_exit_cancelled",
}
#: Strip the loop's "[cu] <verb> at <tag>: " prefix so the human reason the
#: model gave for ``fail`` surfaces clean (the loop writes
#: ``"[cu] fail at step-N: <reason>"`` to stderr).
_CU_REASON_PREFIX_RE = re.compile(
    r"^\s*\[cu\][^:]*:\s*", re.IGNORECASE,
)
#: Internal computer-use DIAGNOSTIC / telemetry markers. A stderr fragment
#: carrying any of these is loop instrumentation — the no-progress guard, the
#: anti-oscillation / toggle guards, or the latency "mission profile" summary —
#: NOT the model's human ``fail`` reason. It must never be forwarded into a
#: spoken/displayed readback. Live bug 2026-06-20 (Angela-Merkel x.com mission):
#: the user heard "Das am Bildschirm hat nicht geklappt: 3 identical screenshots  # i18n-allow  # i18n-allow
#: in a row at step 9 -- the click ..." followed by the raw
#: "[cu] mission profile: steps=9 ..." telemetry line. The exit-code phrases
#: (``cu_exit_*``) exist precisely so these cases degrade to a plain sentence.
_CU_DIAGNOSTIC_RE = re.compile(
    r"\[cu\]"                      # any engineering-prefixed loop line
    r"|identical\s+screenshots?"   # no-progress guard
    r"|mission\s+profile"          # latency telemetry summary
    r"|guard-blocked"              # anti-oscillation / modal guards
    r"|toggle-stop",               # repeated-click toggle guard
    re.IGNORECASE,
)
#: A raw VERIFIER OBSERVATION dump, as opposed to a clean user-facing answer.
#: The read-goal verifier (``_READ_VERIFIER_SYSTEM_PROMPT`` in
#: ``screenshot_only_loop.py``) is a STRICT completion judge: it often PROVES the
#: goal by describing the UI structurally ("Foreground window (...): title '...',
#: content starts '...', followed by bullet points ..., Bottom status bar: ...")
#: rather than answering the user in plain language. Such a proof is an internal
#: evidence artifact (the spirit of ADR-0009 — the voice readback speaks only a
#: clean summary, never the raw signed observation), so it must never be spoken
#: verbatim. Live bug 2026-06-21 (travel-guide HTML turn): a "look at my screen
#: and tell me which app is open" mission read out the full structural dump,
#: INCLUDING the verbatim content of an unrelated parallel Claude-Code
#: AskUserQuestion box ("Eine Detail-Erkenntnis ... Der Guide rendert ...").  # i18n-allow
#: A genuine
#: content answer ("the browser is open showing tab 'Gmail'", "newest messages:
#: Alice 'hi'") carries none of these structural markers and is still forwarded.
_CU_VERIFIER_DUMP_RE = re.compile(
    r"\b(?:fore|back)ground\s+window\b"        # window-layer vocabulary
    r"|\bactive\s+window\b"
    r"|\bvordergrundfenster\b"                  # i18n-allow: DE verifier
    r"|\b(?:status|title|menu|tool|task|side|scroll|address)[\s-]?bars?\b"
    r"|(?:status|titel|men[üu]|symbol|seiten|bildlauf|adress|task|werkzeug)"  # i18n-allow
    r"[\s-]?leisten?\b"                         # i18n-allow: Status-/Titel-/Symbolleiste
    r"|\bcontent\s+(?:starts?|reads?|begins?|shows?|says?)\b"
    r"|\bfollowed\s+by\s+bullet"
    r"|\bbullet\s+points?\b"
    r"|\bwindow\s+(?:title|content|titled)\b",
    re.IGNORECASE,
)
#: The latency "mission profile" line is a run of numeric ``key=value`` telemetry
#: tokens: "steps=3 total=9.5s act=3.0s observe=0.3s plan=1.6s think=4.6s". The
#: FAILURE path strips the "[cu] mission profile:" PREFIX (via
#: ``_CU_REASON_PREFIX_RE``) before the speakability gate runs, which deletes the
#: very "[cu]"/"mission profile" markers ``_CU_DIAGNOSTIC_RE`` keys on — so the
#: BARE profile sailed straight through and was spoken (live bug 2026-06-22, the
#: Ed-Sheeran "Perfect" turn: 'That didn't work on screen: steps=3 total=9.5s
#: act=3.0s observe=0.3s plan=1.6s think=4.6s'). Detect the profile STRUCTURALLY
#: instead — independent of any prefix: any of the named phase keys, or two or
#: more numeric ``key=value`` tokens in a row, is a machine stats dump, never a
#: human sentence. A lone "HTTP 403" / "2 attempts" carries no ``=`` and survives.
_CU_TELEMETRY_RE = re.compile(
    r"\b(?:steps|total|act|observe|plan|think|verify)=\d"  # a named profile stat
    r"|(?:\b[A-Za-z_][\w-]*=\d[\d.]*\w*\b\s*){2,}",        # >=2 numeric key=value
    re.IGNORECASE,
)
#: A filesystem path or screenshot-artifact filename that leaked into a readback.
#: The harness temp capture ("C:\\…\\pythonw_xxxx.png") rode the failure ``detail``
#: into the spoken text on the same 2026-06-22 turn. A spoken answer never names a
#: path or an image file, so any of these forces the generic phrase. The image
#: extension is matched cross-platform (the screenshot leak is identical on a
#: headless Linux VPS, where the path would be POSIX).
_CU_PATH_ARTIFACT_RE = re.compile(
    r"[A-Za-z]:[\\/]"                                  # a Windows drive-letter path
    r"|\b[\w-]+\.(?:png|jpe?g|gif|bmp|webp|tiff?)\b",  # a screenshot / image file
    re.IGNORECASE,
)


def _is_diagnostic_noise(text: str) -> bool:
    """True if ``text`` is internal machine noise that must never be spoken.

    The shared, structural junk-detector behind both speakability gates. Covers
    the named loop markers (``_CU_DIAGNOSTIC_RE``), the bare latency ``mission
    profile`` stats run (``_CU_TELEMETRY_RE`` — matched by SHAPE so it still trips
    after the "[cu] mission profile:" prefix has been stripped off), and a leaked
    filesystem / screenshot path (``_CU_PATH_ARTIFACT_RE``). Pure regex, no LLM
    (AP-11): the answer is "is this a sentence a butler would say, or a developer
    log line?" — the user's "if you see that junk, you know not to speak it".
    """
    return bool(
        _CU_DIAGNOSTIC_RE.search(text)
        or _CU_TELEMETRY_RE.search(text)
        or _CU_PATH_ARTIFACT_RE.search(text)
    )


def _looks_human(text: str) -> bool:
    """True if ``text`` is a real reason sentence, not an opaque exit token.

    Defensive against the upstream layer: when a parallel change makes the
    harness forward the model's ``fail`` reason, we forward it; only a bare
    ``exit N`` / purely-numeric / empty error gets replaced by a generic phrase.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _BARE_EXIT_RE.match(stripped):
        return False
    # A token that is only digits / punctuation carries no human meaning.
    if not re.search(r"[A-Za-zÀ-ÿ]", stripped):
        return False
    return True


def _is_speakable_reason(text: str | None) -> bool:
    """True if ``text`` is a real, user-facing reason — safe to forward verbatim.

    Stricter than :func:`_looks_human`: besides rejecting bare ``exit N`` /
    numeric / empty tokens, it rejects internal computer-use DIAGNOSTIC and
    telemetry strings (the no-progress guard, the anti-oscillation / toggle
    guards, the bare latency ``mission profile`` stats run, and a leaked
    screenshot path). Those are developer instrumentation written to the harness
    ``stderr`` — never the model's human ``fail`` reason — so they must never
    reach a spoken/displayed readback. A blocked string degrades to the generic,
    localized exit-code phrase instead.
    """
    if not _looks_human(text or ""):
        return False
    return not _is_diagnostic_noise(text or "")


def _is_speakable_observation(text: str | None) -> bool:
    """True if ``text`` is a clean, user-facing observation — safe to speak.

    The SUCCESS sibling of :func:`_is_speakable_reason`. Besides rejecting bare
    ``exit N`` / numeric / empty tokens, internal diagnostic markers, the bare
    telemetry profile, and a leaked screenshot path (all via
    :func:`_is_diagnostic_noise`), it also rejects a raw VERIFIER UI-STRUCTURE
    dump (``_CU_VERIFIER_DUMP_RE``): a "Foreground window (...): title '...',
    content starts '...'" proof is the judge's internal evidence, not the answer
    the user asked for, and leaks whatever happened to be on screen (incl.
    unrelated windows). A blocked observation degrades to the generic, localized
    ``cu_done`` phrase instead.
    """
    if not _looks_human(text or ""):
        return False
    if _is_diagnostic_noise(text or ""):
        return False
    return _CU_VERIFIER_DUMP_RE.search(text or "") is None


#: Failure families OUR OWN tools emit, mapped to a spoken sentence per
#: language. Tool error strings are English by contract (the
#: model rephrases them for the user), but the rephrasing model is not always
#: there — no ``[ack_brain]`` provider, a dead key, an exhausted quota, the
#: breaker open. Live 2026-08-20: the Gemini flash slot answered 404 (stale
#: pinned model) and then 429 (credits gone), so EVERY readback came out of the
#: canned table and a German turn spoke the failure line with the cause still
#: in English — half the sentence in the wrong language.
#:
#: These are OUR strings with OUR wording, so the mapping is a deterministic
#: regex table, not a translator (AP-11: no LLM on this path). An unknown
#: reason — any third-party plugin's own text — is passed through verbatim,
#: because a foreign-language cause still beats no cause at all.
#: Sentence boundary for a merged cause. Splits only on a full stop that is
#: followed by whitespace, so a dotted token inside one cause (a file name,
#: a skill id) stays whole.
_REASON_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_REASON_FAMILIES: tuple[tuple[re.Pattern[str], dict[str, str]], ...] = (
    (
        re.compile(
            r"^(?P<subject>[\w .&'’-]{2,40}?)\s+is not connected\b.*$",
            re.IGNORECASE | re.DOTALL,
        ),
        {
            "de": "{subject} ist nicht verbunden. "  # i18n-allow
                  "Verbinde es in der Plugins-Ansicht.",  # i18n-allow
            "en": "{subject} is not connected. Connect it in the Plugins view.",
            "es": "{subject} no está conectado. Conéctalo en la vista de Plugins.",
            "pt": "{subject} não está ligado. Liga-o na vista de Plugins.",
        },
    ),
    (
        re.compile(
            r"^(?P<subject>[\w .&'’-]{2,40}?)\s+authorization expired\b.*$",
            re.IGNORECASE | re.DOTALL,
        ),
        {
            "de": "Die Anmeldung bei {subject} ist abgelaufen. "  # i18n-allow
                  "Verbinde es in der Plugins-Ansicht neu.",  # i18n-allow
            "en": "The sign-in for {subject} expired. Reconnect it in the Plugins view.",
            "es": "La sesión de {subject} caducó. Vuelve a conectarlo en la vista de Plugins.",
            "pt": "A sessão de {subject} expirou. Volta a ligá-lo na vista de Plugins.",
        },
    ),
    (
        re.compile(r"^Unknown skill:\s*(?P<subject>[^.]{1,60})\.?.*$", re.DOTALL),
        {
            "de": "Ich kenne keinen Skill namens {subject}.",  # i18n-allow
            "en": "I don't know a skill called {subject}.",
            "es": "No conozco ninguna skill llamada {subject}.",
            "pt": "Não conheço nenhuma skill chamada {subject}.",
        },
    ),
    (
        re.compile(
            r"^Skill '(?P<subject>[^']{1,60})' is in DRAFT state\b.*$", re.DOTALL
        ),
        {
            "de": "Der Skill {subject} ist noch ein Entwurf. Gib ihn erst frei.",  # i18n-allow
            "en": "The skill {subject} is still a draft. Promote it first.",
            "es": "La skill {subject} sigue siendo un borrador. Actívala primero.",
            "pt": "A skill {subject} ainda é um rascunho. Ativa-a primeiro.",
        },
    ),
    (
        re.compile(
            r"^Skill '(?P<subject>[^']{1,60})' is DISABLED\b.*$", re.DOTALL
        ),
        {
            "de": "Der Skill {subject} ist ausgeschaltet. "  # i18n-allow
                  "Schalte ihn erst wieder ein.",  # i18n-allow
            "en": "The skill {subject} is switched off. Switch it back on first.",
            "es": "La skill {subject} está desactivada. Vuelve a activarla primero.",
            "pt": "A skill {subject} está desativada. Volta a ativá-la primeiro.",
        },
    ),
)


#: The agent-facing refusal of the permission layer ("[permission_needed:<perm>] This
#: action cannot run: ... You must not ...") is prohibitive text for the LLM, never for
#: a person. A tool error that carries it is replaced by ONE short, reason-agnostic
#: cause sentence (it makes no claim about the remedy: that depends on the reason and
#: the on-screen card says it), which :func:`localize_failure_reason` then speaks in
#: the turn's language. Pure regex and fixed tables (AP-11).
_PERMISSION_NEEDED_TOKEN_RE = re.compile(r"\[permission_needed:(?P<token>[a-z_]+)\]")
_PERMISSION_CAUSE_EN = "Dodaios does not have the {name} permission right now."
_PERMISSION_CAUSE_RE = re.compile(
    r"^Dodaios does not have the (?P<name>.+?) permission right now\.$"
)
_PERMISSION_CAUSE_TEMPLATES: dict[str, str] = i18n_catalog.table(
    "voice.action.permission_cause_templates"
)
#: How each language names a permission (the macOS UI labels; unverified on a real Mac).
_PERMISSION_CAUSE_NAMES: dict[str, dict[str, str]] = i18n_catalog.nested_table(
    "voice.action.permission_cause_names"
)
_PERMISSION_CAUSE_NAMES["event_posting"] = _PERMISSION_CAUSE_NAMES["accessibility"]
_PERMISSION_TOKEN_BY_EN_NAME: dict[str, str] = {
    names["en"]: token for token, names in _PERMISSION_CAUSE_NAMES.items()
}
#: Causes without a permission name: a macOS system dialog that is open, and a token
#: this build does not know. English sentence -> its localized wording.
_PERMISSION_FIXED_CAUSES: dict[str, dict[str, str]] = {
    "Dodaios paused because a macOS system dialog is open.": {
        "de": "Dodaios hat angehalten, weil ein Systemdialog offen ist.",  # i18n-allow
        "en": "Dodaios paused because a macOS system dialog is open.",
        "es": "Dodaios se detuvo porque hay un cuadro de diálogo del sistema abierto.",
        "pt": "O Dodaios parou porque há uma caixa de diálogo do sistema aberta.",
    },
    "A macOS permission is missing right now.": {
        "de": "Eine macOS-Berechtigung fehlt gerade.",  # i18n-allow
        "en": "A macOS permission is missing right now.",
        "es": "Falta un permiso de macOS en este momento.",
        "pt": "Falta uma permissão do macOS neste momento.",
    },
}


def _permission_cause(text: str | None) -> str | None:
    """The one-sentence English cause of an agent permission refusal, else ``None``.

    Looks for the ``[permission_needed:<token>]`` marker ANYWHERE in ``text`` (a
    tool may wrap the refusal) and drops the rest of it: the prohibitive agent
    sentences, wrapped prefixes and anything after the marker never reach a person.
    """
    match = _PERMISSION_NEEDED_TOKEN_RE.search(text or "")
    if match is None:
        return None
    permission = match.group("token")
    if permission == "system_dialog":
        return "Dodaios paused because a macOS system dialog is open."
    names = _PERMISSION_CAUSE_NAMES.get(permission)
    if names is None:
        return "A macOS permission is missing right now."
    return _PERMISSION_CAUSE_EN.format(name=names["en"])


def _localize_permission_cause(sentence: str, lang: str) -> str | None:
    """Speak a :func:`_permission_cause` sentence in ``lang``; ``None`` if it is not one."""
    fixed = _PERMISSION_FIXED_CAUSES.get(sentence)
    if fixed is not None:
        return fixed.get(lang) or fixed[_DEFAULT]
    match = _PERMISSION_CAUSE_RE.match(sentence)
    token = _PERMISSION_TOKEN_BY_EN_NAME.get(match.group("name")) if match else None
    if token is None:
        return None
    names = _PERMISSION_CAUSE_NAMES[token]
    template = _PERMISSION_CAUSE_TEMPLATES.get(lang) or _PERMISSION_CAUSE_TEMPLATES[_DEFAULT]
    return template.format(name=names.get(lang) or names[_DEFAULT])


def localize_failure_reason(reason: str | None, language: str) -> str:
    """Speak a KNOWN failure cause in the turn's language; pass others through.

    The deterministic floor under the contextual composer. When the composer
    is alive it rephrases the cause itself and this table never shows; when it
    is not — and on the 2026-08-20 dev box it was not, twice over — this is
    what keeps a German turn from ending in an English clause.

    Returns ``""`` for an empty input, the mapped sentence for a family in
    :data:`_REASON_FAMILIES`, and the input unchanged for anything else.
    """
    text = " ".join(str(reason or "").split())
    if not text:
        return ""
    lang = str(language or "").strip().lower()
    # A merged failure carries ONE sentence per broken tool, so the families
    # are matched sentence by sentence. Run whole, the first family's trailing
    # ``.*`` swallows every later cause and the user hears one of the two
    # things that broke — the exact opposite of the standing rule that a
    # failure names its cause.
    #
    # That trailing ``.*`` still earns its keep WITHIN one cause: a family
    # sentence often drags a machine tail behind it ("Installed skills: a, b,
    # c"), and none of that is speakable. So once a family has matched, a
    # following sentence is kept only if it is a cause in its own right.
    # Before the first match nothing is dropped: an unrecognized reason is a
    # third party's own wording and still beats no cause at all.
    spoken: list[str] = []
    matched = False
    for sentence in _REASON_SENTENCE_RE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        localized = _localize_one_reason(sentence, lang)
        if localized is None:
            if not matched:
                spoken.append(sentence)
            continue
        matched = True
        spoken.append(localized)
    return " ".join(spoken)


def _localize_one_reason(sentence: str, lang: str) -> str | None:
    """Map ONE reported cause onto its localized wording.

    Returns ``None`` when no family owns the sentence — the caller decides
    whether an unrecognized sentence is a cause of its own or the machine tail
    of the cause before it.
    """
    permission_cause = _localize_permission_cause(sentence, lang)
    if permission_cause is not None:
        return permission_cause
    for pattern, templates in _REASON_FAMILIES:
        match = pattern.match(sentence)
        if match is None:
            continue
        # Same language resolution as ``action_phrase``: an unknown code falls
        # back to the module default, never to a half-translated sentence.
        template = templates.get(lang) or templates[_DEFAULT]
        subject = " ".join(match.group("subject").split()).strip("'\" ")
        if not subject:
            continue
        return template.format(subject=subject)
    return None


def extract_speakable_reason(error: str | None, output: object = None) -> str | None:
    """Pull a clean, user-facing failure reason out of a tool result, or ``None``.

    The single opaque-token gate for every NON-computer-use failure readback
    (the local-action fast path, the spawn / leaked-tool recovery paths). It
    mirrors :func:`cu_failure_readback`'s resolution, reusing the same guards so
    the "what may be spoken" rule lives in ONE place:

    1. If ``output`` is a harness/tool result dict, prefer a human sentence from
       its ``stderr`` (then ``stdout``) — the loop's ``"[cu] … : "`` prefix is
       stripped first.
    2. Otherwise fall back to ``error`` if it is itself a human sentence.
    3. Return ``None`` when nothing speakable remains — a bare ``exit N``, a
       purely numeric / empty token, internal diagnostic / telemetry noise, or a
       leaked path. The caller then degrades to a generic localized phrase.

    Pure regex, no LLM (AP-11). The user must NEVER hear the opaque ``exit N``
    token the tool layer emits (``dispatch_to_harness`` → ``f"exit {code}"``).
    """
    if isinstance(output, dict):
        for field in ("stderr", "stdout"):
            raw = str(output.get(field) or "").strip()
            if not raw:
                continue
            # The agent text of a permission refusal is never forwarded: one fixed cause.
            if (cause := _permission_cause(raw)) is not None:
                return cause
            candidate = _CU_REASON_PREFIX_RE.sub("", raw).strip()
            if _is_speakable_reason(candidate):
                return candidate
    if (cause := _permission_cause(error)) is not None:
        return cause
    if _is_speakable_reason(error):
        return str(error).strip()
    return None


#: The engine's own line for a mission stopped by a macOS permission or a system
#: dialog: ``"[cu] blocked_permission at step-N: <sentence>"``. It is NOT the
#: ``[cu] fail`` family: the sentence is a fixed user-facing template, and the
#: engine always appends a ``[cu] mission profile`` line after it, which is what
#: used to trip :data:`_CU_DIAGNOSTIC_RE` and degrade the readback to the generic
#: "an action failed" phrase.
_CU_BLOCKED_PERMISSION_RE = re.compile(
    r"^[ \t]*\[cu\][ \t]+blocked_permission\b[^:\n]*:[ \t]*(?P<sentence>[^\n]*)$",
    re.IGNORECASE | re.MULTILINE,
)
#: The engine's exit code for a tool/action failure; ``blocked_permission`` rides it.
_CU_TOOL_EXIT_CODE = 8

#: How the localized (de/es/pt) phrase names a permission, found by keyword in the
#: engine's English sentence: ``(keyword, {lang: (permission name, settings pane)})``.
#: The pane names are the macOS UI labels (UNVERIFIED on a real Mac: they move
#: between macOS versions).
_BLOCKED_PERMISSION_NAMES: tuple[tuple[str, dict[str, tuple[str, str]]], ...] = (
    (
        "accessibility",
        {
            "de": (
                "Bedienungshilfen",  # i18n-allow
                "Systemeinstellungen > Datenschutz & Sicherheit > Bedienungshilfen",  # i18n-allow
            ),
            "es": (
                "Accesibilidad",
                "Ajustes del Sistema > Privacidad y seguridad > Accesibilidad",
            ),
            "pt": (
                "Acessibilidade",
                "Definições do Sistema > Privacidade e segurança > Acessibilidade",
            ),
        },
    ),
    (
        "screen recording",
        {
            "de": (
                "Bildschirm- und Systemaudioaufnahme",  # i18n-allow
                "Systemeinstellungen > Datenschutz & Sicherheit > "  # i18n-allow
                "Bildschirm- & Systemaudioaufnahme",  # i18n-allow
            ),
            "es": (
                "Grabación de pantalla y audio del sistema",
                "Ajustes del Sistema > Privacidad y seguridad > "
                "Grabación de pantalla y audio del sistema",
            ),
            "pt": (
                "Gravação de ecrã e áudio do sistema",
                "Definições do Sistema > Privacidade e segurança > Gravação de ecrã e áudio do "
                "sistema",
            ),
        },
    ),
    (
        "input monitoring",
        {
            "de": (
                "Eingabeüberwachung",  # i18n-allow
                "Systemeinstellungen > Datenschutz & Sicherheit > Eingabeüberwachung",  # i18n-allow
            ),
            "es": (
                "Supervisión de entradas",
                "Ajustes del Sistema > Privacidad y seguridad > Supervisión de entradas",
            ),
            "pt": (
                "Monitorização de entrada",
                "Definições do Sistema > Privacidade e segurança > Monitorização de entrada",
            ),
        },
    ),
    (
        "microphone",
        {
            "de": (
                "Mikrofon",  # i18n-allow
                "Systemeinstellungen > Datenschutz & Sicherheit > Mikrofon",  # i18n-allow
            ),
            "es": (
                "Micrófono",
                "Ajustes del Sistema > Privacidad y seguridad > Micrófono",
            ),
            "pt": (
                "Microfone",
                "Definições do Sistema > Privacidade e segurança > Microfone",
            ),
        },
    ),
    (
        "automation",
        {
            "de": (
                "Automation",
                "Systemeinstellungen > Datenschutz & Sicherheit > Automation",  # i18n-allow
            ),
            "es": (
                "Automatización",
                "Ajustes del Sistema > Privacidad y seguridad > Automatización",
            ),
            "pt": (
                "Automatização",
                "Definições do Sistema > Privacidade e segurança > Automatização",
            ),
        },
    ),
)


def cu_blocked_permission_sentence(stderr: str | None) -> str | None:
    """The engine's user sentence of a ``blocked_permission`` mission, else ``None``.

    Reads the ``"[cu] blocked_permission at step-N: <sentence>"`` line out of the
    mission's ``stderr`` wherever it sits (the engine appends a ``[cu] mission
    profile`` line after it). The sentence is a fixed template with no exception
    text, path or window title; one that nevertheless looks like machine noise
    (diagnostic marker, telemetry, a path) is dropped, so the caller falls back to
    a fixed phrase. Pure regex (AP-11).
    """
    match = _CU_BLOCKED_PERMISSION_RE.search(stderr or "")
    if match is None:
        return None
    sentence = match.group("sentence").strip()
    return sentence if _is_speakable_reason(sentence) else ""


def _spoken_en(sentence: str) -> str:
    """The engine's English sentence, made speakable and addressed to the listener.

    The engine writes it about "the user" and with a Settings path joined by ``>``;
    spoken, that reads as "greater than" and talks about somebody else. Pure regex
    (AP-11).
    """
    spoken = re.sub(r"\bThe user has to\b", "You have to", sentence)
    spoken = re.sub(r"\bthe user\b", "you", spoken, flags=re.IGNORECASE)
    return _spoken_pane(spoken, "en")


def _spoken_pane(text: str, lang: str) -> str:
    """Replace the written Settings-path separators with speakable words."""
    and_word = {"de": "und", "es": "y", "pt": "e"}.get(lang, "and")
    then_word = {"de": "dann", "es": "luego", "pt": "depois"}.get(lang, "then")
    return text.replace(" > ", f", {then_word} ").replace(" & ", f" {and_word} ")


def _blocked_permission_readback(lang: str, sentence: str) -> str:
    """The localized readback of a ``blocked_permission`` mission (no LLM, AP-11).

    English forwards the engine's own sentence (second person, speakable). de/es/pt
    cannot (it is English), so they name the permission by keyword and pick the
    remedy by REASON: a dialog still open, a restart, an unaskable permission or a
    restriction each get their own phrase, and only a switch that is off says "allow
    it in Settings". A sentence they cannot place falls back to the fixed generic
    phrase.
    """
    low = sentence.lower()
    if lang == "en" and sentence:
        return action_phrase("cu_blocked_permission", lang, sentence=_spoken_en(sentence))
    if "system dialog" in low:
        return action_phrase("cu_blocked_dialog", lang)
    if "restricted" in low:
        return action_phrase("cu_blocked_restricted", lang)
    names = next((n for keyword, n in _BLOCKED_PERMISSION_NAMES if keyword in low), None)
    if names is None or lang not in names:
        return action_phrase("cu_blocked_generic", lang)
    permission, pane = names[lang]
    if "quit and reopened" in low:
        return action_phrase("cu_blocked_restart_hint", lang, permission=permission)
    if "cannot ask" in low:
        return action_phrase("cu_blocked_unavailable", lang, permission=permission)
    if "macos dialog" in low or "showing a dialog" in low:
        return action_phrase("cu_blocked_waiting", lang, permission=permission)
    return action_phrase(
        "cu_blocked_permission", lang, permission=permission, pane=_spoken_pane(pane, lang)
    )


def cu_failure_readback(
    lang: str,
    *,
    error: str | None,
    exit_code: int | None = None,
    detail: str | None = None,
) -> str:
    """Compose the spoken/chat readback for a Computer-Use FAILURE.

    The user must NEVER hear a raw exit code (live bug: "That didn't work on
    screen: exit 5"). This is a pure STATIC lookup — no LLM call (AP-11).

    Resolution order, most-specific first:

    1. ``detail`` (e.g. the harness ``stderr`` carrying the model's ``fail``
       reason) — if it contains a human sentence, FORWARD it (it gets scrubbed
       downstream). The loop's ``"[cu] fail at <tag>: "`` prefix is stripped.
    2. ``error`` — if it is already a human sentence (not a bare ``exit N`` /
       numeric token), FORWARD it.
    3. Otherwise substitute the generic, localized phrase keyed off
       ``exit_code`` (``cu_exit_*``), falling back to the plain
       "didn't work on screen" sentence when the code is unknown.
    """
    # 0) A mission stopped by a macOS permission or a system dialog says what is
    # missing and where to allow it. Checked first: the engine always appends a
    # "[cu] mission profile" line, and the diagnostic gate below would turn the
    # whole detail into the generic "an action failed" phrase.
    if exit_code == _CU_TOOL_EXIT_CODE:
        blocked = cu_blocked_permission_sentence(detail)
        if blocked is not None:
            return _blocked_permission_readback(lang, blocked)

    # 0b) The agent text of a permission refusal is never spoken: one fixed cause.
    for source in (detail, error):
        if (cause := _permission_cause(source)) is not None:
            spoken = _localize_permission_cause(cause, lang) or cause
            return action_phrase("cu_failed_reason", lang, error=spoken)

    # 1) The harness detail string may carry the model's verified reason.
    if detail:
        candidate = _CU_REASON_PREFIX_RE.sub("", detail).strip()
        if _is_speakable_reason(candidate):
            return action_phrase("cu_failed_reason", lang, error=candidate)

    # 2) A human reason already on the error field is forwarded verbatim.
    if _is_speakable_reason(error):
        return action_phrase("cu_failed_reason", lang, error=str(error).strip())

    # 3) Opaque / empty error -> map the exit code to a human phrase.
    phrase_key = _EXIT_CODE_PHRASE.get(int(exit_code)) if exit_code is not None else None
    if phrase_key is None:
        # Unknown / missing exit code: the neutral "didn't work on screen".
        return action_phrase("cu_failed", lang)
    return action_phrase(phrase_key, lang)


def _extract_cu_proof(stdout: str) -> str | None:
    """Pull the verifier's observation out of the harness success ``stdout``.

    The screenshot loop writes the proof as ``"[cu] done at <tag> (verified:
    <proof>)"`` (or ``"[cu] done (verified: <proof>)"``). We scan for that line
    and return everything inside ``(verified: ...)`` — taking up to the FINAL
    ``)`` so an inner parenthesis in the proof itself ("Der Browser (Chrome)
    ...") survives. Returns ``None`` when there is no verified-proof line (e.g.
    ``"[cu] done at <tag>"`` with no observation), so the caller can fall back.
    """
    marker = "(verified:"
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if "[cu] done" not in low or marker not in low:
            continue
        start = low.index(marker) + len(marker)
        proof = stripped[start:].strip()
        if proof.endswith(")"):
            proof = proof[:-1].strip()
        return proof or None
    return None


def cu_success_readback(lang: str, *, stdout: str | None) -> str:
    """Compose the spoken/chat readback for a Computer-Use SUCCESS.

    The SUCCESS sibling of :func:`cu_failure_readback`. When the harness
    verified the goal and left a human observation in ``stdout`` (e.g. "the
    browser is open showing tab 'X'"), FORWARD it so an informational request
    is actually answered — the observation is the answer the user asked for. A
    pure STATIC parse + lookup, no LLM call (AP-11); the text is scrubbed
    downstream like every other spoken phrase.

    Falls back to the plain localized ``cu_done`` phrase when the mission left
    no usable observation (no ``(verified: ...)`` segment, an empty/opaque
    proof, or — via :func:`_is_speakable_observation` — a raw verifier UI
    STRUCTURE dump that describes the screen instead of answering the user).
    """
    proof = _extract_cu_proof(stdout or "")
    if proof and _is_speakable_observation(proof):
        return action_phrase("cu_done_detail", lang, detail=proof)
    return action_phrase("cu_done", lang)


__all__ = [
    "CU_CANCEL_EXIT_CODE",
    "CU_TOOL_OUTCOME_LAYER",
    "OUTPUT_LANGUAGE_ENV_KEY",
    "action_phrase",
    "cu_blocked_permission_sentence",
    "cu_failure_readback",
    "cu_success_readback",
    "extract_speakable_reason",
    "localize_failure_reason",
    "resolve_ambient_language",
    "resolve_phrase_language",
]
