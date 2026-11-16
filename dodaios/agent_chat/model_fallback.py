"""Keep a coding thread going when its model hits a usage or rate limit.

A thread whose model runs out ("You've hit your Fable limit · resets Nov 17
at 12am") used to stop mid-task; the lead then opened a new thread on another
model and told it to read the old one. Now the SAME thread switches to the
next model of its CLI's fallback chain and resumes its own conversation, so
context, history and links stay in one place (``runner_cli.run_cli_turn``).

This module holds the parts that need no CLI process:

* :func:`limit_from_claude_line` / :func:`limit_from_codex_error` read the
  structured signals a CLI's stream carries (Claude Code's
  ``rate_limit_event`` with ``status: rejected``, the assistant message's
  ``error: rate_limit``, the result's ``api_error_status: 429``); text is only
  the fallback (:func:`detect`).
* :func:`chain_for` / :func:`candidates` decide where a thread goes next,
  from ``[agentic_ide] model_fallback_chains`` over :data:`DEFAULT_CHAINS`.
* :func:`note_limited` remembers which model is out until when, so a later
  turn does not walk into a model already known to be spent.
* The notice and report wording, in English; the chat translates the notice
  from its fields (``kind`` ``model_fallback`` / ``model_fallback_exhausted``).
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

log = logging.getLogger(__name__)

#: The thread notice that says the thread moved on to another model.
NOTICE_KIND: Final[str] = "model_fallback"
#: The thread notice that says every model of the chain is limited.
EXHAUSTED_KIND: Final[str] = "model_fallback_exhausted"

#: Each CLI's fallback chain, most preferred first. A thread on a model of
#: the chain moves down it, to the next one that is not limited, never up to
#: a model before it; a thread on a model outside it tries the chain in
#: order. CLIs without an entry do not fall back unless
#: ``[agentic_ide] model_fallback_chains`` names one.
DEFAULT_CHAINS: Final[dict[str, tuple[str, ...]]] = {
    "claude-cli": ("claude-fable-5-2", "claude-opus-5-5", "claude-sonnet-5-5"),
    "codex-cli": ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
}

#: What a resumed thread is told after the switch. The CLI has the whole
#: conversation back; this only says why it stopped and to carry on.
CONTINUE_PROMPT: Final[str] = (
    "Continue where you stopped. The previous model hit its usage limit; this "
    "conversation now runs on {model}. Do not start over and do not repeat what "
    "you already wrote."
)

#: How long a limit without a reset time keeps a model out of the chain.
_USAGE_DEFAULT_S: Final[float] = 3600.0
_RATE_DEFAULT_S: Final[float] = 120.0
#: A reset further away than this is not believed (a parsing slip).
_MAX_RESET_S: Final[float] = 31 * 24 * 3600.0

#: Claude model families a limit message names ("your Fable limit").
_FAMILIES: Final[tuple[str, ...]] = ("fable", "opus", "sonnet", "haiku")
_FAMILY_LIMIT = re.compile(
    r"\b(?P<family>fable|opus|sonnet|haiku)(?:\s+weekly)?\s+limit\b", re.IGNORECASE
)
#: A model the CLI cannot run at all (Claude Code: "There's an issue with the
#: selected model"), or a login it cannot use: the next model of the chain
#: may still work, so the switch goes on past it.
_UNUSABLE_MODEL = re.compile(
    r"issue with the selected model|model_not_found|not_found_error|"
    r"(?:oauth )?token has expired|invalid api key|please run /login",
    re.IGNORECASE,
)
_MONTHS: Final[dict[str, int]] = {
    name: index
    for index, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}
#: "resets Nov 17 at 12am (Europe/Berlin)", "resets Oct 9, 10am", "try again at
#: Nov 21st, 2026 3:41 PM".
_DATED_RESET = re.compile(
    r"(?:resets|try again at|available again at)\s+(?:on\s+)?"
    r"(?P<month>[A-Z][a-z]{2,8})\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?:(?P<year>\d{4}),?\s+)?(?:at\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d\d))?\s*(?P<meridiem>[ap]\.?m\.?)?"
    r"(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?",
    re.IGNORECASE,
)
#: "resets 3pm (Europe/Berlin)": a time of day, the next one.
_CLOCK_RESET = re.compile(
    r"resets\s+(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d\d))?\s*(?P<meridiem>[ap]\.?m\.?)"
    r"(?:\s*\((?P<tz>[A-Za-z_]+(?:/[A-Za-z_+-]+)*)\))?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class LimitHit:
    """A model that refused for its limit, as one turn saw it."""

    #: ``usage`` (a plan allowance is spent) or ``rate`` (requests too fast).
    kind: str
    #: The family the limit names ("Fable"), "" when it names none.
    family: str = ""
    #: When the model is usable again (epoch seconds), if known.
    resets_at: float | None = None
    #: ``stream`` (the CLI's structured signal) or ``text`` (its words).
    source: str = "text"
    #: The CLI's own sentence, for the log and the report.
    message: str = ""


@dataclass(slots=True)
class LimitSignal:
    """What a CLI's stream said about a limit during one run (translator state)."""

    rejected: bool = False
    rate_limited: bool = False
    usage_limit: bool = False
    resets_at: float | None = None
    limit_type: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def hit(self) -> bool:
        return self.rejected or self.rate_limited or self.usage_limit


