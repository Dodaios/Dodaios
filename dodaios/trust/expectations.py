"""Predict before acting: an optional expectation on side-effect calls.

A side-effect tool on a lead surface accepts an optional ``expect`` argument,
``{"outcome": "<what should be true afterwards>", "confidence": 0..1}``. It is
added to the tool's schema by one shared function (:func:`inject_expect`), never
by hand per tool, and the ``ToolExecutor`` strips it before the tool runs. A
call without it behaves exactly as before: no rejection, no nagging.

After the call, :func:`compare` checks the expectation against what the call
returned and its receipt, by fixed rules and without a model call:

* an expected success against an error (or the reverse) is a miss or a hit;
* key facts named in the outcome (a recipient, a time, a date, a path, a URL,
  an exit code) must show up in the call's arguments, result or receipt: all
  present is a hit, a different value of the same kind is a miss, and a kind of
  fact the call shows nothing about leaves the verdict ``unknown``.

The verdict is stored with the audit row (``dodaios.trust.audit``) and feeds
the calibration report (``dodaios.trust.calibration``).

Low confidence (:data:`LOW_CONFIDENCE`) on an irreversible action
(:func:`is_irreversible`) turns into a verify-first step in the executor: a dry
run where the tool offers one (:func:`dry_run_args`), otherwise one ask through
the existing approval card. Reversible work is never interrupted.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Final

from .hard_limits import bare_tool

log = logging.getLogger(__name__)

EXPECT_KEY: Final = "expect"

HIT: Final = "hit"
MISS: Final = "miss"
UNKNOWN: Final = "unknown"
VERDICTS: Final[tuple[str, ...]] = (HIT, MISS, UNKNOWN)

#: A stated confidence below this on an irreversible action means "verify first".
LOW_CONFIDENCE: Final = 0.5

#: ``origin.EFFECTS`` values that cannot be taken back with one more call.
IRREVERSIBLE_EFFECTS: Final[frozenset[str]] = frozenset({"outbound", "destructive", "spend"})

_OUTCOME_MAX = 300

EXPECT_DESCRIPTION: Final = (
    "Optional. Before acting, state what you expect to be true afterwards and how sure you "
    "are, e.g. {\"outcome\": \"mail to ana@example.com is sent\", \"confidence\": 0.9}. "
    "Name concrete facts (recipient, time, file path) so the result can be checked. "
    "Low confidence on an irreversible action makes the app check first."
)


def expect_property() -> dict[str, Any]:
    """The JSON-schema property every side-effect tool gets."""
    return {
        "type": "object",
        "description": EXPECT_DESCRIPTION,
        "properties": {
            "outcome": {"type": "string", "description": "What you expect to be true afterwards."},
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "description": "Probability (0 to 1) that the outcome will be true.",
            },
        },
    }


def _properties(schema: Any) -> dict[str, Any] | None:
    props = schema.get("properties") if isinstance(schema, dict) else None
    return props if isinstance(props, dict) else None


def inject_expect(schema: Any) -> Any:
    """A copy of ``schema`` with the ``expect`` property; the input is never changed.

    A schema that is not an object schema, or that already has its own
    ``expect`` argument, is returned as it is.
    """
    if not isinstance(schema, dict) or schema.get("type") not in (None, "object"):
        return schema
    props = schema.get("properties", {})
    if not isinstance(props, dict) or EXPECT_KEY in props:
        return schema
    return {**schema, "type": "object", "properties": {**props, EXPECT_KEY: expect_property()}}


def wants_expect(tool: Any) -> bool:
    """Whether a tool can change something, from its trusted metadata only."""
    from dodaios.safety.origin import tool_effect

    props = _properties(getattr(tool, "schema", None))
    if props is not None and EXPECT_KEY in props:
        return False  # the tool's own argument; never ours
    if callable(getattr(tool, "read_only_for_args", None)):
        return True  # a mixed tool: some of its calls act
    if getattr(tool, "read_only", False) is True:
        return False
    try:
        effect = tool_effect(tool, {})
    except Exception:  # noqa: BLE001 - unsure means "may act"
        effect = "unknown"
    if effect in ("modify", "outbound", "destructive", "spend"):
        return True
    tier = str(getattr(tool, "risk_tier", "") or "")
    return bool(getattr(tool, "is_action_tool", False)) or tier not in ("", "safe")


def schema_for(tool: Any) -> Any:
    """The schema a model sees for ``tool``: with ``expect`` when the tool acts."""
    schema = getattr(tool, "schema", None)
    try:
        return inject_expect(schema) if wants_expect(tool) else schema
    except Exception:  # noqa: BLE001 - a broken tool object keeps its own schema
        log.debug("expect: schema injection skipped", exc_info=True)
        return schema


# ---------------------------------------------------------------- expectation


@dataclass(frozen=True, slots=True)
class Expectation:
    outcome: str = ""
    confidence: float | None = None


def parse_expect(raw: Any) -> Expectation | None:
    """A lenient read of the model's ``expect``; ``None`` when there is nothing usable."""
    if isinstance(raw, str):
        text = raw.strip()
        if text[:1] == "{":
            try:
                raw = json.loads(text)
            except ValueError:
                raw = {"outcome": text}
        else:
            raw = {"outcome": text}
    if not isinstance(raw, dict):
        return None
    outcome = raw.get("outcome")
    outcome = " ".join(outcome.split())[:_OUTCOME_MAX] if isinstance(outcome, str) else ""
    confidence: float | None = None
    value = raw.get("confidence")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        confidence = min(1.0, max(0.0, float(value)))
    elif isinstance(value, str):
        try:
            confidence = min(1.0, max(0.0, float(value.strip().rstrip("%")) / (
                100.0 if value.strip().endswith("%") else 1.0)))
        except ValueError:
            confidence = None
    if not outcome and confidence is None:
        return None
    return Expectation(outcome, confidence)


