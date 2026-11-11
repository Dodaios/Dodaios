"""Notifications and reminders (``/api/notify``).

* ``GET  /api/notify/settings``              the person's choices.
* ``PUT  /api/notify/settings``              change some of them (partial body).
* ``POST /api/notify/test``                  show a test notification now.
* ``GET  /api/notify/telegram``              whether approvals can reach Telegram.
* ``GET  /api/notify/reminders``             what is coming up (``days``).
* ``POST /api/notify/reminders``             a reminder from plain speech or ISO.
* ``POST /api/notify/reminders/capture``     a brain dump into separate items.
* ``POST /api/notify/reminders/{id}/done``   tick it off.
* ``POST /api/notify/reminders/{id}/snooze`` move it (``minutes`` or ``until``).

Vault handlers are plain ``def`` (SQLite off the loop); only the test
notification awaits.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from dodaios.notify import reminders
from dodaios.notify.settings import load_settings, save_settings, valid_clock

router = APIRouter(prefix="/api/notify", tags=["notify"])


class SettingsPatch(BaseModel):
    enabled: bool | None = None
    kinds: dict[str, bool] | None = None
    quiet_hours: dict[str, Any] | None = None
    telegram_approvals: bool | None = None
    phone: dict[str, bool] | None = None


class NewReminder(BaseModel):
    text: str = Field(default="", max_length=2000)
    #: ISO local date-time, or the time words as said ("Friday at 9").
    when: str = Field(default="", max_length=200)
    timezone: str = Field(default="", max_length=80)


class Dump(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    timezone: str = Field(default="", max_length=80)


class Snooze(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)
    #: ISO local date-time or time words; wins over ``minutes``.
    until: str = Field(default="", max_length=200)
    timezone: str = Field(default="", max_length=80)


def _vault() -> Any:
    from dodaios.memory.vault.runtime import active

    vault = active()
    if vault is None:
        raise HTTPException(status_code=503, detail="memory vault is not running")
    return vault


def _now(timezone: str) -> datetime:
    return datetime.now(reminders.person_zone(timezone or None))


# ------------------------------------------------------------------ settings


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return load_settings().to_dict()


@router.put("/settings")
def put_settings(body: SettingsPatch) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    quiet = patch.get("quiet_hours") or {}
    for key in ("start", "end"):
        if key in quiet and not valid_clock(str(quiet[key])):
            raise HTTPException(status_code=400, detail=f"quiet_hours.{key} must be HH:MM")
    return save_settings(patch).to_dict()


@router.post("/test")
async def test_notification(request: Request) -> dict[str, Any]:
    from dodaios.notify.notifier import current_notifier

    notifier = current_notifier()
    if notifier is None:
        raise HTTPException(status_code=503, detail="notifications are not running")
    lang = reminders.notification_language("")
    verdict = await notifier.notify(
        "reminder",
        reminders.phrase("test_title", lang),
        reminders.phrase("test_body", lang),
        ignore_focus=True,
    )
    return verdict.to_dict()


@router.get("/telegram")
def telegram_state(request: Request) -> dict[str, Any]:
    """Whether a waiting approval could reach the owner's Telegram right now."""
    from dodaios.channels.telegram_approvals import owner_chat_id

    manager = getattr(request.app.state, "channel_manager", None)
    connected = False
    try:
        connected = manager is not None and "telegram" in manager.started()
    except Exception:  # noqa: BLE001 — a manager mid-start counts as not connected
        connected = False
    cfg = getattr(request.app.state, "config", None) or getattr(request.app.state, "cfg", None)
    owner = owner_chat_id(cfg) if cfg is not None else None
    return {"connected": bool(connected), "owner_known": owner is not None}


# ----------------------------------------------------------------- reminders


@router.get("/reminders")
def list_reminders(days: int = Query(default=14, ge=1, le=365)) -> dict[str, Any]:
    return {"items": reminders.list_due(_vault(), days=days)}


@router.post("/reminders", status_code=201)
def create_reminder(body: NewReminder) -> dict[str, Any]:
    vault = _vault()
    now = _now(body.timezone)
    text = body.text.strip()
    if not text and not body.when.strip():
        raise HTTPException(status_code=400, detail="text is missing")
    due, rest, has_time = reminders.resolve_due(body.when, now=now, text=text)
    rest = rest or text
    if due is None:
        return {"needs_time": True, "text": rest}
    if not rest:
        raise HTTPException(status_code=400, detail="text is missing")
    result = reminders.create_reminder(vault, rest, due, via="app", zone=str(now.tzinfo))
    if result.action == "refused":
        raise HTTPException(status_code=422, detail="not saved: looks like a secret")
    memory = result.memory
    row = reminders.row_of(memory, vault.now()) if memory is not None else {}
    return {**row, "has_time": has_time, "existing": result.action == "existing"}


@router.post("/reminders/capture", status_code=201)
def capture(body: Dump) -> dict[str, Any]:
    vault = _vault()
    rows = reminders.capture_dump(vault, body.text, now=_now(body.timezone), evidence=body.text)
    return {"items": rows}


@router.post("/reminders/{memory_id}/done")
def done(memory_id: str) -> dict[str, Any]:
    if not reminders.mark_done(_vault(), memory_id):
        raise HTTPException(status_code=404, detail="no open reminder with that id")
    return {"ok": True}


@router.post("/reminders/{memory_id}/snooze")
def snooze(memory_id: str, body: Snooze) -> dict[str, Any]:
    vault = _vault()
    now = _now(body.timezone)
    until: datetime | None = None
    if body.until.strip():
        until, _rest, _has_time = reminders.resolve_due(body.until, now=now)
        if until is None:
            raise HTTPException(status_code=400, detail="until is not a time I understand")
    if until is None:
        until = now + timedelta(minutes=body.minutes or 60)
    moved = reminders.snooze(vault, memory_id, until)
    if moved is None:
        raise HTTPException(status_code=404, detail="no reminder with that id")
    return reminders.row_of(moved, vault.now())


__all__ = ["router"]
