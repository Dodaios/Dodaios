"""Prompt Mode — a dictation comes out as the message the user meant to type.

The user holds the dictation key and says what they want to an AI agent they
are already talking to; what lands in the input field is that message, written
in their place and in the language they spoke.

The system prompt is one paragraph: the job, and the conditions under which the
answer is discarded. Shape is not guarded (a long brief may become a structured
prompt with headings); fidelity, damage and level are, deterministically and
fail-open — a rejected answer delivers the transcript to the ordinary passes,
so the raw words are never lost. Then two deterministic finishes: typographic
debris in identifiers is normalised and a courtesy sign-off is cut.

Runs on the polish pass's chain (:mod:`dodaios.dictation.polish_client`) on the
family's stronger fast model, one call. Ships OFF.

Pure orchestration — the imports that cost anything are inside the function
(AP-26), so ``import dodaios.dictation.prompt_mode`` is free on the boot path.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Sequence
from typing import Any, Final

from dodaios.agentic_ide.prompt_blueprint import looks_truncated
from dodaios.dictation.polish import PolishOutcome
from dodaios.dictation.polish_prompt import (
    build_polish_user_message,
    build_protected_block,
)

log = logging.getLogger(__name__)

#: Bumped whenever the wording below changes in a way that could change model
#: behaviour (history: git log). v8: one paragraph, no worked examples; the
#: guards' discard conditions are stated as facts.
PROMPT_MODE_PROMPT_VERSION: Final[int] = 8

#: The status a successful Prompt Mode delivery reports on the history row.
#: Lives in ``POLISH_STATUSES`` (the shared vocabulary) — restated here as a
#: named constant so call sites compare against a name, not a string literal.
STATUS_PROMPTED: Final[str] = "prompted"

# One call, one prompt written. The bound is a safety net, not a target: the
# fast chain answers in 2-6 s depending on the provider's hardware, and 12 s
# leaves room for a long dictation on a slower family without ever cutting an
# answer off mid-prompt. 4 s is the floor (below it the pass only ever times
# out, which is worse than being off) and 20 s the ceiling before this stops
# being dictation.
_DEFAULT_TIMEOUT_MS: Final[int] = 12_000
_MIN_TIMEOUT_MS: Final[int] = 4_000
_MAX_TIMEOUT_MS: Final[int] = 20_000

# A written-out prompt with a role, sections and format rules is long — the
# reference run is about 700 tokens — and a cut-off one is rejected as
# truncated and costs the whole pass. Temperature 0: the job is well defined.
_MAX_OUTPUT_TOKENS: Final[int] = 3_000
_TEMPERATURE: Final[float] = 0.0

# The one piece of structure asked of the model, and the only reason for it:
# a model handed this job likes to introduce it ("Hier ist ein System-Prompt
# für deinen Auto-Prompting-Modus" — the reference run's own first line). The
# tag is a fence around the deliverable, not a scratchpad and not a schema.
_PROMPT_OPEN_RE: Final[re.Pattern[str]] = re.compile(r"<\s*prompt\s*>", re.IGNORECASE)
_PROMPT_CLOSE_RE: Final[re.Pattern[str]] = re.compile(r"<\s*/\s*prompt\s*>", re.IGNORECASE)
_OUR_TAGS_RE: Final[re.Pattern[str]] = re.compile(r"<\s*/?\s*prompt\s*>", re.IGNORECASE)

# A courtesy sign-off, in the two shapes measured live on 2026-08-27: a line
# of its own ("...\n\nDanke!") and a sentence tacked onto the last paragraph
# ("...lasse ihn unverändert. Danke dir."). Same vocabulary, two anchors — the
# second needs a sentence boundary in front of it, which also keeps a message
# that IS a thank-you from being erased. The reader is a model; a courtesy
# line is noise it has to step over.
_SIGN_OFF_WORDS: Final[str] = (
    r"(?:thanks?|thank\s+you|dank(?:e|esch[öo]n)?|gracias|merci|grazie|obrigad[oa]|"
    r"bedankt|tak|tack|takk|kiitos|dzi[eę]kuj[eę]|d[ěe]kuji|спасибо|ありがとう|谢谢|"
    r"regards|cheers|gr[üu][ßs]e)"
)
_SIGN_OFF_LINE_RE: Final[re.Pattern[str]] = re.compile(
    rf"^\W{{0,3}}(?:\w+\s+){{0,4}}?{_SIGN_OFF_WORDS}[\w\s,!.…]{{0,40}}$",
    re.IGNORECASE,
)
_SIGN_OFF_SENTENCE_RE: Final[re.Pattern[str]] = re.compile(
    rf"(?<=[.!?…])[ \t]+(?:\w+\s+){{0,3}}?{_SIGN_OFF_WORDS}[\w\s,]{{0,30}}[.!…]*\s*$",
    re.IGNORECASE,
)


# Typographic debris a fast model writes into identifiers and paths. Measured
# live 2026-08-27: gpt-oss on the fast chain joined "Jarvis‑Bar" and
# "Self‑Hosted" with U+2011 (non-breaking hyphen), which a grep for
# "Self-Hosted" in the receiving model never matches. The whole hyphen block
# maps to the hyphen-minus when it sits inside a word; a spaced dash stays a
# spaced dash so an aside written as " – " is not turned into " - " by force.
_TIGHT_HYPHEN_RE: Final[re.Pattern[str]] = re.compile(r"(?<=\w)[‐‑‒–—](?=\w)")
_LOOSE_HYPHEN_RE: Final[re.Pattern[str]] = re.compile(r"[‐‑]")
_SPECIAL_SPACE_RE: Final[re.Pattern[str]] = re.compile(r"[    ​]")
_TRAILING_WS_RE: Final[re.Pattern[str]] = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_RUN_RE: Final[re.Pattern[str]] = re.compile(r"\n{3,}")

# --- Fidelity guards -------------------------------------------------------
#
# The polish pass measures how far the words moved. Here they are supposed to
# move — a prompt is not a tidied transcript — so what is measured instead is
# what got LOST. Two things, both deterministic, both cheap, both fail-open:
#
#   * a literal the user spoke that the prompt does not carry, and
#   * a prompt so much shorter than the transcript that context was thinned.
#
# Neither has an opinion about shape or style. That is the model's judgement,
# and the instruction above is where it is made.

# What counts as a literal worth carrying: an identifier or path
# (``auth_handler``, ``src/app.ts``, ``JarvisBar``), a version or number of
# any length, and anything the user put in quotes. Deliberately NOT
# ordinary words: the prompt is a rewrite, and a guard over every noun would
# reject every honest one.
_IDENTIFIER_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    \b(?:
        [A-Za-z0-9_]+(?:[./\\-][A-Za-z0-9_]+)+        # a.b, src/app.ts, foo-bar
      | [A-Za-z]+_[A-Za-z0-9_]+                       # snake_case
      | [a-z]+[A-Z][A-Za-z0-9]*                       # camelCase
      | [A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*               # PascalCase
    )\b
    """,
    re.VERBOSE,
)
_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"(?<!\w)[+-]?\d+(?:[.,]\d+)*\b")
# Double quotes only. A lone ``'`` is an apostrophe far more often than a
# quotation mark in a transcript ("it's", "don't"), and treating one as an
# opening quote turns the rest of the sentence into a "literal" the prompt is
# then required to reproduce word for word.
_QUOTED_RE: Final[re.Pattern[str]] = re.compile("[\"“„«]([^\"“”„«»\n]{2,60})[\"”»]")

