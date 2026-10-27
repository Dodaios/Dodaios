"""Readable reasons for failed agent-chat turns.

A runtime that fails can leave anything as its last words: a stderr dump with
log lines, part of the agent's own system prompt, the internal gateway URL,
paths under the person's home folder, or a bare JSON-RPC "Internal error".
None of that belongs on the red failed-turn card. :func:`readable_turn_error`
turns such an error into one short sentence the person can act on, and keeps
the raw text only as redacted ``details`` (the card folds them behind a
"Technical details" disclosure; the log gets the same redacted text).

Short, deliberate reasons a runner already wrote (a usage limit, a context
window, a missing key) pass through unchanged: other code matches on them.
"""

from __future__ import annotations

import os
import re
from typing import Final

#: What the card says while a runtime migrates its own database.
RUNTIME_UPDATING: Final = "The agent runtime is updating its data. Try again in a moment."
#: What the card says while a runtime has not finished starting the agent.
STILL_STARTING: Final = "The agent is still starting up. Try again in a moment."
#: What a turn cut off by an app restart says.
APP_RESTARTED: Final = "The app restarted while this turn was running. Send it again."

#: The display name of each runner the person never sees by its id.
_RUNNER_LABELS: Final[dict[str, str]] = {
    "hermes-cli": "Hermes",
    "openclaw-cli": "OpenClaw",
    "claude-cli": "Claude Code",
    "codex-cli": "Codex",
    "agy-cli": "Antigravity",
    "grok-cli": "Grok Build",
    "opencode-cli": "OpenCode",
    "kimi-cli": "Kimi Code",
    "glm-cli": "GLM Coding Plan",
    "dsh-cli": "DeepSeek Harness",
    "cursor-cli": "Cursor CLI",
    "api": "The model",
    "brain": "The model",
}

#: Providers that run on this computer when the provider spec cannot be read.
_LOCAL_FALLBACK: Final = frozenset({"ollama", "local-openai", "lmstudio", "llama-cpp", "llama_cpp"})

_SCHEMA_MIGRATION = re.compile(r"schema version.*doctor --fix", re.IGNORECASE | re.DOTALL)
_STARTUP_INSPECTION = re.compile(r"has not completed startup inspection", re.IGNORECASE)
_STALL = re.compile(
    r"^(?P<runner>[\w.-]+) stopped responding \(nothing for (?P<minutes>\d+) minutes?\)"
)
#: The restart reason turns stored before :data:`APP_RESTARTED` existed.
_RESTARTED = re.compile(r"^(?:Dodaios|Jarvis) restarted while this turn was running\b")
_INTERNAL_ERROR = re.compile(r"^Internal error(?::\s*(?P<rest>.*))?$", re.DOTALL)
#: A log line ("2026-10-27 17:05:19 [INFO] ...") or a Python traceback.
_LOG_LINE = re.compile(r"^\s*\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d", re.MULTILINE)
_RAW_MARKERS = re.compile(
    r"Traceback \(most recent call last\)|\[(?:INFO|DEBUG|WARNING|ERROR)\]|<jarvis_identity>",
)
#: A block of the agent's own prompt (``<jarvis_identity> ... </jarvis_identity>``),
#: closed or cut off by the end of the dump / the next log line.
_PROMPT_BLOCK = re.compile(
    r"<(?P<tag>jarvis_[a-z_]+|system|system_prompt|instructions)>.*?"
    r"(?:</(?P=tag)>|(?=\n[ \t]*\d{4}-\d\d-\d\d[ T]\d\d:\d\d)|\Z)",
    re.DOTALL,
)
#: A one-line prompt preview a runtime logs (``msg='<jarvis_identity> ...'``).
_PROMPT_PREVIEW = re.compile(r"msg='[^'\n]*'?")
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s'\"<>)]+", re.IGNORECASE)
_SECRET = re.compile(
    r"(?i)\b(?:sk|pk|rk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{8,}|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"
)
#: How much of a raw dump the details keep.
_DETAILS_MAX_CHARS: Final = 2000


def runner_label(runner: str) -> str:
    """The name the person knows a runner by ("openclaw-cli" -> "OpenClaw")."""
    if runner in _RUNNER_LABELS:
        return _RUNNER_LABELS[runner]
    base = runner.removesuffix("-cli")
    return base[:1].upper() + base[1:] if base else "The agent"


def is_local_provider(provider: str) -> bool:
    """Whether ``provider`` runs its model on this computer."""
    try:
        from dodaios.brain.app_control import LOCAL_PROVIDERS
    except Exception:  # noqa: BLE001 — the spec is optional here; the fallback list decides
        return provider in _LOCAL_FALLBACK
    return provider in LOCAL_PROVIDERS or provider in _LOCAL_FALLBACK


