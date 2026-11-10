"""Owner-only WhatsApp channel: the owner's own chat continues the lead conversation.

Shape and rules mirror :class:`dodaios.channels.telegram.TelegramChannel`:

* the channel is OFF by default (``enabled`` in ``mobile/whatsapp.json`` under
  the app's data directory, or ``DODAIOS_WHATSAPP_ENABLED=1``), and a disabled
  channel starts silently so the channel manager stays green;
* only ONE sender is ever answered: the owner. The first private message that
  arrives within :data:`FIRST_CONTACT_PAIRING_WINDOW_S` of the channel coming
  up claims the owner seat (``owner_jid``) and is persisted; everything else —
  other people, groups, broadcasts — is dropped without a reply;
* the bridge marks the owner's messages ``whatsapp_private`` so
  :mod:`dodaios.channels.chat_bridge` routes them into the lead's one
  conversation and sends the answer back to the same chat.

What is deliberately NOT here: a WhatsApp client. The person wants their OWN
WhatsApp (a linked device, like WhatsApp Web), not a business number, and
there is no maintained Python library for the linked-device protocol that does
not ship a native binary of its own. So the channel speaks to a small local
bridge process over a documented HTTP contract (:class:`BridgeTransport`), and
the bridge is what is missing. Until one is linked, ``enabled=true`` starts
the channel in a "waiting for bridge" state and reports it honestly in Settings.
See ``docs/mobile-companion.md`` for the contract and the open points.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol
from uuid import uuid4

from pydantic import BaseModel

from dodaios.channels.base import FIRST_CONTACT_PAIRING_WINDOW_S, ChannelMessage, ChannelSession
from dodaios.channels.manager import ChannelContext, ChannelStartError
from dodaios.core.paths import user_data_dir

if TYPE_CHECKING:  # pragma: no cover
    from dodaios.core.bus import EventBus
    from dodaios.core.events import Event

log = logging.getLogger(__name__)

#: The local bridge's default address (a linked-device bridge on this machine).
DEFAULT_BRIDGE_URL = "http://127.0.0.1:3737"


class WhatsAppConfig(BaseModel):
    """Everything the channel needs; no credential ever lives here."""

    enabled: bool = False
    #: The owner's WhatsApp id (``<number>@s.whatsapp.net``); claimed on first contact.
    owner_jid: str = ""
    bridge_url: str = DEFAULT_BRIDGE_URL
    pair_on_first_private_message: bool = True


def _config_path() -> Path:
    return user_data_dir() / "mobile" / "whatsapp.json"


def load_whatsapp_config(path: Path | None = None) -> WhatsAppConfig:
    """The saved config; ``DODAIOS_WHATSAPP_ENABLED`` overrides the switch."""
    target = path or _config_path()
    config = WhatsAppConfig()
    try:
        config = WhatsAppConfig.model_validate_json(target.read_text(encoding="utf-8"))
    except FileNotFoundError:  # never configured: the defaults (off) apply
        pass
    except (ValueError, OSError):
        log.warning("whatsapp: the saved channel config is unreadable; using defaults")
    flag = os.environ.get("DODAIOS_WHATSAPP_ENABLED", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        config.enabled = True
    elif flag in {"0", "false", "no", "off"}:
        config.enabled = False
    return config


def save_whatsapp_config(config: WhatsAppConfig, path: Path | None = None) -> None:
    target = path or _config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".whatsapp-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(config.model_dump_json(indent=2))
        os.replace(name, target)
    except OSError:
        try:
            os.unlink(name)
        except OSError:  # the temp file is already gone
            pass
        raise


# ------------------------------------------------------------------ transport

InboundHandler = Callable[[dict[str, Any]], Awaitable[None]]


class WhatsAppTransport(Protocol):
    """What a linked-device bridge must offer the channel."""

    async def start(self, on_message: InboundHandler) -> None: ...

    async def stop(self) -> None: ...

    async def send_text(self, jid: str, text: str) -> None: ...

    def status(self) -> dict[str, Any]: ...


class BridgeTransport:
    """HTTP contract to a local linked-device bridge (not shipped here).

    ``GET  {url}/status``                → ``{"linked": bool, "me": "<jid>"}``
    ``GET  {url}/messages?wait=<s>``     → ``{"messages": [{"id", "from", "text",
                                            "private": bool, "ts": <ms>}]}`` (long poll)
    ``POST {url}/send`` ``{"to", "text"}`` → ``{"ok": true}``

    The bridge holds the WhatsApp session; this process never sees its keys.
    """

    def __init__(self, url: str = DEFAULT_BRIDGE_URL, *, pool: Any | None = None) -> None:
        self.url = url.rstrip("/")
        self._pool = pool
        self._task: asyncio.Task[None] | None = None
        self._linked = False
        self._me = ""

    def _client(self) -> Any:
        if self._pool is None:
            from dodaios.core.http_pool import HttpClientPool

            self._pool = HttpClientPool(
                timeout_s=40, client_kwargs={"follow_redirects": False, "trust_env": False}
            )
        return self._pool.client()

    async def start(self, on_message: InboundHandler) -> None:
        try:
            response = await self._client().get(f"{self.url}/status")
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001 — reported as "no bridge", with the class only
            raise ChannelStartError(
                f"WhatsApp bridge not reachable at {self.url} ({type(exc).__name__}). "
                "Start a linked-device bridge first (docs/mobile-companion.md)."
            ) from None
        self._linked = bool(data.get("linked"))
        self._me = str(data.get("me") or "")
        self._task = asyncio.create_task(self._poll(on_message), name="whatsapp-bridge-poll")

    async def _poll(self, on_message: InboundHandler) -> None:
        while True:
            try:
                response = await self._client().get(f"{self.url}/messages", params={"wait": 25})
                response.raise_for_status()
                for item in response.json().get("messages") or []:
                    if isinstance(item, dict):
                        await on_message(item)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the bridge went away; keep trying
                log.debug("whatsapp: bridge poll failed: %s", type(exc).__name__)
                await asyncio.sleep(5)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    async def send_text(self, jid: str, text: str) -> None:
        response = await self._client().post(f"{self.url}/send", json={"to": jid, "text": text})
        response.raise_for_status()

    def status(self) -> dict[str, Any]:
        return {"linked": self._linked, "me": self._me, "bridge_url": self.url}


# -------------------------------------------------------------------- channel


class WhatsAppChannel:
    """Owner-only WhatsApp channel over a linked-device bridge."""

    name = "whatsapp"

    def __init__(
        self,
        bus: EventBus,
        config: WhatsAppConfig | None = None,
        transport: WhatsAppTransport | None = None,
        *,
        config_path: Path | None = None,
    ) -> None:
        self._bus = bus
        self._cfg = config if config is not None else load_whatsapp_config(config_path)
        self._config_path = config_path
        self._transport = transport
        self._inbox: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self._sessions: dict[str, ChannelSession] = {}
        self._started = False
        self._active = False
        self._pairing_closes_at = time.monotonic() + FIRST_CONTACT_PAIRING_WINDOW_S
        self._dropped = 0

    @classmethod
    def from_context(cls, ctx: ChannelContext) -> WhatsAppChannel:
        cfg = ctx.config.get("whatsapp_config")
        if not isinstance(cfg, WhatsAppConfig):
            cfg = load_whatsapp_config()
        return cls(bus=ctx.bus, config=cfg)

    @property
    def config(self) -> WhatsAppConfig:
        return self._cfg

    # ---------------------------------------------------------------- life

    async def start(self) -> None:
        if self._started:
            return
        if not self._cfg.enabled:
            self._started = True
            log.info("WhatsAppChannel disabled (enabled=false) — skipping")
            return
        if self._transport is None:
            self._transport = BridgeTransport(self._cfg.bridge_url)
        await self._transport.start(self._on_bridge_message)
        self._started = True
        self._active = True
        owner = "set" if self._cfg.owner_jid else "unclaimed"
        log.info("WhatsAppChannel started (owner %s)", owner)

    async def stop(self) -> None:
        if not self._started:
            return
        if self._transport is not None and self._active:
            try:
                await self._transport.stop()
            except Exception as exc:  # noqa: BLE001
                log.warning("WhatsApp stop raised: %s", type(exc).__name__)
        self._started = False
        self._active = False
        log.info("WhatsAppChannel stopped")

    def status(self) -> dict[str, Any]:
        """What Settings shows (never a jid in full)."""
        transport = self._transport.status() if self._transport is not None else {}
        return {
            "enabled": self._cfg.enabled,
            "running": self._active,
            "owner_claimed": bool(self._cfg.owner_jid),
            "linked": bool(transport.get("linked")),
            "bridge_url": self._cfg.bridge_url,
            "dropped": self._dropped,
        }

    # --------------------------------------------------------------- inbound

    def _is_owner(self, jid: str) -> bool:
        return bool(jid) and jid == self._cfg.owner_jid

    def _claim_owner(self, jid: str) -> bool:
        """The first private sender within the window becomes the owner (persisted)."""
        if not self._cfg.pair_on_first_private_message or self._cfg.owner_jid or not jid:
            return False
        if time.monotonic() > self._pairing_closes_at:
            return False
        self._cfg.owner_jid = jid
        try:
            save_whatsapp_config(self._cfg, self._config_path)
        except OSError:
            log.warning("whatsapp: the owner could not be persisted; it holds until restart")
        log.info("whatsapp: owner claimed on first contact")
        return True

    async def _on_bridge_message(self, item: dict[str, Any]) -> None:
        jid = str(item.get("from") or "").strip()
        text = str(item.get("text") or "").strip()
        private = item.get("private") is True
        if not jid or not text or not private:
            self._dropped += 1
            return
        if not self._is_owner(jid) and not self._claim_owner(jid):
            self._dropped += 1
            log.debug("whatsapp: message dropped (not the owner)")
            return
        session = self._sessions.get(jid)
        if session is None:
            session = ChannelSession(
                session_id=uuid4(), channel_name=self.name, user_handle="owner"
            )
            self._sessions[jid] = session
        await self._inbox.put(
            ChannelMessage(
                session_id=session.session_id,
                kind="text",
                content=text,
                metadata={
                    "whatsapp_jid": jid,
                    "whatsapp_private": True,
                    "whatsapp_message_id": str(item.get("id") or ""),
                    "friend_id": None,
                },
            )
        )

    async def messages(self) -> AsyncIterator[ChannelMessage]:
        while True:
            yield await self._inbox.get()

    # -------------------------------------------------------------- outbound

    async def send_message(self, msg: ChannelMessage) -> None:
        jid = str(msg.metadata.get("whatsapp_jid") or "").strip()
        if not jid or not self._is_owner(jid) or self._transport is None or not self._active:
            return
        text = (msg.content or "").strip()
        if not text:
            return
        await self._transport.send_text(jid, text[:4000])

    async def broadcast_event(self, event: Event) -> None:
        """Nothing is pushed uncalled: the owner's chat only ever gets replies."""
        return None

    async def sessions(self) -> list[ChannelSession]:
        return list(self._sessions.values())