#: How far the prompt may shrink against the transcript before it counts as
#: thinned, and the shortest transcript this is measured on at all. A written
#: prompt is normally LONGER than what was dictated, so this only ever fires
#: on a writer that summarised instead of writing. Short transcripts are
#: exempt: "fix the typo on the login page" is a complete brief at eight
#: words and its prompt may be shorter still.
_MIN_LENGTH_SHARE: Final[float] = 0.40
_MIN_MEASURED_WORDS: Final[int] = 30

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]+", re.UNICODE)

# --- Size guards -------------------------------------------------------------
#
# Prompt Mode is on for every dictation, and not every dictation is a brief.
# The model asks "shall I finish this now?" and the user says "yes"; a
# capable user says "okay, go ahead, but skip the tests". Neither needs a
# prompt, and the maintainer's complaint (2026-08-28) was exactly that they
# got one anyway: a role, sections, a task list, for a "yes". Two answers to
# that, one before the call and one after.

#: A transcript of this many words or fewer never reaches the writer at all.
#: "Ja.", "Nein, lass das.", "Okay, mach weiter.", "fix the typo on the login
#: page" — every one of these is complete as spoken, the ordinary polish pass
#: delivers it with its punctuation, and a prompt written for it could only
#: add what the user did not say. Deterministic, costs nothing, and it keeps
#: the fast chain's per-minute token budget for the dictations that need it.
_MAX_REPLY_WORDS: Final[int] = 8