def _epoch(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):  # a malformed field: no reset time, not a failure
        return None
    if number > 1e12:  # milliseconds
        number /= 1000.0
    return number if number > 0 else None


def limit_from_claude_line(signal: LimitSignal, obj: dict[str, Any]) -> None:
    """Fold one Claude Code stream line into ``signal`` (in place).

    The lines that carry it, as claude 2.1.323 prints them at a spent limit:
    ``rate_limit_event`` with ``rate_limit_info.status == "rejected"`` and
    ``resetsAt``; an ``assistant`` line with ``error: "rate_limit"`` (the
    synthetic message whose text is the limit sentence); and the ``result``
    with ``api_error_status: 429``, ``api_error_type: "rate_limit_error"`` and
    ``api_error: "usage_limit_reached"`` for a spent allowance.
    """
    kind = obj.get("type")
    if kind == "rate_limit_event":
        info = obj.get("rate_limit_info")
        if isinstance(info, dict) and str(info.get("status") or "") == "rejected":
            signal.rejected = True
            signal.resets_at = _epoch(info.get("resetsAt")) or signal.resets_at
            signal.limit_type = str(info.get("rateLimitType") or signal.limit_type)
        return
    if kind == "assistant" and str(obj.get("error") or "") == "rate_limit":
        signal.rate_limited = True
        return
    if kind == "result" and obj.get("is_error"):
        status = obj.get("api_error_status")
        if status == 429 or str(obj.get("api_error_type") or "") == "rate_limit_error":
            signal.rate_limited = True
        if str(obj.get("api_error") or "") == "usage_limit_reached":
            signal.usage_limit = True


def limit_from_codex_error(signal: LimitSignal, err: Any) -> None:
    """Fold a Codex error object into ``signal`` when it carries a limit code."""
    if not isinstance(err, dict):
        return
    info = err.get("codex_error_info") or err.get("codexErrorInfo") or err.get("type") or ""
    code = str(info if not isinstance(info, dict) else next(iter(info), "")).lower()
    if code.replace("_", "") in {"usagelimitexceeded", "usagelimitreached"}:
        signal.usage_limit = True
        resets = _epoch(err.get("resets_at"))
        if resets is None:
            seconds = _epoch(err.get("resets_in_seconds"))
            resets = time.time() + seconds if seconds else None
        signal.resets_at = resets or signal.resets_at
    elif "ratelimit" in code.replace("_", ""):
        signal.rate_limited = True


def family_of(model: str) -> str:
    """The Claude family a model id belongs to ("Fable"), "" for any other."""
    low = (model or "").lower()
    for name in _FAMILIES:
        if name in low:
            return name.capitalize()
    return ""


def _zone(name: str | None) -> Any:
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 — an unknown zone name: local time is the honest guess
        return None


def _hour24(hour: int, meridiem: str | None) -> int | None:
    mark = (meridiem or "").lower().replace(".", "")
    if mark:
        if not 1 <= hour <= 12:
            return None
        if mark == "pm" and hour != 12:
            return hour + 12
        if mark == "am" and hour == 12:
            return 0
        return hour
    return hour if 0 <= hour <= 23 else None


