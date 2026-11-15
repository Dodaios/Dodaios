"""``/api/agent-chat/lead/rituals``: the person's rituals, and their clicks on them.

A ritual is a sequence the person wrote beforehand and starts with a short
phrase (:mod:`dodaios.rituals.service`). These routes are what the assistant's
panel uses: list, write, change, remove, start one now, and ask whether a
sentence would start one.
"""

from __future__ import annotations

from typing import Any, Final

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict

router = APIRouter(prefix="/api/agent-chat/lead/rituals", tags=["rituals"])

#: A ritual's steps are instructions that later run with the person's standing,
#: the moment the phrase is said. Writing, changing or starting one through the
#: raw route is therefore something the assistant asks about first; a run nobody
#: watches cannot plant or start one.
_ASKS_FIRST: Final[dict[str, Any]] = {"x-jarvis-dangerous": True}


class RitualStepBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Kept when a step is only reworded, so what belongs to it stays with it.
    id: str = ""
    #: ``now`` (the moment the phrase is said) or ``ahead`` (gathered before).
    when: str
    text: str


class RitualBody(BaseModel):
    """A ritual the person writes by hand; the service checks lengths and clashes."""

    model_config = ConfigDict(extra="forbid")

    name: str
    phrases: list[str]
    steps: list[RitualStepBody]
    enabled: bool = True
    #: ``HH:MM`` on the person's clock; leave both empty for any time of day.
    window_from: str = ""
    window_to: str = ""
    #: Monday is 0; empty means every day.
    weekdays: list[int] = []
    once_per_day: bool = True
    prepare_from: str = ""


class RitualPatchBody(BaseModel):
    """Only the fields that are sent change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    phrases: list[str] | None = None
    steps: list[RitualStepBody] | None = None
    enabled: bool | None = None
    window_from: str | None = None
    window_to: str | None = None
    weekdays: list[int] | None = None
    once_per_day: bool | None = None
    prepare_from: str | None = None


#: ``RitualError.code`` -> HTTP status. Anything unknown reads as a bad request.
_STATUS: Final[dict[str, int]] = {
    "not_found": 404,
    "invalid": 422,
    "conflict": 409,
    "state": 409,
    "limit": 409,
    "unavailable": 503,
}


def _refused(exc: Any) -> HTTPException:
    return HTTPException(status_code=_STATUS.get(str(exc.code), 400), detail=str(exc.message))


def _view(ritual: Any, *, with_text: bool = False) -> dict[str, Any]:
    from dodaios.rituals import service

    today = service.today_of(ritual.id)
    return {
        "ritual": ritual.to_dict(),
        "today": today.to_dict(with_text=with_text) if today is not None else None,
    }


@router.get("", summary="Rituals: what a short phrase starts, and where each stands today")
def get_rituals() -> dict[str, Any]:
    from dodaios.rituals import service

    return service.overview()


@router.post("", status_code=201, summary="Write a new ritual", openapi_extra=_ASKS_FIRST)
async def post_ritual(body: RitualBody) -> dict[str, Any]:
    from dodaios.rituals import service
    from dodaios.rituals.models import RitualError

    try:
        ritual = await service.create(origin="owner", **body.model_dump())
    except RitualError as exc:
        raise _refused(exc) from exc
    return _view(ritual)


@router.get("/match", summary="Would this sentence start a ritual right now? Starts nothing")
def match_ritual(text: str = Query(..., min_length=1, max_length=400)) -> dict[str, Any]:
    from dodaios.rituals import service

    found = service.find_match(text)
    if found is None:
        return {"matched": False, "fires": False, "blocked": "", "ritual": None, "phrase": ""}
    return {
        "matched": True,
        "fires": found.fires,
        "blocked": found.blocked,
        "ritual": found.ritual.to_dict(),
        "phrase": found.phrase,
    }


@router.get("/{ritual_id}", summary="One ritual and what was gathered for it today")
def get_ritual(ritual_id: str) -> dict[str, Any]:
    from dodaios.rituals import service

    ritual = service.get(ritual_id)
    if ritual is None:
        raise HTTPException(status_code=404, detail="No such ritual")
    return _view(ritual, with_text=True)


@router.patch(
    "/{ritual_id}",
    summary="Change a ritual's wording, phrases, steps or times",
    openapi_extra=_ASKS_FIRST,
)
async def patch_ritual(ritual_id: str, body: RitualPatchBody) -> dict[str, Any]:
    from dodaios.rituals import service
    from dodaios.rituals.models import RitualError

    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(status_code=422, detail="Nothing to change")
    try:
        ritual = await service.update(ritual_id, **changes)
    except RitualError as exc:
        raise _refused(exc) from exc
    return _view(ritual)


@router.delete("/{ritual_id}", summary="Remove a ritual")
async def delete_ritual(ritual_id: str) -> dict[str, Any]:
    from dodaios.rituals import service
    from dodaios.rituals.models import RitualError

    try:
        await service.remove(ritual_id)
    except RitualError as exc:
        raise _refused(exc) from exc
    return {"ok": True, "id": ritual_id}


@router.post("/{ritual_id}/prepare", summary="Gather now what a ritual wants ready ahead")
async def prepare_ritual(ritual_id: str) -> dict[str, Any]:
    from dodaios.rituals import prepare, service
    from dodaios.rituals.models import RitualError

    try:
        # The person's own click: gathers anew although today's result is still good.
        started = await prepare.start(ritual_id, by_user=True, again=True)
    except RitualError as exc:
        raise _refused(exc) from exc
    ritual = service.get(ritual_id)
    if ritual is None:
        raise HTTPException(status_code=404, detail="No such ritual")
    return {"started": started, **_view(ritual)}


@router.post(
    "/{ritual_id}/run",
    summary="Start a ritual now, whatever the clock says",
    openapi_extra=_ASKS_FIRST,
)
async def run_ritual(ritual_id: str) -> dict[str, Any]:
    from dodaios.rituals import service
    from dodaios.rituals.models import RitualError

    try:
        # The person's own click: it starts the ritual outside its window and
        # a second time on the same day.
        return await service.fire(ritual_id, via="button", force=True)
    except RitualError as exc:
        raise _refused(exc) from exc