def split_expect(tool: Any, args: dict[str, Any]) -> tuple[dict[str, Any], Expectation | None]:
    """``args`` without ``expect``, and the parsed expectation.

    A tool that declares its own ``expect`` argument keeps it untouched.
    """
    if not isinstance(args, dict) or EXPECT_KEY not in args:
        return args, None
    props = _properties(getattr(tool, "schema", None))
    if props is not None and EXPECT_KEY in props:
        return args, None
    clean = {k: v for k, v in args.items() if k != EXPECT_KEY}
    return clean, parse_expect(args[EXPECT_KEY])


# ----------------------------------------------------------------- tool class


def tool_class(tool_name: str) -> str:
    """The calibration class of a tool: ``mail``, ``calendar``, ``file``, ..., ``other``."""
    key = bare_tool(tool_name).lower().replace("-", "_")
    if key.startswith(("delegate", "spawn", "dispatch", "multi_spawn", "message_agent")):
        return "delegation"
    if "mail" in key or "outlook" in key:
        return "mail"
    if "calendar" in key:
        return "calendar"
    if key in ("write", "edit", "notebookedit") or "file" in key:
        return "file"
    if key in ("run_shell", "runcommand", "bash") or "shell" in key or key.startswith("cli_"):
        return "shell"
    if "github" in key:
        return "github"
    if any(w in key for w in ("slack", "telegram", "discord", "whatsapp", "signal", "sms")):
        return "message"
    return "other"


def is_irreversible(effect: str) -> bool:
    return effect in IRREVERSIBLE_EFFECTS


# ------------------------------------------------------------------- compare

