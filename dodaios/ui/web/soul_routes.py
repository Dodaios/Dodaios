"""REST API for the SOUL.md section — the assistant's own profile.

The section shows every file that shapes who the assistant is, in one place:

* ``SOUL.md`` (``data/workspace/SOUL.md``) — its character: name, role, tone,
  limits, and the notes it keeps about itself (``update_soul``);
* the standing instructions the person writes for it
  (``data/agent_instructions/<Name>.md``, edited through
  ``/api/settings/agent-instructions``);
* ``MEMORY.md`` and ``USER.md`` — what it was asked to remember, its working
  notes, and what it knows about the person. While the memory vault runs
  (ADR-0044) both pages are views of the vault, because that is where a
  reviewed conversation is written (``dodaios.memory.vault.pages``); notes
  still left in the old notebooks (``society/jarvis/``,
  ``dodaios.memory.learning.notebook``) are listed after them. The USER.md
  page starts with what the person's own profile states
  (``data/workspace/USER.md``), so one page answers "what does it know
  about me".

Endpoints:
    GET    /api/soul                              → the whole profile
    PUT    /api/soul/file                         → save SOUL.md's Markdown
    PUT    /api/soul/initiative                   → how much initiative it takes
    DELETE /api/soul/entries/{target}/{entry_id}  → forget one learned note

Reads never create a file: a fresh install shows the files as missing
rather than seeding them from a GET.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/soul", tags=["soul"])

#: How many recent learning-ledger lines the activity list shows.
_ACTIVITY_LIMIT = 12
#: Longest quote of what the person said that one activity line carries.
_EVIDENCE_CHARS = 220
#: The ledger rotates at 256 KB; reading its tail is enough for the list.
_LEDGER_TAIL_BYTES = 64 * 1024


class InitiativeBody(BaseModel):
    level: Literal["off", "balanced", "high"]


class SoulBody(BaseModel):
    # The Markdown under the frontmatter. Empty is refused: SOUL.md is the
    # assistant's identity and the page has no "delete" for it.
    content: str = Field(..., min_length=1)


def _config(request: Request) -> Any:
    return getattr(request.app.state, "config", None) or getattr(request.app.state, "cfg", None)


def _mtime_ms(path: Path) -> int | None:
    try:
        return int(path.stat().st_mtime * 1000)
    except OSError:  # a missing file has no mtime
        return None


def _entry(entry: Any) -> dict[str, Any]:
    from dodaios.memory.learning.notebook import EXPLICIT_ORIGIN

    return {
        "id": entry.id,
        "text": entry.text,
        "importance": entry.importance,
        "origin": entry.origin,
        "explicit": entry.origin == EXPLICIT_ORIGIN,
        "store": "notebook",
        "at_ms": None,
    }


def _labelled(lines: list[str]) -> list[dict[str, str]]:
    """``- **Role:** text`` bullets as ``{label, text}``; plain bullets keep no label."""
    out: list[dict[str, str]] = []
    for line in lines:
        text = line.strip()
        if text[:2] in ("- ", "* "):
            text = text[2:].strip()
        label = ""
        if text.startswith("**") and ":**" in text:
            label, text = text[2:].split(":**", 1)
            label, text = label.strip(), text.strip()
        elif text.startswith("**") and text.count("**") >= 2:
            label, text = text[2:].split("**", 1)
            label, text = label.strip().rstrip(":"), text.strip().lstrip(":").strip()
        if text or label:
            out.append({"label": label, "text": text})
    return out


def _soul_file(path: Path) -> dict[str, Any]:
    from dodaios.memory.soul import Soul

    base: dict[str, Any] = {
        "id": "soul",
        "filename": path.name,
        "exists": path.is_file(),
        "editable": True,
        "updated_ms": _mtime_ms(path),
        "content": "",
        "chars": 0,
        "character": {"who": [], "tone": [], "limits": []},
        "learned": [],
        "name_in_file": "",
    }
    if not base["exists"]:
        return base
    try:
        soul = Soul.load(path)
    except (OSError, ValueError):
        log.warning("soul: SOUL.md could not be read", exc_info=True)
        base["exists"] = False
        return base
    sections = soul.sections()
    base.update(
        content=soul.body,
        chars=len(soul.body),
        character={key: _labelled(lines) for key, lines in sections.items()},
        learned=[_entry(e) for e in soul.learned()],
        name_in_file=soul.name,
    )
    return base


def _instructions_file(config: Any) -> dict[str, Any]:
    from dodaios.brain import agent_instructions

    path = agent_instructions.instructions_path(config)
    content = agent_instructions.read_agent_instructions(config) or ""
    return {
        "id": "instructions",
        "filename": path.name,
        "exists": bool(content),
        "editable": True,
        "updated_ms": _mtime_ms(path) if content else None,
        "content": content,
        "chars": len(content),
        "template": agent_instructions.seed_template(config),
    }


def _notebook_folder(config: Any) -> Path | None:
    from dodaios.memory.learning.notebook import OWNER_ID
    from dodaios.society.memory import resolve_society_vault
    from dodaios.society.memory_books import folder_for

    try:
        return folder_for(resolve_society_vault(config), OWNER_ID)
    except Exception:  # noqa: BLE001 — no vault means no notebooks to show, not a failure
        log.debug("soul: the notebook folder is unavailable", exc_info=True)
        return None


def _book_file(folder: Path | None, target: str) -> dict[str, Any]:
    from dodaios.society.memory_books import FILES, body
    from dodaios.society.notebook import parse

    filename = FILES[target]
    path = folder / filename if folder is not None else None
    base: dict[str, Any] = {
        "id": target,
        "filename": filename,
        "exists": bool(path and path.is_file()),
        "editable": False,
        "updated_ms": _mtime_ms(path) if path else None,
        "entries": [],
        "chars": 0,
        "store": "notebook",
    }
    if not base["exists"] or path is None:
        return base
    try:
        entries = parse(body(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        log.warning("soul: %s could not be read", filename, exc_info=True)
        return base
    # Newest first: the page answers "what did it learn lately" before "since when".
    ordered = sorted(entries, key=lambda e: e.revision, reverse=True)
    base["entries"] = [_entry(e) for e in ordered]
    base["chars"] = sum(len(e.text) for e in entries)
    return base


def _same_note(text: str) -> str:
    """One spelling of a note, to tell a notebook entry from its copy in the vault."""
    from dodaios.memory.vault.legacy_import import clean
    from dodaios.memory.vault.models import normalize_text

    return normalize_text(clean(text))


def _show_vault(books: dict[str, dict[str, Any]], vault: Any) -> None:
    """Fill both pages from the memory vault; notebook notes it does not hold follow.

    The vault is where a review writes while it runs, so without this the
    pages stay empty however much the assistant has learned. A notebook note
    the one-time import copied into the vault is shown once, as the vault's.
    """
    from dodaios.memory.vault import pages

    try:
        found = pages.entries(vault)
        known: set[str] = set()
        if any(book["entries"] for book in books.values()):
            known = {_same_note(m.text) for m in vault.list(include_closed=True)}
    except Exception:  # noqa: BLE001 — a vault fault leaves the notebooks on the page
        log.warning("soul: the memory vault could not be read for the page", exc_info=True)
        return
    for target, rows in found.items():
        book = books[target]
        kept = [e for e in book["entries"] if _same_note(e["text"]) not in known]
        times = [row["at_ms"] for row in rows if row["at_ms"]]
        if kept and book["updated_ms"]:
            times.append(book["updated_ms"])
        book.update(
            entries=rows + kept,
            exists=True,
            store="vault",
            updated_ms=max(times) if times else None,
            chars=sum(len(e["text"]) for e in rows + kept),
        )


#: Profile fields the USER.md page lists, in reading order: ``(cluster, field)``.
_PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("identity", "name"),
    ("identity", "preferred_address"),
    ("identity", "about"),
    ("identity", "pronouns"),
    ("identity", "primary_language"),
    ("identity", "languages"),
    ("identity", "timezone"),
    ("identity", "devices"),
    ("communication", "directness"),
    ("communication", "formality"),
    ("communication", "verbosity"),
    ("communication", "humor_types"),
    ("communication", "emoji_ok"),
    ("work_style", "focus_mode"),
    ("work_style", "planning_horizon"),
    ("values", "top_values"),
    ("values", "pet_peeves"),
    ("values", "motivations"),
    ("relationship", "feedback_pref"),
)
#: Fields rated on a scale of one to five.
_SCALE_FIELDS = frozenset({"directness", "formality"})


def _profile_path() -> Path:
    """The person's profile (``<DATA_DIR>/workspace/USER.md``), next to SOUL.md."""
    from dodaios.brain.identity import soul_path
    from dodaios.memory.workspace import USER_MD

    return soul_path().parent / USER_MD