def parse_reset(text: str | None, *, now: float | None = None) -> float | None:
    """The epoch second a limit sentence says the model is usable again, or ``None``."""
    if not text:
        return None
    base = time.time() if now is None else now
    match = _DATED_RESET.search(text)
    if match and match.group("month").lower().rstrip(".") in _MONTHS:
        zone = _zone(match.group("tz"))
        hour = _hour24(int(match.group("hour")), match.group("meridiem"))
        if hour is not None:
            here = datetime.fromtimestamp(base, tz=zone) if zone else datetime.fromtimestamp(base)
            year = int(match.group("year") or here.year)
            try:
                at = here.replace(
                    year=year,
                    month=_MONTHS[match.group("month").lower().rstrip(".")],
                    day=int(match.group("day")),
                    hour=hour,
                    minute=int(match.group("minute") or 0),
                    second=0,
                    microsecond=0,
                )
            except ValueError:  # "Feb 30": not a date
                at = None
            if at is not None:
                if not match.group("year") and at.timestamp() < base - 86400:
                    at = at.replace(year=year + 1)
                stamp = at.timestamp()
                if 0 < stamp - base <= _MAX_RESET_S:
                    return stamp
    match = _CLOCK_RESET.search(text)
    if match:
        zone = _zone(match.group("tz"))
        hour = _hour24(int(match.group("hour")), match.group("meridiem"))
        if hour is not None:
            here = datetime.fromtimestamp(base, tz=zone) if zone else datetime.fromtimestamp(base)
            at = here.replace(
                hour=hour, minute=int(match.group("minute") or 0), second=0, microsecond=0
            )
            stamp = at.timestamp()
            if stamp <= base:
                stamp += 86400
            return stamp
    try:
        from dodaios.brain import seat_health

        return seat_health.parse_reset_time(text, now=base)
    except Exception:  # noqa: BLE001 — no reset time is a valid answer
        return None


def detect(
    error: str | None, signal: LimitSignal | None = None, *, model: str = ""
) -> LimitHit | None:
    """Whether a failed run was refused for a usage or rate limit.

    The stream's own signal decides first; the error text only when the
    stream said nothing (a CLI without such lines, or a run that died before
    it printed them). A tool failure that merely mentions a limit is not one:
    text needs the seat classifier's quota / rate verdict.
    """
    text = str(error or "")
    family_match = _FAMILY_LIMIT.search(text)
    family = family_match.group("family").capitalize() if family_match else ""
    if not family and signal is not None:
        # Claude Code's ``rateLimitType`` names a model's own window
        # ("seven_day_opus") where the sentence does not.
        family = family_of(signal.limit_type)
    if signal is not None and signal.hit:
        long_wait = (
            signal.resets_at is not None and signal.resets_at - time.time() > _RATE_DEFAULT_S
        )
        kind = "usage" if (signal.usage_limit or signal.rejected or long_wait) else "rate"
        return LimitHit(
            kind=kind,
            family=family,
            resets_at=signal.resets_at or parse_reset(text),
            source="stream",
            message=text,
        )
    if not text:
        return None
    try:
        from dodaios.brain import seat_health

        verdict = seat_health.classify_seat_failure(text)
    except Exception:  # noqa: BLE001 — no classifier: no fallback, the error stands
        return None
    if verdict == seat_health.CLASS_QUOTA:
        kind = "usage"
    elif verdict == seat_health.CLASS_RATE:
        kind = "rate"
    else:
        return None
    return LimitHit(kind=kind, family=family, resets_at=parse_reset(text), message=text)


def switch_helps(hit: LimitHit) -> bool:
    """Whether another model can carry on past ``hit``.

    Only a spent allowance of one model family ("You've hit your Fable
    limit") is left behind by switching. A limit that names no family is the
    whole account's (every model of the chain shares it), and a rate limit is
    a burst that passes in a minute or two: switching would only walk the
    chain and leave the thread on a lesser model for nothing.
    """
    return hit.kind == "usage" and bool(hit.family)


def model_unusable(error: str | None) -> bool:
    """Whether a run failed because its model (or the login) cannot be used at all.

    Such a model is skipped and the next one of the chain is tried; any other
    failure ends the switch with its own error.
    """
    text = str(error or "")
    if not text:
        return False
    if _UNUSABLE_MODEL.search(text):
        return True
    try:
        from dodaios.brain import seat_health

        return seat_health.classify_seat_failure(text) in {
            seat_health.CLASS_MODEL,
            seat_health.CLASS_AUTH,
        }
    except Exception:  # noqa: BLE001 — no classifier: the failure stands
        return False


# ------------------------------------------------------------- the setting


def enabled() -> bool:
    """``[agentic_ide] model_fallback``; on unless switched off."""
    try:
        from dodaios.core.config import load_config

        return bool(getattr(load_config().agentic_ide, "model_fallback", True))
    except Exception:  # noqa: BLE001 — an unreadable config keeps the default
        return True


