"""REST API for the pets (docs/pets.md).

Pets live in the app: the active pet is how the app draws the assistant, an
agent can wear any pet, and the user can draw their own. They are no longer
shown on the desktop.

Endpoints (mounted by the WebServer in ``_build_app()``):

    GET    /api/pets                   → the active pet and every pet
                                         (built-in + user-created).
    GET    /api/pets/template.png      → the blank sprite-sheet template.
    GET    /api/pets/{id}/sheet.png    → a pet's sprite sheet.
    PUT    /api/pets/active            → pick the active pet; saved to
                                         ``[ui] pet_id``.
    POST   /api/pets                   → create a pet from an uploaded sheet.
    DELETE /api/pets/{id}              → delete a user-created pet.

Under the CLI-first contract every action here is also a
``jarvis api pets <op>`` command. Every change of the active pet is announced
as ``PetChanged`` so every open window redraws its pets from one event.

Instances: both desktop instances read ONE ``jarvis.toml``, so ``PUT /active``
answers 409 on a dev instance: a pick there would silently change the default
app's pet. User-created pets live in each instance's own data directory, so
creating and deleting them is allowed everywhere.

The pet engine (``dodaios.ui.pets``) decodes images with Pillow, so it is
imported inside the handlers: nothing here loads on the boot path (AP-26).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.responses import Response
from starlette.types import Message, Receive

from dodaios.core.config import normalize_pet_id
from dodaios.ui.pets.states import DEFAULT_PET_ID, NO_PET_ID, PET_STATES

log = logging.getLogger(__name__)

#: Ceiling of a whole request body on this router: the 2 MB sheet plus the
#: manifest and the form overhead. Checked BEFORE the multipart parser runs,
#: because Starlette spools an entire upload to disk before a handler (or a
#: FastAPI dependency) ever sees it — a per-handler read cap alone would still
#: accept a multi-gigabyte body.
MAX_REQUEST_BYTES = 3 * 1024 * 1024

_TOO_LARGE = "The upload is too large (the sprite sheet may be at most 2 MB)."


def _limited_receive(receive: Receive, limit: int) -> Receive:
    """Wrap ``receive`` so a body without ``Content-Length`` stops at ``limit``."""
    seen = 0

    async def counting() -> Message:
        nonlocal seen
        message = await receive()
        if message.get("type") == "http.request":
            seen += len(message.get("body", b""))
            if seen > limit:
                raise HTTPException(status_code=413, detail=_TOO_LARGE)
        return message

    return counting


class _BodyLimitRoute(APIRoute):
    """An ``APIRoute`` that refuses an oversized body before parsing it.

    A declared ``Content-Length`` above :data:`MAX_REQUEST_BYTES` is answered
    with 413 at once; a chunked body without one is counted while it streams
    and cut off at the same ceiling.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        handler = super().get_route_handler()

        async def limited(request: Request) -> Response:
            if request.method in ("POST", "PUT", "PATCH"):
                declared = request.headers.get("content-length")
                if declared is None:
                    request = Request(
                        request.scope, _limited_receive(request.receive, MAX_REQUEST_BYTES)
                    )
                else:
                    try:
                        size = int(declared)
                    except ValueError:
                        raise HTTPException(
                            status_code=400, detail="Invalid Content-Length header."
                        ) from None
                    if size > MAX_REQUEST_BYTES:
                        raise HTTPException(status_code=413, detail=_TOO_LARGE)
            return await handler(request)

        return limited


router = APIRouter(prefix="/api/pets", tags=["pets"], route_class=_BodyLimitRoute)

#: A user-created pet's sheet never changes: a new upload gets a new id.
_IMMUTABLE_CACHE = {"Cache-Control": "public, max-age=31536000, immutable"}
#: A built-in sheet can change with an app update under the same URL, so the
#: browser revalidates it (FileResponse answers with an ETag).
_REVALIDATE_CACHE = {"Cache-Control": "no-cache"}
_NOSNIFF = {"X-Content-Type-Options": "nosniff"}


class ActiveBody(BaseModel):
    pet_id: str = Field(..., min_length=1, max_length=40)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ui(request: Request) -> Any | None:
    cfg = getattr(request.app.state, "config", None) or getattr(request.app.state, "cfg", None)
    return getattr(cfg, "ui", None)


def _configured_pet_id(request: Request) -> str:
    return normalize_pet_id(getattr(_ui(request), "pet_id", None)) or DEFAULT_PET_ID


def _config_path() -> Any:
    """The ``jarvis.toml`` this process loaded (honours ``JARVIS_CONFIG``)."""
    from dodaios.core.config import resolve_config_path

    return resolve_config_path()