#: Above that, the writer decides — and is measured. A transcript under
#: ``_MIN_MEASURED_WORDS`` (30) is a remark, a follow-up or an answer, and its
#: message may not grow past this multiple of the spoken word count, with a
#: floor so a ten-word brief may still become a decent paragraph. A message
#: over the line is the "yes" that came back as a document.
_INFLATION_FACTOR: Final[float] = 4.0
_INFLATION_FLOOR_WORDS: Final[int] = 60


# Rendered from the same constants the ``inflated`` and ``dropped_context``
# guards enforce, so the prompt and the guard cannot drift apart.
_SYSTEM_PROMPT: Final[str] = (
    "The user is dictating to an AI agent they are already talking to, usually a "
    "coding agent. Write the message they mean, in their place and in the language "
    "they spoke; it is pasted into that agent's input field as if typed. The agent "
    'sees the conversation, so a reference like "that" stays a reference. The '
    "answer is discarded if it drops an identifier, number or quoted string from "
    "the transcript, asks for a prompt to be written when the user never said "
    f'"prompt", or grows a transcript under {_MIN_MEASURED_WORDS} words past '
    f"{_INFLATION_FACTOR:g} times its length. Return the message between <prompt> "
    "and </prompt>."
)


def is_short_reply(raw: str) -> bool:
    """True when *raw* is too short to want a prompt written for it."""
    return len(_WORD_RE.findall(str(raw or ""))) <= _MAX_REPLY_WORDS


def looks_inflated(raw: str, prompt: str) -> bool:
    """True when a short transcript came back as a long document.

    Only over transcripts under the measured length: a real brief is allowed
    to grow into a structured prompt, and does, but a remark of twenty words
    has nothing in it that a message of a hundred could be faithful to.
    """
    spoken = len(_WORD_RE.findall(str(raw or "")))
    if spoken >= _MIN_MEASURED_WORDS:
        return False
    written = len(_WORD_RE.findall(str(prompt or "")))
    return written > max(_INFLATION_FLOOR_WORDS, int(spoken * _INFLATION_FACTOR))


# --- Level guards ------------------------------------------------------------
#
# A wrong LEVEL: the writer delivered a message whose task is "write a
# prompt". Deterministic to spot, fails open like the rest.

# A task verb followed, within one clause, by the word "prompt" - in the two
# languages the writer is most often asked to write. "Erstelle einen klaren,
# professionellen Prompt" is the live 2026-08-28 output; "write a system
# prompt that" is its English twin. A message that names prompt engineering
# as its subject is the same defect by another route.
_META_PROMPT_RE: Final[re.Pattern[str]] = re.compile(
    r"""
    \b(?:
        erstell\w*|schreib\w*|formulier\w*|verfass\w*|generier\w*|entw[iü]rf\w*|
        entwerf\w*|optimier\w*|verbesser\w*|bau\w*|
        write|writes|create|creates|draft|drafts|generate|generates|compose|
        composes|produce|produces|craft|crafts|design|designs|build|builds|
        optimi[sz]e|optimi[sz]es|improve|improves|rewrite|rewrites
    )\b[^.!?\n]{0,60}?\bprompts?\b
    | \bprompt[- ]?engineer
    """,
    re.IGNORECASE | re.VERBOSE,
)