def whatsapp_status(config: WhatsAppConfig, app_state: Any = None) -> dict[str, Any]:
    """Settings payload: the saved switch plus the live channel's state when it runs."""
    status: dict[str, Any] = {
        "enabled": config.enabled,
        "running": False,
        "owner_claimed": bool(config.owner_jid),
        "linked": False,
        "bridge_url": config.bridge_url,
        "start_error": "",
        "missing": "bridge",
    }
    manager = getattr(app_state, "channel_manager", None) if app_state is not None else None
    if manager is None:
        return status
    try:
        status["start_error"] = str(manager.start_errors().get("whatsapp") or "")
        if "whatsapp" in manager.started():
            channel = manager.get("whatsapp")
            live = getattr(channel, "status", None)
            if callable(live):
                status.update(live())
    except Exception:  # noqa: BLE001 — the saved switch is still a true answer
        log.debug("whatsapp: live status unavailable", exc_info=True)
    return status


def dump_config(config: WhatsAppConfig) -> str:
    return json.dumps(config.model_dump(), indent=2)


__all__ = [
    "DEFAULT_BRIDGE_URL",
    "BridgeTransport",
    "WhatsAppChannel",
    "WhatsAppConfig",
    "WhatsAppTransport",
    "load_whatsapp_config",
    "save_whatsapp_config",
    "whatsapp_status",
]