def _span(seconds: float) -> str:
    if seconds >= 60:
        minutes = int(seconds // 60)
        return f"{minutes} minute" + ("" if minutes == 1 else "s")
    whole = max(1, int(seconds))
    return f"{whole} second" + ("" if whole == 1 else "s")


def stall_reason(runner: str, seconds: float, *, provider: str = "") -> str:
    """Why a turn whose runtime went silent for ``seconds`` was stopped."""
    label = runner_label(runner)
    span = _span(seconds)
    if is_local_provider(provider):
        return (
            f"{label} got no reply from the local model for {span}, so the turn was "
            "stopped. The model may be busy, slow, or still loading behind another "
            "model. Try again, or pick a smaller model."
        )
    return f"{label} got no reply from the model for {span}, so the turn was stopped. Try again."


def handshake_reason(runner: str, seconds: float) -> str:
    """Why a turn whose runtime never opened its session was stopped."""
    return (
        f"{runner_label(runner)} did not open its session within {_span(seconds)}, "
        "so the turn was stopped. Try again in a moment."
    )


def _home_dirs() -> list[str]:
    homes = {os.path.expanduser("~")}
    for var in ("USERPROFILE", "HOME"):
        value = os.environ.get(var)
        if value:
            homes.add(value)
    out: list[str] = []
    for home in homes:
        if home and home not in {"~", "/", "\\"}:
            out.append(home)
            out.append(home.replace("\\", "/"))
            out.append(home.replace("\\", "\\\\"))
    return sorted(set(out), key=len, reverse=True)


def redact(text: str) -> str:
    """``text`` without prompt blocks, URLs, secrets or the person's home folder."""
    out = _PROMPT_PREVIEW.sub("msg=[removed]", text)
    out = _PROMPT_BLOCK.sub("[agent instructions removed]", out)
    out = _SECRET.sub("[redacted]", out)
    out = _URL.sub("[url]", out)
    for home in _home_dirs():
        out = re.sub(re.escape(home), "~", out, flags=re.IGNORECASE)
    # A Windows profile path the env did not name (another account, a short name).
    out = re.sub(r"(?i)\b[A-Z]:[\\/]+Users[\\/]+[^\\/\s'\"]+", "~", out)
    out = re.sub(r"/(?:home|Users)/[^/\s'\"]+", "~", out)
    out = "\n".join(line.rstrip() for line in out.splitlines()).strip()
    if len(out) > _DETAILS_MAX_CHARS:
        out = "…" + out[-_DETAILS_MAX_CHARS:]
    return out


def looks_raw(text: str) -> bool:
    """Whether ``text`` is a dump (log lines, a traceback, prompt text), not a reason."""
    if _RAW_MARKERS.search(text) or _LOG_LINE.search(text):
        return True
    lines = [line for line in text.splitlines() if line.strip()]
    return len(lines) > 3 or len(text) > 600


def gateway_unavailable_reason(text: str) -> str:
    """The reason for a runtime's known UNAVAILABLE reply ("" = not one of them)."""
    if _SCHEMA_MIGRATION.search(text):
        return RUNTIME_UPDATING
    if _STARTUP_INSPECTION.search(text):
        return STILL_STARTING
    return ""


def readable_turn_error(
    error: str | None, *, runner: str = "", provider: str = ""
) -> tuple[str | None, str | None]:
    """``(reason, details)`` for a failed turn's error text.

    ``reason`` is one short sentence for the card; ``details`` the redacted
    raw text when the original was a dump, else ``None``.
    """
    if not error:
        return error, None
    text = str(error).strip()
    label = runner_label(runner) if runner else "The agent"
    if _SCHEMA_MIGRATION.search(text):
        return RUNTIME_UPDATING, redact(text)
    if _STARTUP_INSPECTION.search(text):
        return STILL_STARTING, redact(text)
    stall = _STALL.match(text)
    if stall and stall.group("runner") in _RUNNER_LABELS:
        seconds = int(stall.group("minutes")) * 60
        return stall_reason(stall.group("runner"), seconds, provider=provider), None
    internal = _INTERNAL_ERROR.match(text)
    if internal:
        rest = (internal.group("rest") or "").strip()
        return (
            f"{label} hit an internal error and stopped this turn. Try again.",
            redact(rest) or None,
        )
    if _RESTARTED.match(text):
        return APP_RESTARTED, None
    if looks_raw(text):
        return f"{label} stopped with an error. Try again.", redact(text) or None
    # "openclaw-cli exited with code 1." names the runtime as the person knows it.
    head, sep, rest = text.partition(" ")
    if sep and head in _RUNNER_LABELS and head.endswith("-cli"):
        return f"{_RUNNER_LABELS[head]} {rest}", None
    return text, None