def _profile_entries(path: Path) -> list[dict[str, Any]]:
    """What the person's profile states, one line per value; ``[]`` without a profile.

    The profile is in every prompt ("About the User"), so it belongs to what
    the assistant knows about the person. Its lines are read-only here: the
    Profile page edits them. A value the old template filled in for everybody
    is left out (``dodaios.memory.template_defaults``).
    """
    from dodaios.memory.frontmatter import parse_frontmatter
    from dodaios.memory.template_defaults import assumed_fields

    try:
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # no readable profile: nothing to list
        return []
    assumed = assumed_fields(meta, body)
    out: list[dict[str, Any]] = []
    for cluster, name in _PROFILE_FIELDS:
        section = meta.get(cluster)
        value = section.get(name) if isinstance(section, dict) else None
        if value is None or (cluster == "identity" and name in assumed):
            continue
        values = value if isinstance(value, list) else [value]
        for index, item in enumerate(values):
            if isinstance(item, bool):
                text = "true" if item else "false"
            elif name in _SCALE_FIELDS and isinstance(item, int):
                text = f"{item}/5"
            else:
                text = " ".join(str(item).split()) if isinstance(item, str | int | float) else ""
            if not text:
                continue
            suffix = f":{index}" if isinstance(value, list) else ""
            out.append(
                {
                    "id": f"profile:{cluster}.{name}{suffix}",
                    "text": text,
                    "importance": 0,
                    "origin": "profile",
                    "explicit": False,
                    "store": "profile",
                    "field": name,
                    "at_ms": None,
                }
            )
    return out


