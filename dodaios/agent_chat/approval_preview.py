"""The exact action an approval card shows, as structured data (display + edit).

``approval_card.describe_call`` adds the result as ``preview`` to the
``approval_required`` payload. The card renders the fields as the action will
run: the mail with its recipients, subject, body and attachments; the calendar
invite with attendees and time; the file that will be deleted or overwritten
(with a diff); the shell command and the folder it runs in; a payment with its
amount and payee. Nothing here decides anything: tiers, hard limits and rules
stay where they are.

Shape of ``preview``::

    {
      "class":        one of PREVIEW_CLASSES,
      "irreversible": bool,           # sent, deleted or paid: no undo
      "fields": [{"key", "arg", "kind", "value" | "items", "editable"}],
      "diff":   {"path", "creates", "added", "removed", "lines": [{"op", "text"}]}
                or absent,
      "compact": one line of the essentials for a phone,
    }

``kind`` is ``text`` (one line), ``multiline``, ``time``, ``path``, ``code``
or ``people``; ``people`` carries ``items`` of ``{"text", "new"}`` where
``new`` marks a recipient the person never wrote to from here before (the
trust layer's own ledger, ``dodaios.trust.recipients``). ``arg`` is the
argument the field is read from, which is what an edit changes.

Only plain text fields are editable (:data:`EDITABLE`): subject, body, message
text, event title and time. Recipients, attendees, paths and commands never
are, so an edit cannot widen what the person approved or reach a different
recipient. :func:`apply_edits` re-derives what is editable from the call itself
and never trusts the client's idea of it.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from dodaios.core.redact import redact_secrets
from dodaios.trust.hard_limits import (
    action_of,
    bare_tool,
    command_of,
    hard_limit_for,
    is_outbound,
    recipients_of,
)

log = logging.getLogger(__name__)

PREVIEW_CLASSES: Final[tuple[str, ...]] = (
    "mail",
    "calendar",
    "message",
    "file_delete",
    "file_write",
    "shell",
    "payment",
)

_FIELD_CHARS: Final[int] = 20_000
_LIST_ITEMS: Final[int] = 50
_DIFF_LINES: Final[int] = 120
_DIFF_READ_BYTES: Final[int] = 400_000
#: The longest text an inline edit may carry.
EDIT_CHARS: Final[int] = 100_000

#: Argument names a person may change inline, by class.
EDITABLE: Final[dict[str, tuple[str, ...]]] = {
    "mail": ("subject", "body"),
    "calendar": ("summary", "title", "start", "end", "description"),
    "message": ("text", "message", "body", "content"),
}
_TIME_KEYS: Final[frozenset[str]] = frozenset({"start", "end"})

_MAIL_WORDS: Final[re.Pattern[str]] = re.compile(r"(?i)(gmail|mail|outlook|smtp|imap)")
_CALENDAR_WORDS: Final[re.Pattern[str]] = re.compile(r"(?i)(calendar|event|invite)")
_CALENDAR_VERBS: Final[frozenset[str]] = frozenset(
    {"create_event", "update_event", "delete_event", "invite", "respond_to_event"}
)
_DELETE_FILE_TOOLS: Final[frozenset[str]] = frozenset({"delete_file", "remove_file", "rm"})
_WRITE_TOOLS: Final[frozenset[str]] = frozenset(
    {"write", "write_file", "create_file", "overwrite_file"}
)
_EDIT_TOOLS: Final[frozenset[str]] = frozenset(
    {"edit", "edit_file", "str_replace", "str_replace_editor", "multiedit"}
)
_SHELL_TOOLS: Final[frozenset[str]] = frozenset(
    {
        "bash",
        "runcommand",
        "run_command",
        "shell",
        "local_shell",
        "exec",
        "exec_command",
        "execute",
        "terminal",
        "powershell",
        "society_shell",
        "society_sandbox",
    }
)
_PATH_KEYS: Final[tuple[str, ...]] = ("file_path", "path", "filePath", "target_file", "filename")
_ATTACHMENT_KEYS: Final[tuple[str, ...]] = ("attachments", "attachment", "files")
_PAYMENT_KEYS: Final[tuple[str, ...]] = (
    "amount",
    "currency",
    "payee",
    "recipient",
    "to",
    "iban",
    "account",
    "description",
    "memo",
    "reference",
    "item",
    "merchant",
    "price",
    "quantity",
    "order_id",
    "invoice",
)
_SECRET_KEYS: Final[re.Pattern[str]] = re.compile(
    r"(?i)(pass|secret|token|api[_-]?key|cookie|credential|private[_-]?key|otp|pin)"
)
_ADDR_KEYS_MAIL: Final[tuple[str, ...]] = ("to", "cc", "bcc")


# ------------------------------------------------------------------ helpers


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _clip(value: str) -> str:
    return redact_secrets(value)[:_FIELD_CHARS]


def _people(raw: Any) -> list[str]:
    from dodaios.trust.hard_limits import _values  # one reading of "who", shared

    return _values(raw)[:_LIST_ITEMS]


def _first_present(args: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        if isinstance(args.get(key), str) and args[key].strip():
            return key
    return ""


def _known(recipients_known: Callable[[str], bool] | None) -> Callable[[str], bool]:
    if recipients_known is not None:
        return recipients_known
    try:
        from dodaios.trust.recipients import known_recipients

        return known_recipients().knows
    except Exception:  # noqa: BLE001 — without the ledger nobody is flagged as new
        log.debug("approval preview: recipient ledger unavailable", exc_info=True)
        return lambda _value: True


def _field(
    key: str,
    kind: str,
    *,
    arg: str = "",
    value: str = "",
    items: list[dict[str, Any]] | None = None,
    editable: bool = False,
) -> dict[str, Any]:
    out: dict[str, Any] = {"key": key, "arg": arg or key, "kind": kind, "editable": editable}
    if items is not None:
        out["items"] = items
    else:
        out["value"] = _clip(value)
    return out


# ------------------------------------------------------------- classification


def class_of(name: str, args: dict[str, Any]) -> str:
    """Which preview class a call belongs to, or ``""`` for none."""
    bare = bare_tool(name)
    low = bare.lower()
    verb = action_of(args)
    limit = hard_limit_for(name, args, recipients_known=lambda _r: True)
    if limit == "money":
        return "payment"
    if verb in _CALENDAR_VERBS or (
        _CALENDAR_WORDS.search(low)
        and verb
        and not verb.startswith(("list", "get", "read", "search"))
    ):
        return "calendar"
    if low in _DELETE_FILE_TOOLS or verb == "delete_file":
        return "file_delete"
    if is_outbound(name, args):
        if _MAIL_WORDS.search(low) or "subject" in args or any(k in args for k in ("cc", "bcc")):
            return "mail"
        return "message"
    if verb in ("trash_message", "delete_message") and _MAIL_WORDS.search(low):
        return "mail"
    if low in _WRITE_TOOLS or low in _EDIT_TOOLS:
        return "file_write"
    if low in _SHELL_TOOLS or (command_of(args) and not verb):
        return "shell"
    return ""


# ------------------------------------------------------------------- previews


def build_preview(
    name: str,
    args: dict[str, Any] | None,
    cwd: str = "",
    *,
    recipients_known: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    """The structured preview of one call, or ``None`` when no class fits."""
    args = args if isinstance(args, dict) else {}
    klass = class_of(name, args)
    if not klass:
        return None
    builder = _BUILDERS[klass]
    preview = builder(name, args, cwd, _known(recipients_known))
    preview["class"] = klass
    preview["compact"] = compact_line(preview)
    return preview


def _mail(
    name: str, args: dict[str, Any], cwd: str, known: Callable[[str], bool]
) -> dict[str, Any]:
    verb = action_of(args)
    fields: list[dict[str, Any]] = []
    for key in _ADDR_KEYS_MAIL:
        people = _people(args.get(key))
        if people:
            items = [{"text": _clip(p), "new": not known(p)} for p in people]
            fields.append(_field(key, "people", items=items))
    if verb in ("trash_message", "delete_message"):
        fields.append(_field("message_id", "text", value=_text(args.get("message_id"))))
    subject = _first_present(args, ("subject",))
    fields.append(
        _field("subject", "text", value=_text(args.get("subject")), editable=True)
        if subject or verb.startswith("send")
        else _field("subject", "text", value="")
    )
    if "body" in args or verb.startswith(("send", "reply", "forward")):
        fields.append(_field("body", "multiline", value=_text(args.get("body")), editable=True))
    attachments = _attachments(args)
    if attachments:
        fields.append(
            _field("attachments", "people", items=[{"text": a, "new": False} for a in attachments])
        )
    fields = [
        f
        for f in fields
        if not (f["key"] == "subject" and not f.get("value") and not f["editable"])
    ]
    return {"irreversible": verb != "trash_message", "fields": fields}


def _attachments(args: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in _ATTACHMENT_KEYS:
        raw = args.get(key)
        entries = raw if isinstance(raw, list) else [raw] if raw else []
        for entry in entries:
            if isinstance(entry, str) and entry.strip():
                out.append(_clip(os.path.basename(entry.strip()) or entry.strip()))
            elif isinstance(entry, dict):
                label = _text(entry.get("name") or entry.get("filename") or entry.get("path"))
                if label:
                    out.append(_clip(os.path.basename(label) or label))
    return out[:_LIST_ITEMS]


def _calendar(
    name: str, args: dict[str, Any], cwd: str, known: Callable[[str], bool]
) -> dict[str, Any]:
    verb = action_of(args)
    fields: list[dict[str, Any]] = []
    title_key = "summary" if "summary" in args or "title" not in args else "title"
    title = _text(args.get(title_key))
    if title or verb in ("create_event", "update_event"):
        fields.append(_field("title", "text", arg=title_key, value=title, editable=True))
    for key in ("start", "end"):
        if key in args:
            fields.append(_field(key, "time", value=_text(args.get(key)), editable=True))
    attendees = _people(args.get("attendees") or args.get("guests"))
    if attendees:
        fields.append(
            _field(
                "attendees",
                "people",
                arg="attendees" if "attendees" in args else "guests",
                items=[{"text": _clip(p), "new": not known(p)} for p in attendees],
            )
        )
    for key in ("location",):
        if _text(args.get(key)):
            fields.append(_field(key, "text", value=_text(args.get(key))))
    if "description" in args:
        fields.append(
            _field("description", "multiline", value=_text(args.get("description")), editable=True)
        )
    if verb in ("update_event", "delete_event", "respond_to_event") and _text(args.get("event_id")):
        fields.append(_field("event_id", "text", value=_text(args.get("event_id"))))
    return {
        "irreversible": verb == "delete_event" or bool(attendees),
        "fields": fields,
        "verb": verb,
    }


def _message(
    name: str, args: dict[str, Any], cwd: str, known: Callable[[str], bool]
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    people = recipients_of(name, args)[:_LIST_ITEMS]
    if people:
        fields.append(
            _field(
                "to",
                "people",
                items=[{"text": _clip(p), "new": not known(p)} for p in people],
            )
        )
    key = _first_present(args, EDITABLE["message"])
    if key:
        fields.append(
            _field("text", "multiline", arg=key, value=_text(args.get(key)), editable=True)
        )
    return {"irreversible": True, "fields": fields}


def _path_of(args: dict[str, Any]) -> str:
    nested = args.get("arguments")
    for part in (args, nested) if isinstance(nested, dict) else (args,):
        for key in _PATH_KEYS:
            value = part.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _absolute(path: str, cwd: str) -> str:
    raw = Path(path)
    if not raw.is_absolute() and cwd:
        raw = Path(cwd) / raw
    return os.path.normpath(str(raw))


def _shown(path: str, cwd: str) -> str:
    from .approval_card import display_paths

    return display_paths(path, cwd)


def _file_delete(
    name: str, args: dict[str, Any], cwd: str, known: Callable[[str], bool]
) -> dict[str, Any]:
    path = _path_of(args)
    fields = [_field("path", "path", value=_shown(path, cwd))] if path else []
    if path:
        try:
            full = _absolute(path, cwd)
            if os.path.isfile(full):
                fields.append(_field("size", "text", value=f"{os.path.getsize(full)} B"))
            elif os.path.isdir(full):
                fields.append(_field("folder", "text", value="1"))
        except OSError:
            log.debug("approval preview: could not stat %s", path)
    return {"irreversible": True, "fields": fields}


def _file_write(
    name: str, args: dict[str, Any], cwd: str, known: Callable[[str], bool]
) -> dict[str, Any]:
    path = _path_of(args)
    fields = [_field("path", "path", value=_shown(path, cwd))] if path else []
    preview: dict[str, Any] = {"irreversible": False, "fields": fields}
    low = bare_tool(name).lower()
    try:
        diff = _write_diff(low, args, path, cwd)
    except (OSError, UnicodeError, ValueError) as exc:
        log.debug("approval preview: no diff for %s: %s", path, exc)
        diff = None
    if diff is not None:
        preview["diff"] = diff
        # An overwrite replaces what was there; the diff above is the only record.
        preview["irreversible"] = bool(not diff["creates"] and diff["removed"])
    return preview


def _write_diff(low: str, args: dict[str, Any], path: str, cwd: str) -> dict[str, Any] | None:
    shown = _shown(path, cwd)
    if low in _WRITE_TOOLS:
        new = args.get("content")
        if not isinstance(new, str):
            new = args.get("text") if isinstance(args.get("text"), str) else None
        if new is None or not path:
            return None
        full = _absolute(path, cwd)
        if os.path.isfile(full):
            if os.path.getsize(full) > _DIFF_READ_BYTES:
                return None
            old = Path(full).read_text(encoding="utf-8", errors="replace")
            creates = False
        else:
            old, creates = "", True
        return _diff_lines(shown, old, new, creates)
    old_s, new_s = args.get("old_string"), args.get("new_string")
    if isinstance(old_s, str) and isinstance(new_s, str):
        return _diff_lines(shown, old_s, new_s, False)
    return None


def _diff_lines(path: str, old: str, new: str, creates: bool) -> dict[str, Any]:
    old_lines, new_lines = old.splitlines(), new.splitlines()
    rows: list[dict[str, str]] = []
    added = removed = 0
    for line in difflib.unified_diff(old_lines, new_lines, lineterm="", n=2):
        if line.startswith(("---", "+++")):
            continue
        if line.startswith("@@"):
            rows.append({"op": "@", "text": line})
        elif line.startswith("+"):
            added += 1
            rows.append({"op": "+", "text": line[1:]})
        elif line.startswith("-"):
            removed += 1
            rows.append({"op": "-", "text": line[1:]})
        else:
            rows.append({"op": " ", "text": line[1:]})
    return {
        "path": path,
        "creates": creates,
        "added": added,
        "removed": removed,
        "truncated": len(rows) > _DIFF_LINES,
        "lines": [{"op": r["op"], "text": _clip(r["text"])[:400]} for r in rows[:_DIFF_LINES]],
    }


def _shell(
    name: str, args: dict[str, Any], cwd: str, known: Callable[[str], bool]
) -> dict[str, Any]:
    from .approval_card import caution_of, display_paths

    command = command_of(args)
    folder = args.get("cwd") or args.get("workdir") or cwd
    fields = [_field("command", "code", value=command)]
    if isinstance(folder, str) and folder.strip():
        fields.append(_field("folder", "path", value=display_paths(folder, cwd)))
    irreversible = caution_of("terminal", command, "") == "irreversible" or (
        hard_limit_for(name, args, recipients_known=lambda _r: True) == "permanent_delete"
    )
    return {"irreversible": irreversible, "fields": fields}


def _payment(
    name: str, args: dict[str, Any], cwd: str, known: Callable[[str], bool]
) -> dict[str, Any]:
    fields: list[dict[str, Any]] = []
    verb = action_of(args)
    if verb:
        fields.append(_field("action", "text", value=verb))
    for key in _PAYMENT_KEYS:
        value = _text(args.get(key))
        if value and not _SECRET_KEYS.search(key):
            fields.append(_field(key, "text", value=value))
    return {"irreversible": True, "fields": fields}


_BUILDERS: Final[dict[str, Callable[..., dict[str, Any]]]] = {
    "mail": _mail,
    "calendar": _calendar,
    "message": _message,
    "file_delete": _file_delete,
    "file_write": _file_write,
    "shell": _shell,
    "payment": _payment,
}


# --------------------------------------------------------------- phone line

_LABELS: Final[dict[str, dict[str, str]]] = {
    "en": {
        "to": "To",
        "new": "new",
        "subject": "Subject",
        "attachments": "attachments",
        "title": "Title",
        "start": "From",
        "end": "to",
        "attendees": "With",
        "delete": "Delete",
        "overwrite": "Overwrite",
        "create": "Create",
        "run": "Run",
        "in": "in",
        "cannot_undo": "cannot be undone",
        "message": "Message",
        "pay": "Pay",
        "lines": "lines",
    },
    "de": {
        "to": "An",  # i18n-allow
        "new": "neu",  # i18n-allow
        "subject": "Betreff",  # i18n-allow
        "attachments": "Anhänge",  # i18n-allow
        "title": "Titel",  # i18n-allow
        "start": "Von",  # i18n-allow
        "end": "bis",  # i18n-allow
        "attendees": "Mit",  # i18n-allow
        "delete": "Löschen",  # i18n-allow
        "overwrite": "Überschreiben",  # i18n-allow
        "create": "Anlegen",  # i18n-allow
        "run": "Ausführen",  # i18n-allow
        "in": "in",  # i18n-allow
        "cannot_undo": "nicht rückgängig zu machen",  # i18n-allow
        "message": "Nachricht",  # i18n-allow
        "pay": "Zahlen",  # i18n-allow
        "lines": "Zeilen",  # i18n-allow
    },
    "es": {
        "to": "Para",
        "new": "nuevo",
        "subject": "Asunto",
        "attachments": "adjuntos",
        "title": "Título",
        "start": "Desde",
        "end": "hasta",
        "attendees": "Con",
        "delete": "Borrar",
        "overwrite": "Sobrescribir",
        "create": "Crear",
        "run": "Ejecutar",
        "in": "en",
        "cannot_undo": "no se puede deshacer",
        "message": "Mensaje",
        "pay": "Pagar",
        "lines": "líneas",
    },
    "pt": {
        "to": "Para",
        "new": "novo",
        "subject": "Assunto",
        "attachments": "anexos",
        "title": "Título",
        "start": "De",
        "end": "até",
        "attendees": "Com",
        "delete": "Apagar",
        "overwrite": "Substituir",
        "create": "Criar",
        "run": "Executar",
        "in": "em",
        "cannot_undo": "não pode ser desfeito",
        "message": "Mensagem",
        "pay": "Pagar",
        "lines": "linhas",
    },
}
_COMPACT_BODY: Final[int] = 90


def _fields(preview: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["key"]: f for f in preview.get("fields", [])}


def _people_text(field: dict[str, Any] | None, new_word: str) -> str:
    if not field:
        return ""
    return ", ".join(
        f"{item['text']} ({new_word})" if item.get("new") else item["text"]
        for item in field.get("items", [])
    )


def _one_line(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def compact_line(preview: dict[str, Any], lang: str = "en") -> str:
    """The essentials of ``preview`` on one short line, for a phone channel."""
    words = _LABELS.get(lang) or _LABELS["en"]
    fields = _fields(preview)
    klass = preview.get("class")
    parts: list[str] = []
    if klass == "mail":
        parts = [f"{words['to']}: {_people_text(fields.get('to'), words['new'])}"]
        if fields.get("subject", {}).get("value"):
            parts.append(f"{words['subject']}: {_one_line(fields['subject']['value'], 80)}")
        if fields.get("body", {}).get("value"):
            parts.append(f'"{_one_line(fields["body"]["value"], _COMPACT_BODY)}"')
        if fields.get("attachments"):
            parts.append(f"{len(fields['attachments']['items'])} {words['attachments']}")
    elif klass == "calendar":
        if fields.get("title"):
            parts.append(_one_line(fields["title"].get("value", ""), 80))
        when = " ".join(
            x
            for x in (
                fields.get("start", {}).get("value", ""),
                f"{words['end']} {fields['end']['value']}" if fields.get("end") else "",
            )
            if x
        )
        if when:
            parts.append(when)
        if fields.get("attendees"):
            parts.append(f"{words['attendees']}: {_people_text(fields['attendees'], words['new'])}")
    elif klass == "message":
        parts = [f"{words['to']}: {_people_text(fields.get('to'), words['new'])}"]
        if fields.get("text"):
            parts.append(f'"{_one_line(fields["text"].get("value", ""), _COMPACT_BODY)}"')
    elif klass == "file_delete":
        parts = [f"{words['delete']}: {fields.get('path', {}).get('value', '')}"]
    elif klass == "file_write":
        diff = preview.get("diff") or {}
        verb = words["create"] if diff.get("creates") else words["overwrite"]
        parts = [f"{verb}: {fields.get('path', {}).get('value', '')}"]
        if diff:
            parts.append(f"+{diff.get('added', 0)} -{diff.get('removed', 0)} {words['lines']}")
    elif klass == "shell":
        parts = [f"{words['run']}: {_one_line(fields.get('command', {}).get('value', ''), 140)}"]
        if fields.get("folder"):
            parts.append(f"{words['in']} {fields['folder']['value']}")
    elif klass == "payment":
        amount = " ".join(
            x
            for x in (
                fields.get("amount", {}).get("value"),
                fields.get("currency", {}).get("value"),
            )
            if x
        )
        payee = next(
            (fields[k]["value"] for k in ("payee", "recipient", "to", "merchant") if k in fields),
            "",
        )
        parts = [x for x in (words["pay"] + (f": {amount}" if amount else ""), payee) if x]
    line = " | ".join(p for p in parts if p.strip())
    if preview.get("irreversible") and line:
        line += f" ({words['cannot_undo']})"
    return line[:400]


# ------------------------------------------------------------------- editing


def editable_keys(name: str, args: dict[str, Any]) -> dict[str, str]:
    """``{field key: argument name}`` the person may edit on this call (server-side truth)."""
    preview = build_preview(name, args, recipients_known=lambda _r: True)
    if preview is None:
        return {}
    return {f["key"]: f["arg"] for f in preview["fields"] if f.get("editable")}


def _valid_time(value: str) -> bool:
    text = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            datetime.strptime(text, "%Y-%m-%d")
            return True
        except ValueError:  # not a real calendar date
            return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:  # not an ISO date-time
        return False
    return "T" in text


class EditRejected(ValueError):
    """An inline edit the card may not apply (the person is told why)."""


def apply_edits(
    name: str, args: dict[str, Any], edits: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """``(new_args, changed)`` for the person's inline edits.

    ``edits`` maps a preview field key to its new text. Only fields the call's
    own preview marks editable are accepted; anything else raises
    :class:`EditRejected` rather than being ignored, so a stale or forged card
    never quietly runs something the person did not see. ``changed`` lists
    ``{key: {"before", "after"}}`` for fields whose text actually changed (an
    edit equal to the original is dropped).
    """
    allowed = editable_keys(name, args)
    new_args = dict(args)
    changed: dict[str, dict[str, str]] = {}
    for key, value in (edits or {}).items():
        arg = allowed.get(str(key))
        if arg is None:
            raise EditRejected(f"{key} cannot be edited on this action")
        if not isinstance(value, str):
            raise EditRejected(f"{key} must be text")
        if len(value) > EDIT_CHARS:
            raise EditRejected(f"{key} is too long")
        if str(key) in _TIME_KEYS and not _valid_time(value):
            raise EditRejected(f"{key} is not a valid date or time")
        before = _text(args.get(arg))
        if value == before:
            continue
        new_args[arg] = value
        changed[str(key)] = {"before": before[:2000], "after": value[:2000]}
    return new_args, changed


def edits_note(changed: dict[str, dict[str, str]]) -> str:
    """What the agent is told when the person edited the action before approving."""
    if not changed:
        return ""
    lines = [
        f"- {key}: {_one_line(v['before'], 160)!r} -> {_one_line(v['after'], 160)!r}"
        for key, v in changed.items()
    ]
    return (
        "The person edited this action before approving it. It ran with their version, "
        "not yours:\n" + "\n".join(lines)
    )


__all__ = [
    "EDITABLE",
    "EDIT_CHARS",
    "PREVIEW_CLASSES",
    "EditRejected",
    "apply_edits",
    "build_preview",
    "class_of",
    "compact_line",
    "edits_note",
    "editable_keys",
]