_NO_ERROR = re.compile(r"\b(?:no|without(?: any)?|zero)\s+(?:errors?|failures?)\b|error-free", re.I)
_FAILURE = re.compile(
    r"\b(?:fail(?:s|ed|ure)?|errors?|refus\w*|reject\w*|denied|bounc\w*|won't|will not|cannot|"
    r"can't|not\s+(?:be\s+)?(?:sent|created|found|possible|allowed|saved|written|delivered)|"
    r"doesn't exist|does not exist)\b",
    re.I,
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://[^\s\"'<>)\]]+")
_DATE = re.compile(r"(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)")
_TIME = re.compile(r"(?<![\d:+-])(\d{1,2}):(\d{2})(?!\d)")
_EXT = (
    "py|js|ts|tsx|jsx|json|md|txt|csv|html|css|yml|yaml|toml|ini|cfg|sh|ps1|bat|pdf|docx|xlsx|"
    "pptx|png|jpg|jpeg|gif|svg|zip|log|sql|rs|go|java|c|cpp|h"
)
_PATH = re.compile(
    rf"(?:(?:[A-Za-z]:[\\/]|~[\\/]|/)[^\s\"'<>|*?]+|[\w.-]+(?:[\\/][\w.-]+)*\.(?:{_EXT})\b)"
)
_EXIT = re.compile(r"\bexit(?:s|ed)?(?:\s+(?:code|status|with))*\s*(?:code\s*)?(-?\d+)", re.I)


def _norm_path(value: str) -> str:
    return value.replace("\\", "/").strip(" .,;:").lower()


def _times(text: str) -> set[tuple[int, int]]:
    return {(int(h), int(m)) for h, m in _TIME.findall(text) if int(h) < 24 and int(m) < 60}


def _facts(text: str) -> dict[str, set[Any]]:
    """The checkable facts in a piece of text, by kind."""
    urls = {u.rstrip(".,;:").lower() for u in _URL.findall(text)}
    rest = _URL.sub(" ", text)
    emails = {e.lower() for e in _EMAIL.findall(rest)}
    rest = _EMAIL.sub(" ", rest)
    paths = {_norm_path(p) for p in _PATH.findall(rest)}
    return {
        "email": emails,
        "url": urls,
        "date": set(_DATE.findall(rest)),
        "time": _times(rest),
        "path": {p for p in paths if len(p) > 2},
    }


def _flatten(value: Any, limit: int = 20_000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:limit]
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except (TypeError, ValueError):
        return str(value)[:limit]


def _haystack(args: dict[str, Any], output: Any, receipt: dict[str, Any] | None) -> str:
    parts = [_flatten(args), _flatten(output)]
    if receipt:
        parts += [
            _flatten(receipt.get("summary")),
            _flatten(receipt.get("evidence")),
            _flatten(receipt.get("links")),
        ]
    return "\n".join(p for p in parts if p).replace("\\\\", "\\")


def _path_found(expected: str, haystack_norm: str) -> bool:
    base = expected.rsplit("/", 1)[-1]
    return expected in haystack_norm or bool(base) and base in haystack_norm


def expects_failure(outcome: str) -> bool:
    return bool(_FAILURE.search(_NO_ERROR.sub(" ", outcome or "")))


def compare(
    expectation: Expectation,
    *,
    tool_name: str,
    args: dict[str, Any],
    succeeded: bool,
    output: Any = None,
    receipt: dict[str, Any] | None = None,
) -> str:
    """``hit`` / ``miss`` / ``unknown`` for one finished call. Never raises."""
    try:
        return _compare(expectation, tool_name, args, succeeded, output, receipt)
    except Exception:  # noqa: BLE001 - a comparison that breaks says nothing
        log.debug("expect: comparison failed", exc_info=True)
        return UNKNOWN


def _compare(
    expectation: Expectation,
    tool_name: str,
    args: dict[str, Any],
    succeeded: bool,
    output: Any,
    receipt: dict[str, Any] | None,
) -> str:
    outcome = expectation.outcome
    wants_fail = expects_failure(outcome)
    cls = tool_class(tool_name)
    code = _exit_code(receipt) if cls == "shell" else None

    if not succeeded:
        return HIT if wants_fail else MISS
    if wants_fail:
        if cls != "shell":
            return MISS  # an error was expected, the call succeeded
        if code is None:
            return UNKNOWN
        return HIT if code != 0 else MISS

    verdicts: list[str] = []
    if cls == "shell" and code is not None:
        stated = _EXIT.search(outcome)
        verdicts.append(HIT if code == (int(stated.group(1)) if stated else 0) else MISS)

    want_facts = _facts(outcome)
    if any(want_facts.values()):
        hay = _haystack(args, output, receipt)
        have = _facts(hay)
        hay_norm = hay.replace("\\", "/").lower()
        for kind, wanted in want_facts.items():
            if not wanted:
                continue
            if kind == "path":
                found = {p for p in wanted if _path_found(p, hay_norm)}
                comparable = bool(have["path"])
            else:
                found = wanted & have[kind]
                comparable = bool(have[kind])
            if found == wanted:
                verdicts.append(HIT)
            elif comparable:
                verdicts.append(MISS)
            else:
                verdicts.append(UNKNOWN)

    if MISS in verdicts:
        return MISS
    if UNKNOWN in verdicts:
        return UNKNOWN
    return HIT  # no fact to check, or every fact matched: the call itself succeeded


def _exit_code(receipt: dict[str, Any] | None) -> int | None:
    evidence = (receipt or {}).get("evidence")
    value = evidence.get("exit_code") if isinstance(evidence, dict) else None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def prediction_record(
    expectation: Expectation,
    verdict: str,
    *,
    tool_name: str,
    seat: str = "",
) -> dict[str, Any]:
    """What the audit row keeps about one prediction."""
    return {
        "outcome": expectation.outcome,
        "confidence": expectation.confidence,
        "verdict": verdict,
        "class": tool_class(tool_name),
        "seat": seat,
    }


# --------------------------------------------------------------- low confidence


def is_low_confidence(expectation: Expectation | None) -> bool:
    return (
        expectation is not None
        and expectation.confidence is not None
        and expectation.confidence < LOW_CONFIDENCE
    )


def dry_run_args(tool: Any, args: dict[str, Any]) -> dict[str, Any] | None:
    """Arguments for a side-effect-free preview of this call, when the tool offers one.

    A tool opts in with ``dry_run_args(args) -> dict | None`` (the arguments of
    a call that only shows what would happen), or by having a boolean
    ``dry_run`` property in its schema.
    """
    hook = getattr(tool, "dry_run_args", None)
    if callable(hook):
        try:
            found = hook(dict(args))
        except Exception:  # noqa: BLE001 - a broken hook means "no preview"
            log.debug("expect: dry_run_args failed for %s", getattr(tool, "name", "?"))
            return None
        return dict(found) if isinstance(found, dict) else None
    props = _properties(getattr(tool, "schema", None)) or {}
    spec = props.get("dry_run")
    if isinstance(spec, dict) and spec.get("type") == "boolean":
        return {**args, "dry_run": True}
    return None


__all__ = [
    "EXPECT_KEY",
    "HIT",
    "LOW_CONFIDENCE",
    "MISS",
    "UNKNOWN",
    "VERDICTS",
    "Expectation",
    "compare",
    "dry_run_args",
    "expect_property",
    "inject_expect",
    "is_irreversible",
    "is_low_confidence",
    "parse_expect",
    "prediction_record",
    "schema_for",
    "split_expect",
    "tool_class",
    "wants_expect",
]
