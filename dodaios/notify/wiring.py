"""Wiring the notify package into the running app.

``install()`` runs once at boot (``server.py``): it builds the one
:class:`Notifier`, subscribes the attention bridge and starts the reminder
scheduler. ``attach_chat_service()`` runs when the chat service is built (on
first chat use) and adds the Telegram approval buttons, which need the
service's event listener. Everything here degrades to a no-op in a bare
runtime: no window, no bus, no Telegram.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from dodaios.notify import attention_bridge
from dodaios.notify.notifier import Notifier, set_current
from dodaios.notify.reminders import ReminderScheduler

log = logging.getLogger(__name__)

_scheduler: ReminderScheduler | None = None
_telegram_bridge: Any | None = None
_urgent_caller: Any | None = None


def _vault_getter(cfg: Any) -> Callable[[], Any | None]:
    def _vault() -> Any | None:
        from dodaios.memory.vault import runtime as vault_runtime

        vault = vault_runtime.active()
        if vault is not None:
            return vault
        try:
            # The learning loop opens the vault lazily; a reminder must not
            # wait for the first chat turn to be delivered after a restart.
            return vault_runtime.open_from_config(cfg)
        except Exception:  # noqa: BLE001 — a vault that will not open is retried next tick
            log.debug("notify: vault not available yet", exc_info=True)
            return None

    return _vault


def _focus_fn(app_state: Any, cfg: Any) -> Callable[[], Any]:
    def _focus() -> Any:
        desktop = getattr(app_state, "desktop_app", None)
        raise_now = getattr(desktop, "_focus_window_now", None)
        if callable(raise_now):
            return raise_now()
        # No desktop shell in this process (browser-only use): the server's
        # own focus route answers, honestly, that there is no window.
        import httpx

        port = int(getattr(getattr(cfg, "ui", None), "admin_api_port", 47821) or 47821)
        return httpx.post(f"http://127.0.0.1:{port}/api/window/focus", timeout=1.0).json()

    return _focus


def _app_focused_fn(get_service: Callable[[], Any | None]) -> Callable[[], bool]:
    def _focused() -> bool:
        from dodaios.agent_chat.attention import FOCUS_TTL_S, attention_of

        svc = get_service()
        attention = attention_of(svc) if svc is not None else None
        if attention is None:
            return False
        focus = attention.gate.focus
        fresh = focus.at > 0 and time.monotonic() - focus.at <= FOCUS_TTL_S
        return bool(fresh and focus.app_focused)

    return _focused


def install(
    *,
    app_state: Any,
    bus: Any,
    cfg: Any,
    get_service: Callable[[], Any | None],
    start_scheduler: bool = True,
) -> Notifier:
    """Build the notifier, subscribe the attention bridge, start the scheduler."""
    global _scheduler
    notifier = Notifier(
        bus=lambda: bus,
        focus=_focus_fn(app_state, cfg),
        app_focused=_app_focused_fn(get_service),
    )
    set_current(notifier)
    attention_bridge.install(bus, notifier)
    if start_scheduler:
        _scheduler = ReminderScheduler(vault=_vault_getter(cfg), notifier=lambda: notifier)
        _scheduler.start()
        log.info("notify: reminder scheduler started")
    return notifier


def attach_chat_service(service: Any, *, app_state: Any, cfg: Any) -> None:
    """Add the Telegram approval buttons once the chat service exists (idempotent)."""
    global _telegram_bridge
    if _telegram_bridge is not None:
        return
    from dodaios.channels.telegram_approvals import TelegramApprovalBridge

    def _channel() -> Any | None:
        manager = getattr(app_state, "channel_manager", None)
        if manager is None:
            return None
        try:
            return manager.get("telegram") if "telegram" in manager.started() else None
        except Exception:  # noqa: BLE001 — a channel that is not up is "no Telegram"
            return None

    _telegram_bridge = TelegramApprovalBridge(service, channel=_channel, config=lambda: cfg)
    _telegram_bridge.install()
    _attach_urgent_calls(service, cfg)


def _phone_allowed(cfg: Any) -> bool:
    """Whether the owner's voice seat may speak in an unattended call.

    With a subscription connected, background work must not bill a per-token
    key (``background_policy``); a phone call nobody started is background
    work, so it only goes ahead when its speech providers are ones that policy
    allows. Otherwise the text escalation stands alone.
    """
    from dodaios.brain.background_policy import background_providers

    names = [
        str(getattr(getattr(cfg, section, None), "provider", "") or "").strip().lower()
        for section in ("stt", "tts")
    ]
    names = [name for name in names if name]
    allowed = background_providers(names)
    return not allowed.subscription_mode or all(allowed.permits(name) for name in names)


def _attach_urgent_calls(service: Any, cfg: Any) -> None:
    """Subscribe the opt-in "call me for urgent decisions" caller (a no-op while it is off)."""
    global _urgent_caller
    from dodaios.notify.notifier import current_notifier
    from dodaios.notify.settings import settings_path
    from dodaios.notify.urgent_call import CallLedger, UrgentCaller
    from dodaios.notify.urgent_ring import desktop_ringer, is_open_fn, phone_ringer

    notifier = current_notifier()
    _urgent_caller = UrgentCaller(
        ring_desktop=desktop_ringer(service, notifier),
        ring_phone=phone_ringer(service),
        is_open=is_open_fn(service),
        phone_allowed=lambda: _phone_allowed(cfg),
        ledger=CallLedger(settings_path().with_name("urgent_calls.json")),
    )
    service.add_event_listener(_urgent_caller.on_chat_event)


async def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        await _scheduler.stop()
        _scheduler = None


__all__ = ["attach_chat_service", "install", "shutdown"]