def _configured_chains() -> dict[str, Any]:
    try:
        from dodaios.core.config import load_config

        raw = getattr(load_config().agentic_ide, "model_fallback_chains", None)
    except Exception:  # noqa: BLE001 — an unreadable config keeps the defaults
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def chain_for(runner: str, configured: dict[str, Any] | None = None) -> tuple[str, ...]:
    """The fallback chain of ``runner``: the configured one, else the default.

    A configured empty list switches fallback off for that CLI.
    """
    chains = _configured_chains() if configured is None else configured
    if runner in chains:
        value = chains[runner]
        if isinstance(value, str):
            value = [part for part in value.split(",")]
        if isinstance(value, list | tuple):
            return tuple(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))
        return ()
    return DEFAULT_CHAINS.get(runner, ())


def effective_chains() -> dict[str, list[str]]:
    """Every CLI's chain as it applies now (defaults with the configured ones on top)."""
    configured = _configured_chains()
    names = {*DEFAULT_CHAINS, *configured}
    return {name: list(chain_for(name, configured)) for name in sorted(names)}


# ------------------------------------------------- models known to be spent

_LOCK = threading.Lock()
#: (runner, seat, family-or-model) -> epoch second it is usable again.
_LIMITED: dict[tuple[str, str, str], float] = {}


def _key(runner: str, seat: str, model: str) -> tuple[str, str, str]:
    return runner, seat or "", (family_of(model) or model or "").lower()


def note_limited(runner: str, seat: str, model: str, hit: LimitHit) -> float:
    """Remember that ``model`` is out on ``seat``; returns until when."""
    now = time.time()
    until = hit.resets_at if hit.resets_at and hit.resets_at > now else None
    if until is None:
        until = now + (_USAGE_DEFAULT_S if hit.kind == "usage" else _RATE_DEFAULT_S)
    with _LOCK:
        for stale in [k for k, v in _LIMITED.items() if v <= now]:
            _LIMITED.pop(stale, None)
        for name in {model, hit.family}:
            if name:
                _LIMITED[_key(runner, seat, name)] = until
    return until


def limited_until(runner: str, seat: str, model: str) -> float | None:
    """When ``model`` is usable again on ``seat``, if it is known to be out now."""
    with _LOCK:
        until = _LIMITED.get(_key(runner, seat, model))
    return until if until is not None and until > time.time() else None


def reset() -> None:
    """Forget every remembered limit (tests)."""
    with _LOCK:
        _LIMITED.clear()


def candidates(
    runner: str,
    current: str,
    *,
    hit: LimitHit | None = None,
    tried: set[str] | frozenset[str] = frozenset(),
    seat: str = "",
    chain: tuple[str, ...] | None = None,
) -> list[str]:
    """The models a limited thread may move to, in the order to try them.

    Down the chain from the current model: a thread on Opus goes on to Sonnet,
    never up to Fable (its limit is no reason to pay for a larger model). A
    model outside the chain tries the chain from the top. Never the current
    model, one tried this turn, one of the family the limit names (a "Fable
    limit" spends every Fable model), or one still known to be out on this
    seat.
    """
    order = chain_for(runner) if chain is None else chain
    at = _position(order, current)
    if at is not None:
        order = order[at + 1 :]
    spent = {current, *tried}
    families = {family_of(m) for m in spent if family_of(m)}
    if hit is not None and hit.family:
        families.add(hit.family)
    elif family_of(current):
        families.add(family_of(current))
    out: list[str] = []
    for model in order:
        if model in spent or model in out:
            continue
        if family_of(model) and family_of(model) in families:
            continue
        if limited_until(runner, seat, model) is not None:
            continue
        out.append(model)
    return out


def _position(chain: tuple[str, ...], model: str) -> int | None:
    """Where ``model`` sits in ``chain``: by id, else by its family."""
    if model in chain:
        return chain.index(model)
    family = family_of(model)
    if family:
        for index, entry in enumerate(chain):
            if family_of(entry) == family:
                return index
    return None


# ------------------------------------------------------------- the words


def model_label(model: str) -> str:
    """The short name a person knows a model by ("claude-opus-5-5" -> "Opus 5.5")."""
    picked = (model or "").strip()
    if not picked:
        return "the default model"
    try:
        from dodaios.agent_chat import catalog

        rows = (*catalog.claude_code_models(), *catalog.CODEX_FALLBACK_MODELS)
        for row in rows:
            if row.id == picked and row.label:
                return row.label.removeprefix("Claude ").strip()
    except Exception:  # noqa: BLE001 — the id below is still a name
        log.debug("Model fallback: catalog unavailable for labels")
    match = re.fullmatch(r"claude-([a-z]+)-(\d+)(?:-(\d{1,2}))?(?:-\d{8})?(\[1m\])?", picked)
    if match:
        version = match.group(2) + (f".{match.group(3)}" if match.group(3) else "")
        return f"{match.group(1).capitalize()} {version}" + (" (1M)" if match.group(4) else "")
    return picked