def _set_ui_value(request: Request, field: str, value: object) -> None:
    """Best-effort in-memory update so a later read agrees before a restart."""
    ui = _ui(request)
    if ui is None:
        return
    try:
        setattr(ui, field, value)
    except Exception as exc:  # noqa: BLE001 — a frozen model is not an error
        log.debug("in-memory ui.%s update skipped: %s", field, exc)


def _refuse_on_secondary_instance() -> None:
    from dodaios.core.instance import current_instance

    instance = current_instance()
    if not instance.owns_ambient_duties:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The active pet belongs to the default app; the {instance.label} "
                "instance does not change the shared setting. "
                "Change the pet in the regular Dodaios app."
            ),
        )


def _pet_exists(pet_id: str) -> bool:
    """A pet id exists when it names a pet folder on disk (never ``none``)."""
    if pet_id == NO_PET_ID:
        return False
    from dodaios.ui.pets import loader

    return loader.find_pet_dir(pet_id) is not None


def _pet_json(manifest: Any) -> dict[str, Any]:
    """One pet as the settings page needs it.

    ``animations`` is resolved for EVERY state (a state the manifest leaves
    out already carries its fallback's row), so no client has to repeat the
    fallback table.
    """
    animations: dict[str, dict[str, Any]] = {}
    for state in PET_STATES:
        _resolved, spec = manifest.spec_for(state)
        animations[state] = {
            "row": spec.row,
            "frames": spec.frames,
            "fps": spec.fps,
            "loop": spec.loop,
            # 0 / 1 when the row has no accent (every cell on every loop).
            "accent_frames": int(getattr(spec, "accent_frames", 0)),
            "accent_every": int(getattr(spec, "accent_every", 1)),
        }
    return {
        "id": manifest.id,
        "name": manifest.name,
        "description": manifest.description,
        "builtin": bool(manifest.builtin),
        "frame_size": manifest.frame_size,
        "animations": animations,
        "sheet_url": f"/api/pets/{manifest.id}/sheet.png",
    }


async def _publish_changed(request: Request, pet_id: str, *, source: str) -> None:
    bus = getattr(request.app.state, "bus", None)
    if bus is None:
        return
    from dodaios.core.events import PetChanged

    try:
        await bus.publish(
            PetChanged(pet_id=pet_id, source=source)
        )
    except Exception as exc:  # noqa: BLE001 — a bus hiccup must not fail the change
        log.warning("PetChanged publish failed: %s", exc)


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


@router.get("")
def list_pets(request: Request) -> dict[str, Any]:
    """The active pet and every pet."""
    from dodaios.ui.pets import loader

    manifests = loader.list_pets()
    known = {m.id for m in manifests}
    configured = _configured_pet_id(request)
    # An id whose folder is gone (a deleted or broken pet) and the old "none"
    # are drawn as the default pet, so the answer says the same.
    active = configured if configured in known else DEFAULT_PET_ID
    return {"active": active, "pets": [_pet_json(m) for m in manifests]}


#: The blank sprite-sheet template "Create pet" offers for download: seven
#: tinted state rows in ``PET_STATES`` order, eight 48 px cells each.
_TEMPLATE_PNG = Path(__file__).resolve().parents[1] / "pets" / "template" / "template.png"


@router.get("/template.png", response_model=None)
def pet_template() -> FileResponse:
    """The sprite-sheet template for a user-drawn pet.

    Registered before the ``/{pet_id}/...`` routes so no pet id can shadow it.
    Ships with the app and changes only with an app update, so the browser
    revalidates it like a built-in sheet.
    """
    if not _TEMPLATE_PNG.is_file():
        raise HTTPException(status_code=404, detail="The template is not installed.")
    return FileResponse(
        str(_TEMPLATE_PNG),
        media_type="image/png",
        filename="pet-template.png",
        headers={**_NOSNIFF, **_REVALIDATE_CACHE},
    )


@router.get("/{pet_id}/sheet.png", response_model=None)
def pet_sheet(pet_id: str) -> FileResponse:
    """A pet's sprite sheet. The id is shape-checked before any path is built."""
    from dodaios.ui.pets import loader
    from dodaios.ui.pets.manifest import PetManifestError

    normalized = normalize_pet_id(pet_id)
    found = loader.find_pet_dir(normalized) if normalized else None
    if found is None:
        raise HTTPException(status_code=404, detail="Unknown pet.")
    folder, builtin = found
    try:
        manifest = loader.read_manifest(folder, builtin=builtin)
    except PetManifestError as exc:
        log.warning("pet %r sheet not served: %s", normalized, exc)
        raise HTTPException(status_code=404, detail="Unknown pet.") from exc
    return FileResponse(
        str(folder / manifest.sheet),
        media_type="image/png",
        headers={**_NOSNIFF, **(_REVALIDATE_CACHE if builtin else _IMMUTABLE_CACHE)},
    )