def asks_for_a_prompt(raw: str, prompt: str) -> bool:
    """True when *prompt* tells its reader to write a prompt the user never asked for.

    The user's own words decide: a transcript that says "prompt" ("kannst du
    mir bitte ein Prompt schreiben") may legitimately want one written, and
    the message may then say so. One that never mentions a prompt cannot have
    asked for one, so a message that assigns prompt writing has answered on
    the wrong level - it wrote the writer's own job description instead of
    the user's message.
    """
    if "prompt" in str(raw or "").casefold():
        return False
    return bool(_META_PROMPT_RE.search(str(prompt or "")))


# --- The switch, and the pause on top of it ---------------------------------
#
# Two levels, because the maintainer asked for two (2026-08-28):
#
#   * ``[dictation].prompt_mode`` is the SETTING. It lives in jarvis.toml, the
#     settings card and the front-page pill own it, and turning it off means
#     the feature is not in use at all — the bar then shows nothing.
#   * the PAUSE is a runtime flag with no home on disk. The bar's sparkle
#     toggles it: "not for the next few dictations", with the setting left
#     exactly as it was, so one click brings it back. It resets on restart and
#     whenever the setting itself is written, because a switch the user just
#     turned on must not come back paused from a click they made yesterday.
#
# Process-wide module state, like the polish pass's breaker: the dictation
# path, the REST routes and the bar all live in the desktop process, and a bool
# assignment is atomic under CPython, so no lock earns its keep here.
_paused: bool = False


def prompt_mode_configured(cfg: Any) -> bool:
    """The SETTING alone — ``[dictation].prompt_mode``, ignoring the pause.

    What a surface asks when it wants to know whether to show the switch at
    all. Off on any config that has not heard of the key.
    """
    return bool(getattr(cfg, "prompt_mode", False))


def prompt_mode_paused() -> bool:
    """Whether the switch is paused from the bar. Never persisted."""
    return _paused


def set_prompt_mode_paused(paused: bool) -> bool:
    """Set the runtime pause; returns the value now in force."""
    global _paused
    _paused = bool(paused)
    return _paused


def prompt_mode_enabled(cfg: Any) -> bool:
    """Whether THIS dictation is to be rewritten: the setting, minus the pause.

    Every call site that asks "does Prompt Mode apply right now" asks this
    one, so pausing from the bar reaches the live dictation path, the REST
    dictation route and the polish probe without any of them knowing a pause
    exists. A surface that wants to draw the switch asks
    :func:`prompt_mode_configured` instead.
    """
    return prompt_mode_configured(cfg) and not _paused


def build_prompt_mode_prompt(protected_terms: Sequence[str] = ()) -> str:
    """The system prompt for one Prompt Mode call.

    ``protected_terms`` are the spellings the writer must carry across
    untouched — the STT dictionary, the wake word, the user's own name. The
    block is the polish pass's, not a copy: what "spell this exactly" looks
    like to a model is one decision.
    """
    return f"{_SYSTEM_PROMPT}\n\n{build_protected_block(protected_terms)}"


def extract_prompt_block(answer: str) -> str:
    """The prompt out of the answer, tolerant of a ragged one.

    The LAST opening tag wins and the closing one is optional: a model that
    names the tag while introducing itself would otherwise hand over its
    introduction, and one that ran out of budget still wrote a usable prompt
    up to where it stopped — the truncation guard is what decides whether it
    is usable. An answer with no tag at all is taken whole, on the assumption
    that the model simply wrote the prompt directly, which is a fine thing to
    have done.

    Whatever comes out is stripped of any of our own tags echoed inside it.
    """
    body = str(answer or "").strip()
    if not body:
        return ""
    opens = list(_PROMPT_OPEN_RE.finditer(body))
    if not opens:
        return _OUR_TAGS_RE.sub("", body).strip()
    rest = body[opens[-1].end() :]
    close = _PROMPT_CLOSE_RE.search(rest)
    return _OUR_TAGS_RE.sub("", rest[: close.start()] if close else rest).strip()


