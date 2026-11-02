"""Locale, ``verse.*`` settings and the companion topic (BW10, BW12; contract 3.2, 12, 14).

``welcome.locale`` carries the frontend i18n chunk ``ship`` for the
person's language, read from the same JSON files the web app bundles, so a
string change needs no Unreal rebuild. ``settings.set`` validates and writes
the ``verse.*`` keys and answers with every setting; ``settings.changed``
then reaches Verse and, through ``VerseSettingsChanged`` on the bus, the web
UI. The ``companion`` topic sends the active pet and the overlay style, and
an update within 2 s of a ``PetChanged``.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from .. import protocol as P
from ..settings_store import SettingsError, SettingsStore
from .base import RelayBase

log = logging.getLogger(__name__)

LOCALES = ("en", "de", "es", "pt", "zh")
SHIP_DIR = (
    Path(__file__).resolve().parents[2]
    / "ui"
    / "web"
    / "frontend"
    / "src"
    / "i18n"
    / "locales"
    / "ship"
)


def _flatten(prefix: str, node: Any, out: dict[str, str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            _flatten(f"{prefix}.{key}" if prefix else str(key), value, out)
    elif isinstance(node, str):
        out[prefix] = node


@lru_cache(maxsize=8)
def _chunk(lang: str, root: str) -> dict[str, str]:
    out: dict[str, str] = {}
    folder = Path(root)
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob(f"*.{lang}.json")):
        try:
            _flatten("", json.loads(path.read_text(encoding="utf-8")), out)
        except (OSError, ValueError):
            log.warning("verse locale: %s unreadable", path.name)
    return out


def locale_strings(lang: str, root: Path = SHIP_DIR) -> dict[str, str]:
    """The ``ship`` chunk for ``lang`` over the English one (missing keys fall back)."""
    strings = dict(_chunk("en", str(root)))
    if lang != "en":
        strings.update(_chunk(lang, str(root)))
    return strings


def ui_language(config: Any) -> str:
    lang = str(getattr(getattr(config, "ui", None), "language", "") or "en").lower()
    lang = lang.split("-", 1)[0].split("_", 1)[0]
    return lang if lang in LOCALES else "en"


def locale_block(config: Any, root: Path = SHIP_DIR) -> dict[str, Any]:
    lang = ui_language(config)
    return {"lang": lang, "fallback": "en", "strings": locale_strings(lang, root)}


class SettingsRelay(RelayBase):
    """``settings.set`` and the live ``settings.changed`` push."""

    topics = ()

    def __init__(self, session: Any, backend: Any, store: SettingsStore, publish: Any) -> None:
        super().__init__(session, backend)
        self.store = store
        self.publish = publish

    async def start(self) -> None:
        self.session.hub.command("settings.set", self._set)

    async def _set(self, session: Any, msg: P.Inbound) -> dict[str, Any]:
        try:
            settings = self.store.update(dict(msg.data))
        except SettingsError as exc:
            raise P.BridgeError("bad_request", str(exc)) from exc
        changed = {k: settings[k] for k in msg.data if k in settings}
        self.session.send("settings.changed", changed)
        if self.publish is not None:
            await self.publish(changed)
        return {"settings": settings}


class CompanionRelay(RelayBase):
    topics = ("companion",)

    async def start(self) -> None:
        from dodaios.core import events as E

        self.listen([E.PetChanged], self._on_pet)
        self.last: dict[str, Any] | None = None

    async def read(self) -> dict[str, Any]:
        pet = await self.backend.active_pet()
        pet_id = pet.get("pet_id")
        return {
            "pet_id": pet_id if isinstance(pet_id, str) and pet_id else None,
            "look": str(pet.get("look") or ""),
            "style": str(pet.get("style") or "default"),
        }

    async def subscribe(self, topic: str) -> None:
        self.last = await self.read()
        self.session.outbox.snapshot_of["companion"] = lambda: self.last
        self.session.send("companion.snapshot", self.last, topic="companion", feed=True)

    async def _on_pet(self, _event: Any) -> None:
        if "companion" not in self.subscribed:
            return
        current = await self.read()
        if current != self.last:
            self.last = current
            self.session.send("companion.update", current, topic="companion", feed=True)