@router.put("/active")
async def put_active(body: ActiveBody, request: Request) -> dict[str, Any]:
    """Pick the active pet: save ``[ui] pet_id`` and announce it."""
    pet_id = normalize_pet_id(body.pet_id)
    if pet_id is None:
        raise HTTPException(status_code=400, detail=f"'{body.pet_id.strip()}' is not a pet id.")
    if pet_id == NO_PET_ID:
        raise HTTPException(status_code=400, detail="Pick a pet: 'none' is no longer offered.")
    if not await asyncio.to_thread(_pet_exists, pet_id):
        raise HTTPException(status_code=404, detail=f"There is no pet '{pet_id}'.")
    _refuse_on_secondary_instance()

    _set_ui_value(request, "pet_id", pet_id)
    persisted = False
    try:
        from dodaios.core import config_writer

        await asyncio.to_thread(config_writer.set_pet_id, pet_id, path=_config_path())
        persisted = True
    except Exception as exc:  # noqa: BLE001 — the running app still uses the pick
        log.warning("pet_id persist failed (kept for this run): %s", exc)

    await _publish_changed(request, pet_id, source="settings")
    return {"ok": True, "active": pet_id, "persisted": persisted}


@router.post("", status_code=201)
async def create_pet(
    sheet: UploadFile = File(...),  # noqa: B008 — FastAPI dependency default
    name: str = Form(""),
    description: str = Form(""),
    manifest: str | None = Form(None),
    frame_size: str | None = Form(None),
) -> dict[str, Any]:
    """Create a pet from an uploaded sprite sheet (and optional ``pet.json``).

    The sheet is read with a ceiling rather than whole — one byte over the
    limit is enough for the store to refuse it. Every refusal is a 400 whose
    detail is the store's own user-readable sentence.
    """
    from dodaios.ui.pets import loader
    from dodaios.ui.pets.manifest import MAX_SHEET_BYTES, PetManifestError
    from dodaios.ui.pets.store import PetStore

    size: int | None = None
    if frame_size is not None and frame_size.strip():
        try:
            size = int(frame_size.strip())
        except ValueError:
            raise HTTPException(
                status_code=400, detail=f"'{frame_size.strip()}' is not a frame size."
            ) from None

    data = await sheet.read(MAX_SHEET_BYTES + 1)
    store = PetStore(loader.custom_root())
    try:
        created = await asyncio.to_thread(
            store.add,
            sheet_bytes=data,
            name=name,
            description=description,
            manifest_json=manifest,
            frame_size=size,
        )
    except PetManifestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log.info("Pet %r created (%s).", created.id, created.name)
    return _pet_json(created)


@router.delete("/{pet_id}", openapi_extra={"x-jarvis-dangerous": True})
async def delete_pet(pet_id: str, request: Request) -> dict[str, Any]:
    """Delete a user-created pet. Deleting the active one switches to the default."""
    from dodaios.ui.pets import loader
    from dodaios.ui.pets.manifest import USER_ID_RE
    from dodaios.ui.pets.store import PetStore

    normalized = normalize_pet_id(pet_id)
    if normalized is None:
        raise HTTPException(status_code=404, detail="Unknown pet.")
    if not USER_ID_RE.match(normalized):
        raise HTTPException(
            status_code=400, detail="Built-in pets cannot be deleted, only pets you created."
        )
    store = PetStore(loader.custom_root())
    if not await asyncio.to_thread(store.delete, normalized):
        raise HTTPException(status_code=404, detail="Unknown pet.")
    log.info("Pet %r deleted.", normalized)

    active = _configured_pet_id(request)
    if active != normalized:
        return {"ok": True, "deleted": normalized, "active": active}

    # The active pet is gone: fall back to the default pet. On a secondary
    # instance the shared setting is not this instance's to change (its pets
    # live in its own data directory, so the default app's pick is unaffected).
    from dodaios.core.instance import current_instance

    if current_instance().owns_ambient_duties:
        _set_ui_value(request, "pet_id", DEFAULT_PET_ID)
        try:
            from dodaios.core import config_writer

            await asyncio.to_thread(config_writer.set_pet_id, DEFAULT_PET_ID, path=_config_path())
        except Exception as exc:  # noqa: BLE001 — the running app still uses the default
            log.warning("pet_id fallback persist failed: %s", exc)
        await _publish_changed(request, DEFAULT_PET_ID, source="pet_deleted")
    return {"ok": True, "deleted": normalized, "active": DEFAULT_PET_ID}