def _show_profile(book: dict[str, Any], path: Path) -> None:
    """Put the profile's lines at the top of the USER.md page.

    A memory the one-time import copied from the profile only repeats a line
    that is shown above it, so it is left out.
    """
    lines = _profile_entries(path)
    if not lines:
        return
    # The import wrote identity fields only; a value counts as a whole word,
    # so the language "en" does not hide a sentence that merely contains it.
    stated = [
        re.compile(rf"(?<!\w){re.escape(line['text'].casefold())}(?!\w)")
        for line in lines
        if line["id"].startswith("profile:identity.")
    ]

    def repeats_profile(entry: dict[str, Any]) -> bool:
        source = entry.get("source") or {}
        if source.get("from") != "user-profile":
            return False
        text = str(entry["text"]).casefold()
        return any(value.search(text) for value in stated)

    rest = [e for e in book["entries"] if not repeats_profile(e)]
    times = [t for t in (book["updated_ms"], _mtime_ms(path)) if t]
    book.update(
        entries=lines + rest,
        exists=True,
        updated_ms=max(times) if times else None,
        chars=sum(len(e["text"]) for e in lines + rest),
    )


def _books(folder: Path | None) -> list[dict[str, Any]]:
    """The MEMORY.md and USER.md pages: the vault, the notebooks and the profile."""
    from dodaios.memory.vault import runtime as vault_runtime

    books = {target: _book_file(folder, target) for target in ("memory", "user")}
    vault = vault_runtime.active()
    if vault is not None:
        _show_vault(books, vault)
    _show_profile(books["user"], _profile_path())
    for book in books.values():
        for entry in book["entries"]:
            entry.pop("source", None)  # where a memory came from stays off the page
    return list(books.values())


def _stamp_ms(stamp: str) -> int:
    """A ledger or vault time as milliseconds, for sorting; 0 when unreadable."""
    from dodaios.memory.vault.pages import time_ms

    return time_ms(stamp) or 0