def normalize_prompt_text(text: str) -> str:
    """Undo the typographic debris a fast model leaves behind.

    Deterministic and lossless in meaning: a non-breaking hyphen inside a word
    becomes the hyphen-minus the user's keyboard produces, special spaces
    become spaces, trailing spaces on a line go, and runs of blank lines
    collapse to one paragraph break. Runs BEFORE the guards, so a protected
    spelling the model wrote with a U+2011 still counts as present.
    """
    body = str(text or "")
    body = _TIGHT_HYPHEN_RE.sub("-", body)
    body = _LOOSE_HYPHEN_RE.sub("-", body)
    body = _SPECIAL_SPACE_RE.sub(" ", body)
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    body = _TRAILING_WS_RE.sub("", body)
    body = _BLANK_RUN_RE.sub("\n\n", body)
    return body.strip()


def ends_with_sign_off(text: str) -> bool:
    """Whether *text* closes on a courtesy sign-off, as a line or a sentence."""
    body = str(text or "").strip()
    if not body:
        return False
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if lines and _SIGN_OFF_LINE_RE.match(lines[-1]):
        return True
    return bool(_SIGN_OFF_SENTENCE_RE.search(body))


def strip_closing_sign_off(text: str) -> str:
    """*text* with a trailing courtesy line or sentence removed.

    The instruction asks for a prompt that ends on its substance; this is the
    guarantee. Loops, because a model that writes "Danke!" under "Viele Grüße"
    has written two, and because cutting the last line can expose another
    underneath it. Never strips the whole thing: a line of thanks that is all
    there is stays, and a sentence is only cut when a finished sentence stands
    in front of it.

    Runs AFTER the truncation guard, for the reason that guard exists — a
    prompt that stopped mid-sentence must be caught as damage, not tidied.
    """
    body = str(text or "").strip()
    while True:
        trimmed = _SIGN_OFF_SENTENCE_RE.sub("", body).strip()
        if trimmed != body and trimmed:
            body = trimmed
            continue
        lines = body.splitlines()
        kept = [line.strip() for line in lines if line.strip()]
        if len(kept) < 2 or not _SIGN_OFF_LINE_RE.match(kept[-1]):
            return body
        cut = len(lines)
        while cut > 0 and not lines[cut - 1].strip():
            cut -= 1
        body = "\n".join(lines[: cut - 1]).strip()


def transcript_literals(text: str) -> list[str]:
    """The literals in *text* a faithful prompt has to carry.

    Identifiers and paths, all explicit numbers, and quoted spans.
    Case is preserved in what comes back (the caller folds it) so a log line
    can name the thing that went missing the way the user said it.
    """
    body = str(text or "")
    found: dict[str, str] = {}
    for pattern in (_IDENTIFIER_RE, _NUMBER_RE):
        for match in pattern.finditer(body):
            token = match.group(0)
            found.setdefault(token.casefold(), token)
    for match in _QUOTED_RE.finditer(body):
        token = match.group(1).strip()
        if token:
            found.setdefault(token.casefold(), token)
    return list(found.values())


def lost_literals(raw: str, prompt: str) -> list[str]:
    """Which of the transcript's literals the prompt does not carry."""
    target = str(prompt or "").casefold()
    numbers = set(_NUMBER_RE.findall(target))
    missing = []
    for token in transcript_literals(raw):
        if _NUMBER_RE.fullmatch(token) and token not in numbers:
            missing.append(token)
            continue
        # A spoken CamelCase name may be written with spaces. Accept that
        # spelling repair, without permitting a different identifier or value.
        parts = re.split(r"(?<=[a-z])(?=[A-Z])", token)
        pattern = r"[ \t]*".join(re.escape(part.casefold()) for part in parts)
        if not re.search(r"(?<!\w)" + pattern + r"(?!\w)", target):
            missing.append(token)
    return missing


def looks_thinned(raw: str, prompt: str) -> bool:
    """True when the prompt is too short to still hold what was dictated.

    A word-count proxy, and only over transcripts long enough for the ratio to
    mean anything. A written prompt is normally longer than the dictation, so
    this fires on a writer that summarised rather than wrote — without having
    any opinion about wording.
    """
    spoken = len(_WORD_RE.findall(str(raw or "")))
    if spoken < _MIN_MEASURED_WORDS:
        return False
    written = len(_WORD_RE.findall(str(prompt or "")))
    return written < spoken * _MIN_LENGTH_SHARE