def limit_label(hit: LimitHit, model: str) -> str:
    """What ran out, as the notice names it ("Fable", "Opus 5.5")."""
    return hit.family or model_label(model)


def _when(at: float | None) -> str:
    if not at:
        return ""
    moment = datetime.fromtimestamp(at)
    return f"{moment:%b} {moment.day}, {moment:%H:%M}"


def iso_utc(at: float | None) -> str:
    """``at`` as the "2026-11-16T23:00Z" form the failed-turn card reads."""
    if not at:
        return ""
    return datetime.fromtimestamp(at, tz=UTC).strftime("%Y-%m-%dT%H:%MZ")


def switch_notice(
    hit: LimitHit, from_model: str, to_model: str, until: float | None
) -> dict[str, Any]:
    """The thread notice for a move to ``to_model``; the chat words it from the fields."""
    what = limit_label(hit, from_model)
    to = model_label(to_model)
    if hit.kind == "rate":
        text = f"{what} is rate limited – continued on {to}."
    elif until:
        text = f"{what} limit reached until {_when(until)} – continued on {to}."
    else:
        text = f"{what} limit reached – continued on {to}."
    return {
        "kind": NOTICE_KIND,
        "text": text,
        "limit": hit.kind,
        "limit_label": what,
        "from_model": from_model,
        "from_label": model_label(from_model),
        "to_model": to_model,
        "to_label": to,
        "resets_at": until,
        "source": hit.source,
    }


@dataclass(frozen=True, slots=True)
class Spent:
    """One model of the chain that refused this turn."""

    model: str
    label: str
    until: float | None


def exhausted_notice(spent: list[Spent]) -> dict[str, Any]:
    """The thread notice when every model of the chain is limited."""
    parts = [f"{s.label} until {_when(s.until)}" if s.until else s.label for s in spent]
    first = min((s.until for s in spent if s.until), default=None)
    text = "Every model this thread can switch to is at its limit (" + "; ".join(parts) + ")."
    if first:
        text += f" Stopped; the first one is free again {_when(first)}."
    else:
        text += " Stopped."
    return {
        "kind": EXHAUSTED_KIND,
        "text": text,
        "models": [{"model": s.model, "label": s.label, "resets_at": s.until} for s in spent],
        "resets_at": first,
    }


def exhausted_error(spent: list[Spent]) -> str:
    """The turn's error when the chain ran out: the card reads "usage limit" and the time."""
    labels = ", ".join(s.label for s in spent)
    first = min((s.until for s in spent if s.until), default=None)
    text = f"Usage limit reached on every model this thread can use ({labels})."
    if first:
        text += f" The first one resets at {iso_utc(first)}."
    return text


def report_line(events: list[dict[str, Any]], turn_id: str) -> str:
    """One sentence for the lead's report: which model finished a turn that switched."""
    moves = [
        (event.get("payload") or {})
        for event in events
        if event.get("kind") == "notice"
        and (event.get("payload") or {}).get("kind") in {NOTICE_KIND, EXHAUSTED_KIND}
        and (not turn_id or str((event.get("payload") or {}).get("turn_id") or "") == turn_id)
    ]
    if not moves:
        return ""
    last = moves[-1]
    if last.get("kind") == EXHAUSTED_KIND:
        return str(last.get("text") or "")
    first = moves[0]
    return (
        f"Finished on {last.get('to_label') or 'another model'}: "
        f"{first.get('limit_label') or first.get('from_label') or 'the first model'} hit its "
        f"{'rate' if first.get('limit') == 'rate' else 'usage'} limit"
        + (f" (until {_when(first.get('resets_at'))})" if first.get("resets_at") else "")
        + " and the thread switched models in place."
    )


__all__ = [
    "CONTINUE_PROMPT",
    "DEFAULT_CHAINS",
    "EXHAUSTED_KIND",
    "NOTICE_KIND",
    "LimitHit",
    "LimitSignal",
    "Spent",
    "candidates",
    "chain_for",
    "detect",
    "effective_chains",
    "enabled",
    "exhausted_error",
    "exhausted_notice",
    "family_of",
    "limit_from_claude_line",
    "limit_from_codex_error",
    "limit_label",
    "limited_until",
    "model_label",
    "model_unusable",
    "note_limited",
    "parse_reset",
    "report_line",
    "reset",
    "switch_helps",
    "switch_notice",
]