def _with_vault_activity(listed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ledger's changes and the vault's, newest first, as one list."""
    from dodaios.memory.vault import pages
    from dodaios.memory.vault import runtime as vault_runtime

    vault = vault_runtime.active()
    if vault is None:
        return listed
    try:
        learned = pages.activity(vault, limit=_ACTIVITY_LIMIT)
    except Exception:  # noqa: BLE001 — the ledger's own lines still answer
        log.warning("soul: the memory vault's activity could not be read", exc_info=True)
        return listed
    merged = sorted(listed + learned, key=lambda item: _stamp_ms(item["ts"]), reverse=True)
    return merged[:_ACTIVITY_LIMIT]


#: Ledger fields that name the model call behind a line (``review.SeatChoice``).
_SEAT_FIELDS = ("seat", "seat_label", "billing")


def _seat(record: dict[str, Any]) -> dict[str, str]:
    return {name: str(record.get(name, "") or "") for name in _SEAT_FIELDS}


def _ledger_lines(folder: Path | None) -> list[dict[str, Any]]:
    """The ledger's tail as records, newest first."""
    from dodaios.memory.learning.notebook import LEDGER_NAME

    if folder is None:
        return []
    ledger = folder / LEDGER_NAME
    try:
        with ledger.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - _LEDGER_TAIL_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:  # no ledger yet means no history
        return []
    lines = tail.splitlines()
    if size > _LEDGER_TAIL_BYTES and lines:
        lines = lines[1:]  # the first line of a mid-file tail is cut off
    records: list[dict[str, Any]] = []
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:  # a torn ledger line is skipped
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _last_review(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The newest model call of the loop: when, how it ended, where it ran and how it billed."""
    for record in records:
        if record.get("operation") == "review":
            return {
                "ts": str(record.get("ts", "")),
                "source": str(record.get("source", "")),
                "outcome": str(record.get("outcome", "")),
                "changes": int(record.get("changes", 0) or 0),
                **_seat(record),
            }
    return None


def _activity(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The most recent changes the ledger holds, newest first."""
    out: list[dict[str, Any]] = []
    for record in records:
        operation = str(record.get("operation", ""))
        if operation == "review":
            continue  # a model call, not a change: ``last_review`` carries it
        text = str(record.get("before" if operation == "remove" else "after", "") or "")
        evidence = str(record.get("evidence", "") or "")
        if len(evidence) > _EVIDENCE_CHARS:
            evidence = evidence[: _EVIDENCE_CHARS - 1].rstrip() + "…"
        out.append(
            {
                "ts": str(record.get("ts", "")),
                "source": str(record.get("source", "")),
                "target": str(record.get("target", "")),
                "operation": operation,
                "text": text,
                "evidence": evidence,
                **_seat(record),
            }
        )
        if len(out) >= _ACTIVITY_LIMIT:
            break
    return out


def _wake_phrase(config: Any) -> str:
    trigger = getattr(config, "trigger", None)
    wake_word = getattr(trigger, "wake_word", None) if trigger is not None else None
    return str(getattr(wake_word, "phrase", "") or "") if wake_word is not None else ""


def _payload(request: Request) -> dict[str, Any]:
    from dodaios.brain.assistant_name import DEFAULT_ASSISTANT_NAME, resolve_assistant_name
    from dodaios.brain.identity import PRODUCT_NAME, soul_path
    from dodaios.memory.learning import notebook as notebook_module

    config = _config(request)
    try:
        name = resolve_assistant_name(config)
    except Exception:  # noqa: BLE001 — the page still renders with the fallback name
        log.debug("soul: assistant name unavailable", exc_info=True)
        name = DEFAULT_ASSISTANT_NAME
    folder = _notebook_folder(config)
    records = _ledger_lines(folder)
    return {
        "name": name,
        "named": name != DEFAULT_ASSISTANT_NAME,
        "product": PRODUCT_NAME,
        "wake_phrase": _wake_phrase(config),
        "learning": notebook_module.active() is not None,
        "files": [
            _soul_file(soul_path()),
            _instructions_file(config),
            *_books(folder),
        ],
        "activity": _with_vault_activity(_activity(records)),
        "last_review": _last_review(records),
        "initiative": _initiative(config),
    }


def _initiative(config: Any) -> dict[str, Any]:
    """The initiative level and the dated plans the assistant may bring up."""
    from dodaios.brain import proactivity

    level = proactivity.current_level(config)
    upcoming = [] if level == "off" else proactivity.upcoming_notes()
    return {
        "level": level,
        "levels": list(proactivity.LEVELS),
        "upcoming": [{"date": day.isoformat(), "text": text} for day, text in upcoming],
    }


@router.get("", summary="The assistant's profile: SOUL.md and every file that shapes it")
def get_soul(request: Request) -> dict[str, Any]:
    return _payload(request)


@router.put("/file", summary="Save SOUL.md")
def put_soul(body: SoulBody, request: Request) -> dict[str, Any]:
    """Write SOUL.md's Markdown under its lock; the next prompt reads it."""
    from dodaios.brain.identity import soul_path
    from dodaios.memory.soul import edit_soul

    if not body.content.strip():
        raise HTTPException(status_code=400, detail="SOUL.md must not be empty.")
    path = soul_path()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="SOUL.md does not exist yet.")
    try:
        edit_soul(path, lambda soul: soul.set_body(body.content))
    except TimeoutError as exc:
        raise HTTPException(status_code=409, detail="SOUL.md is busy; try again.") from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save: {exc}") from exc
    return {"ok": True, **_payload(request)}


@router.put("/initiative", summary="Set how much initiative the assistant takes")
def put_initiative(body: InitiativeBody, request: Request) -> dict[str, Any]:
    """Persist ``[brain] proactivity``, then apply it live to every surface.

    The write comes first: a level that could not be saved is not shown as set.
    """
    from dodaios.brain import proactivity
    from dodaios.core import config_writer
    from dodaios.core.config import resolve_config_path

    try:
        # Honour JARVIS_CONFIG so the write lands in the file load_config reads.
        config_writer.set_proactivity(body.level, path=resolve_config_path())
    except Exception as exc:  # noqa: BLE001 — reported to the page, nothing applied
        log.warning("soul: initiative level not saved", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not save: {exc}") from exc
    level = proactivity.apply_level(body.level)
    brain = getattr(_config(request), "brain", None)
    if brain is not None:
        try:
            brain.proactivity = level
        except Exception:  # noqa: BLE001 — the live level above already answers
            log.debug("soul: in-memory brain.proactivity not updated", exc_info=True)
    return {"ok": True, **_payload(request)}


def _forget_notebook_copy(notebook: Any, text: str) -> None:
    """Remove the notebook note a forgotten memory was imported from, if one is left.

    Otherwise the note would come back on the page, and stay in the prompt,
    the moment its copy in the vault is gone.
    """
    same = _same_note(text)
    try:
        for target in ("memory", "user"):  # the import filed by kind, not by notebook
            for entry in notebook.entries().get(target, []):
                if _same_note(entry.text) == same:
                    notebook.apply(
                        target=target,
                        operation="remove",
                        entry_id=entry.id,
                        source="soul page: forgotten by the user",
                    )
    except (ValueError, OSError):  # the memory itself is forgotten; the copy stays listed
        log.warning("soul: a forgotten memory's notebook copy could not be removed", exc_info=True)


@router.delete("/entries/{target}/{entry_id}", summary="Forget one learned note")
def forget_entry(
    target: Literal["soul", "memory", "user"], entry_id: str, request: Request
) -> dict[str, Any]:
    """Remove one note.

    A memory of the vault is forgotten with every version of it. A notebook
    note is removed from its file; the learning ledger keeps its old text.
    """
    from dodaios.memory.learning import notebook as notebook_module
    from dodaios.memory.vault import pages
    from dodaios.memory.vault import runtime as vault_runtime

    vault = vault_runtime.active()
    notebook = notebook_module.active()
    memory = vault.get(entry_id) if vault is not None and target != "soul" else None
    if vault is not None and memory is not None and pages.forget(vault, entry_id):
        if notebook is not None:
            _forget_notebook_copy(notebook, memory.text)
        return {"ok": True, **_payload(request)}
    if notebook is None:
        raise HTTPException(
            status_code=503, detail="The learning loop is not running in this session."
        )
    try:
        notebook.apply(
            target=target,
            operation="remove",
            entry_id=entry_id,
            source="soul page: forgotten by the user",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **_payload(request)}