def prompt_guard_reason(raw: str, prompt: str, *, protected: Sequence[str] = ()) -> str:
    """Why *prompt* must not be delivered, or ``""`` when it may.

    Damage and fidelity, never shape. A prompt is allowed to be markdown, to
    carry headings, sections and a role line — v3 rejected exactly that as
    ``markdown``, which was this feature refusing its own purpose. What is
    still worth catching:

    * ``empty`` — nothing came back worth pasting.
    * ``truncated`` — stopped mid-sentence. Reads as complete, is not.
    * ``meta_prompt`` — the message tells its reader to write a prompt, and
      the user never said the word. The writer answered on the wrong level:
      it wrote its own job description instead of the user's message.
    * ``lost_protected_term`` — a spelling the user protected was in the
      transcript and is not in the prompt. The dictionary exists because the
      recognizer gets these wrong; a writer that drops one has undone that.
    * ``dropped_detail`` — file names, identifiers, numbers or quoted strings
      the user spoke are missing. The model is sent looking for something the
      user had already named.
    * ``dropped_context`` — under 40 % of the spoken word count. A written
      prompt is normally longer than the dictation; this short means the
      writer summarised instead.
    * ``inflated`` — a transcript under the measured length came back more
      than four times its size (floor 60 words). A remark or an answer
      became a document.
    """
    body = (prompt or "").strip()
    if not body:
        return "empty"
    if looks_truncated(body):
        return "truncated"
    if asks_for_a_prompt(raw, body):
        return "meta_prompt"
    source = (raw or "").casefold()
    target = body.casefold()
    for term in protected or ():
        needle = str(term or "").strip().casefold()
        if needle and needle in source and needle not in target:
            return "lost_protected_term"
    if lost_literals(raw, body):
        return "dropped_detail"
    if looks_thinned(raw, body):
        return "dropped_context"
    if looks_inflated(raw, body):
        return "inflated"
    return ""


def timeout_budget_s(cfg: Any, override_s: float | None = None) -> float:
    """The wall-clock ceiling for one call, in seconds."""
    if override_s is not None:
        return max(0.05, float(override_s))
    try:
        ms = int(getattr(cfg, "prompt_mode_timeout_ms", _DEFAULT_TIMEOUT_MS))
    except (TypeError, ValueError):
        # A hand-edited jarvis.toml that never reached the validator (a plain
        # object in tests, an older config class): the shipped default is the
        # right answer and nobody needs a log line about a missing knob.
        ms = _DEFAULT_TIMEOUT_MS
    return max(_MIN_TIMEOUT_MS, min(_MAX_TIMEOUT_MS, ms)) / 1000.0


