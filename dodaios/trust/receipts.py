"""Action receipts: proof, from the environment, that a side effect happened.

A tool that says "sent" is not evidence that anything was sent. Every
side-effect call that succeeds through the ``ToolExecutor`` gets a receipt
built from what the tool's own result (or the machine) can show: the provider
message id and thread link of a sent mail, the event id of a calendar entry,
the path, size and hash of a written file, the exit code of a command, the URL
of a pull request, the id of a posted channel message, the job id of a
delegation. A call whose tool cannot show anything still gets a receipt, marked
``none`` ("no external evidence"), so the gap is visible rather than silent.

A receipt is a plain dict::

    {"id": "...", "state": "backed" | "none" | "read", "kind": "mail_sent",
     "summary": "Mail sent (message 18c...)", "evidence": {...}, "links": [...]}

``read`` marks a call that has no side effect (no receipt is shown for it).

Two ways to supply evidence, both optional per tool:

* a tool method ``receipt_evidence(args, result, config) -> Evidence | None``;
* :func:`register_evidence` for a tool the app does not own (the built-ins
  below use it, like ``undo.register_inverse``).

Extractors read the result; they never raise (a broken one means "no
evidence") and never change what ran.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .hard_limits import bare_tool

log = logging.getLogger(__name__)

BACKED: Final = "backed"
NONE: Final = "none"
READ: Final = "read"
STATES: Final[tuple[str, ...]] = (BACKED, NONE, READ)

#: ``origin.EFFECTS`` values that change something in the world.
SIDE_EFFECTS: Final[frozenset[str]] = frozenset({"modify", "outbound", "destructive", "spend"})

NO_EVIDENCE_NOTE: Final = "no external evidence"

_HASH_CHUNK = 1 << 20


@dataclass(frozen=True, slots=True)
class Evidence:
    """What a tool (or the machine) can show about one call."""

    kind: str
    summary: str
    ids: dict[str, Any] = field(default_factory=dict)
    links: tuple[str, ...] = ()


EvidenceFn = Callable[[dict[str, Any], Any, dict[str, Any]], "Evidence | None"]
_EXTRACTORS: dict[str, EvidenceFn] = {}


def _key(tool_name: str) -> str:
    return bare_tool(tool_name).lower().replace("-", "_")


def register_evidence(tool_name: str, fn: EvidenceFn) -> None:
    """Register how calls of ``tool_name`` prove themselves (the last one wins)."""
    _EXTRACTORS[_key(tool_name)] = fn


def is_side_effect(tool: Any, args: dict[str, Any], *, effect: str, tier: str) -> bool:
    """Whether this call changes something, from trusted metadata only."""
    from dodaios.core.tool_read_only import allows_read

    try:
        if allows_read(tool, args):
            return False
    except Exception:  # noqa: BLE001 — unsure means "treat as a side effect"
        log.debug("receipt: read-only check failed", exc_info=True)
    if effect == "read":
        return False
    if effect in SIDE_EFFECTS:
        return True
    # An undeclared effect on a tool that is not "safe" is audited as a side
    # effect: risk tiers above "safe" exist because the call changes something.
    return bool(getattr(tool, "is_action_tool", False)) or tier != "safe"


def _jsonish(value: Any) -> Any:
    """A result as data: a dict stays, a JSON string is parsed, anything else is itself."""
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("{", "["):
            try:
                return json.loads(text)
            except ValueError:
                return value
    return value


def _text(value: Any, limit: int = 20_000) -> str:
    if isinstance(value, str):
        return value[:limit]
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:limit]
    except (TypeError, ValueError):
        return str(value)[:limit]


def _out(result: Any) -> Any:
    return _jsonish(getattr(result, "output", None))


def _clean(ids: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in ids.items() if v not in (None, "", [], {})}


# ---------------------------------------------------------------- extractors


def _gmail(args: dict[str, Any], result: Any, _cfg: dict[str, Any]) -> Evidence | None:
    action = str(args.get("action") or "").strip()
    out = _out(result)
    if not isinstance(out, dict) or not out.get("id"):
        return None
    thread = str(out.get("threadId") or "")
    link = f"https://mail.google.com/mail/u/0/#all/{thread or out['id']}"
    ids = _clean({"message_id": out["id"], "thread_id": thread, "to": args.get("to")})
    if action == "send_message":
        return Evidence("mail_sent", f"Mail sent (message {out['id']})", ids, (link,))
    if "draft" in action:
        return Evidence("mail_draft", f"Draft saved (message {out['id']})", ids, (link,))
    label = action or "changed"
    return Evidence("mail_changed", f"Mail {label} (message {out['id']})", ids, (link,))


def _calendar(args: dict[str, Any], result: Any, _cfg: dict[str, Any]) -> Evidence | None:
    action = str(args.get("action") or "").strip()
    out = _out(result)
    event_id = ""
    link = ""
    if isinstance(out, dict):
        event_id = str(out.get("id") or "")
        link = str(out.get("htmlLink") or "")
    if action == "delete_event":
        # The API answered success for this id; there is no event left to link.
        event_id = event_id or str(args.get("event_id") or "")
        if not event_id:
            return None
        return Evidence("calendar_deleted", f"Event deleted ({event_id})", {"event_id": event_id})
    if not event_id:
        return None
    verb = "updated" if action == "update_event" else "created"
    return Evidence(
        "calendar_event",
        f"Event {verb} ({event_id})",
        _clean({"event_id": event_id, "summary": args.get("summary")}),
        (link,) if link else (),
    )


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_write(args: dict[str, Any], result: Any, cfg: dict[str, Any]) -> Evidence | None:
    raw = str(args.get("file_path") or args.get("path") or "")
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        base = str(cfg.get("cwd") or "")
        if not base:
            return None
        path = Path(base) / path
    if not path.is_file():
        return None
    digest = _sha256_of(path)
    ids: dict[str, Any] = {"path": str(path), "size": path.stat().st_size, "sha256": digest}
    content = args.get("content")
    if isinstance(content, str):
        ids["matches_content"] = hashlib.sha256(content.encode("utf-8")).hexdigest() == digest
    return Evidence("file_write", f"File written ({path.name}, {ids['size']} bytes)", ids)


_EXIT_FOOTER = re.compile(r"\[exit (-?\d+)")
_GITHUB_URL = re.compile(
    r"https://github\.com/[\w.-]+/[\w.-]+/(?:pull|issues|commit|releases/tag)/[\w.%-]+"
)


def _shell(args: dict[str, Any], result: Any, _cfg: dict[str, Any]) -> Evidence | None:
    command = str(args.get("command") or "").strip()
    out = _out(result)
    code: int | None = None
    if isinstance(out, dict) and out.get("exit_code") is not None:
        code = int(out["exit_code"])
    elif isinstance(out, str):
        match = _EXIT_FOOTER.search(out[-200:])
        code = int(match.group(1)) if match else None
    if code is None:
        return None
    links = tuple(dict.fromkeys(_GITHUB_URL.findall(_text(out))))[:5]
    ids = _clean({"command": command[:500]})
    ids["exit_code"] = code
    kind = "pull_request_or_issue" if links else "shell"
    return Evidence(kind, f"Command exited {code}", ids, links)


def _slack(_args: dict[str, Any], result: Any, _cfg: dict[str, Any]) -> Evidence | None:
    out = _out(result)
    if not isinstance(out, dict) or not out.get("ts"):
        return None
    ids = _clean(
        {
            "message_id": out["ts"],
            "channel_id": out.get("channel_id"),
            "thread_ts": out.get("thread_ts"),
        }
    )
    return Evidence("channel_message", f"Message posted (ts {out['ts']})", ids)


_JOB_KEYS = ("job_id", "mission_id", "assignment_id", "task_id", "id")
_JOB_IN_TEXT = re.compile(r"\b(job_id|mission_id|assignment_id)[:=]\s*([\w-]{4,})")


def _job(_args: dict[str, Any], result: Any, _cfg: dict[str, Any]) -> Evidence | None:
    out = _out(result)
    ids: dict[str, Any] = {}
    if isinstance(out, dict):
        ids = {k: out[k] for k in _JOB_KEYS if out.get(k)}
    elif isinstance(out, str):
        ids = {m.group(1): m.group(2) for m in _JOB_IN_TEXT.finditer(out)}
    for item in getattr(result, "artifacts", ()) or ():
        if isinstance(item, dict) and item.get("job_id"):
            ids.setdefault("job_id", item["job_id"])
    if not ids:
        return None
    first = next(iter(ids.values()))
    return Evidence("job", f"Started ({first})", _clean(ids))


_URL_KEYS = ("html_url", "url", "htmlLink", "web_url")


def _github_like(_args: dict[str, Any], result: Any, _cfg: dict[str, Any]) -> Evidence | None:
    out = _out(result)
    links: list[str] = []
    if isinstance(out, dict):
        links = [str(out[k]) for k in _URL_KEYS if isinstance(out.get(k), str) and out[k]]
    links += _GITHUB_URL.findall(_text(out))
    links = list(dict.fromkeys(links))[:5]
    if not links:
        return None
    return Evidence("pull_request_or_issue", f"Created ({links[0]})", {}, tuple(links))


register_evidence("gmail", _gmail)
register_evidence("google_calendar", _calendar)
for _name in ("Write", "Edit"):
    register_evidence(_name, _file_write)
for _name in ("run_shell", "RunCommand"):
    register_evidence(_name, _shell)
register_evidence("slack", _slack)
for _name in (
    "delegate_to_agent",
    "spawn_worker",
    "spawn_subagents",
    "multi_spawn",
    "dispatch_to_harness",
    "dispatch_with_review",
    "dispatch_to_admin",
    "message_agent",
):
    register_evidence(_name, _job)


def _evidence(tool: Any, args: dict[str, Any], result: Any, cfg: dict[str, Any]) -> Evidence | None:
    own = getattr(tool, "receipt_evidence", None)
    if callable(own):
        found = own(args, result, cfg)
        if found is not None:
            return found  # type: ignore[no-any-return]
    name = str(getattr(tool, "name", "") or "")
    fn = _EXTRACTORS.get(_key(name))
    if fn is not None:
        return fn(args, result, cfg)
    if "github" in name.lower():
        return _github_like(args, result, cfg)
    return None


def build_receipt(
    receipt_id: str,
    tool: Any,
    args: dict[str, Any],
    result: Any,
    config: dict[str, Any] | None,
    *,
    side_effect: bool,
) -> dict[str, Any]:
    """The receipt of one successful call. Never raises."""
    base: dict[str, Any] = {"id": receipt_id}
    if not side_effect:
        return {**base, "state": READ, "kind": "read", "summary": "", "evidence": {}, "links": []}
    found: Evidence | None = None
    try:
        found = _evidence(tool, dict(args or {}), result, dict(config or {}))
    except Exception:  # noqa: BLE001 — a broken extractor means "no evidence"
        log.warning("receipt: evidence for %s failed", getattr(tool, "name", "?"), exc_info=True)
    if found is None:
        return {
            **base,
            "state": NONE,
            "kind": "none",
            "summary": NO_EVIDENCE_NOTE,
            "evidence": {},
            "links": [],
        }
    return {
        **base,
        "state": BACKED,
        "kind": found.kind,
        "summary": found.summary,
        "evidence": dict(found.ids),
        "links": list(found.links),
    }


__all__ = [
    "BACKED",
    "NONE",
    "NO_EVIDENCE_NOTE",
    "READ",
    "SIDE_EFFECTS",
    "STATES",
    "Evidence",
    "build_receipt",
    "is_side_effect",
    "register_evidence",
]