async def compose_prompt(
    raw: str,
    *,
    cfg: Any,
    protected_terms: Sequence[str] = (),
    timeout_s: float | None = None,
    language: str = "",
) -> PolishOutcome:
    """Turn *raw* into the prompt it is asking for. Never raises, never loses text.

    Returns a :class:`~dodaios.dictation.polish.PolishOutcome` so the delivery
    path, the history row and the settings screen read Prompt Mode through the
    same fields they already read the polish pass through. ``text`` is the
    prompt on :data:`STATUS_PROMPTED` and the untouched *raw* on every other
    status — the caller then falls through to whatever it would have done
    without this feature, which is the polish pass.

    ``language`` is the resolved dictation language. The prompt is written in
    the transcript's own language by the instruction, so nothing here depends
    on it; the parameter stays because every caller passes it and because the
    language belongs in the log line when a delivery has to be explained.

    The model is the polish pass's own chain (``[dictation].polish_provider``
    and its ``auto`` order), asked for the family's stronger fast model — the
    one the translate pass uses — because writing a prompt asks more of a
    model than punctuating a sentence.
    """
    started = time.perf_counter()
    source = str(raw or "")

    def _result(
        status: str,
        *,
        provider: str = "",
        model: str = "",
        reason: str = "",
        text: str | None = None,
    ) -> PolishOutcome:
        return PolishOutcome(
            text=source if text is None else text,
            status=status,
            provider=provider,
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            reason=reason,
        )

    try:
        if not prompt_mode_enabled(cfg):
            return _result("off")
        if not source.strip():
            return _result("skipped_short", reason="empty_input")
        if is_short_reply(source):
            # "Ja.", "Nein, lass das.", "okay, go ahead": complete as spoken.
            # The ordinary passes punctuate it; a writer could only add.
            return _result("skipped_short", reason="reply")

        from dodaios.dictation import polish as polish_pass

        breaker = polish_pass._breaker()
        if await breaker.is_open():
            return _result("unavailable", reason="circuit_open")

        budget_s = timeout_budget_s(cfg, timeout_s)
        attempt = polish_pass._Attempt()
        system = build_prompt_mode_prompt(protected_terms)
        user = build_polish_user_message(source)
        try:
            answer = await asyncio.wait_for(
                _call_chain(
                    cfg,
                    system=system,
                    user=user,
                    attempt=attempt,
                    deadline=time.monotonic() + budget_s,
                ),
                budget_s,
            )
        except TimeoutError:
            await breaker.record_failure()
            log.info(
                "dictation prompt mode exceeded its %d ms ceiling on %r; delivering "
                "the transcript to the ordinary passes.",
                int(budget_s * 1000),
                attempt.provider,
            )
            return _result(
                "timeout", provider=attempt.provider, model=attempt.model, reason="deadline"
            )

        if answer is None:
            if attempt.error == "no_credential":
                log.debug(
                    "dictation prompt mode found no usable provider family; "
                    "delivering the transcript to the ordinary passes."
                )
                return _result("unavailable", reason="no_credential")
            await breaker.record_failure()
            status = "local_only" if attempt.on_device_only else "provider_error"
            return _result(
                status,
                provider=attempt.provider,
                model=attempt.model,
                reason=attempt.error or "no_provider",
            )

        await breaker.record_success()

        prompt = normalize_prompt_text(extract_prompt_block(answer))
        reason = prompt_guard_reason(source, prompt, protected=protected_terms)
        if reason:
            log.info(
                "dictation prompt mode answer from %r rejected (%s); delivering the "
                "transcript to the ordinary passes.",
                attempt.provider,
                reason,
            )
            return _result(
                "rejected_drift", provider=attempt.provider, model=attempt.model, reason=reason
            )

        log.debug(
            "dictation prompt mode wrote a %d-word prompt on %r (language %r).",
            len(_WORD_RE.findall(prompt)),
            attempt.provider,
            language or "auto",
        )
        return _result(
            STATUS_PROMPTED,
            provider=attempt.provider,
            model=attempt.model,
            text=strip_closing_sign_off(prompt),
        )
    except Exception:
        # ``Exception``, not ``BaseException``, for the reason the polish pass
        # gives: a cancellation or an interpreter exit belongs to whoever
        # raised it, and swallowing one leaves a task that refuses to die.
        log.warning(
            "dictation prompt mode failed unexpectedly; delivering the transcript "
            "to the ordinary passes.",
            exc_info=True,
        )
        return _result("provider_error", reason="unexpected")


async def _call_chain(
    cfg: Any,
    *,
    system: str,
    user: str,
    attempt: Any,
    deadline: float,
) -> str | None:
    """One walk of the polish family chain. Split out so tests can stand in."""
    from dodaios.dictation.polish import _resolve_and_run

    return await _resolve_and_run(
        cfg,
        system=system,
        user=user,
        attempt=attempt,
        deadline=deadline,
        max_output_tokens=_MAX_OUTPUT_TOKENS,
        temperature=_TEMPERATURE,
        # The family's stronger fast model, exactly as the translate pass asks
        # for it: writing a prompt is a rewrite, not a repunctuation.
        translating=True,
    )


__all__ = [
    "PROMPT_MODE_PROMPT_VERSION",
    "STATUS_PROMPTED",
    "asks_for_a_prompt",
    "build_prompt_mode_prompt",
    "compose_prompt",
    "ends_with_sign_off",
    "extract_prompt_block",
    "is_short_reply",
    "looks_inflated",
    "looks_thinned",
    "lost_literals",
    "normalize_prompt_text",
    "prompt_guard_reason",
    "prompt_mode_configured",
    "prompt_mode_enabled",
    "prompt_mode_paused",
    "set_prompt_mode_paused",
    "strip_closing_sign_off",
    "timeout_budget_s",
    "transcript_literals",
]
