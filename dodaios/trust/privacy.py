"""What the assistant knows and where it goes: one overview for the Privacy page.

Reads what is already configured and connected; decides nothing. Every block
is best effort: a part that cannot be read (no vault, no catalog) is reported
as absent, never as an error, so the page always paints.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

#: Roles whose provider the overview names, with the config path that holds it.
ROLES: tuple[tuple[str, str], ...] = (
    ("brain", "brain.primary"),
    ("realtime", "brain.realtime.provider"),
    ("tts", "tts.provider"),
    ("stt", "stt.provider"),
    ("learning", "memory.learning.provider"),
)


def _get(obj: Any, dotted: str) -> Any:
    node = obj
    for part in dotted.split("."):
        if node is None:
            return None
        node = getattr(node, part, None)
    return node


def is_local_provider(provider_id: str) -> bool:
    """Whether a provider runs on this machine (spec-derived, plus the obvious names)."""
    pid = (provider_id or "").strip().lower()
    if not pid:
        return False
    try:
        from dodaios.brain.app_control import LOCAL_PROVIDERS

        if pid in LOCAL_PROVIDERS:
            return True
    except Exception:  # noqa: BLE001 — without the catalog the name decides
        log.debug("privacy overview: provider catalog unavailable", exc_info=True)
    return any(
        marker in pid
        for marker in ("local", "ollama", "whisper", "piper", "kokoro", "vosk", "sherpa", "coqui")
    )


def _provider_label(provider_id: str) -> str:
    try:
        from dodaios.brain.app_control import get_spec

        spec = get_spec(provider_id)
        label = getattr(spec, "label", None)
        if isinstance(label, str) and label.strip():
            return label
    except Exception:  # noqa: BLE001 — the id is a fine label
        log.debug("privacy overview: no spec for %s", provider_id, exc_info=True)
    return provider_id


def providers_in_use(cfg: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for role, path in ROLES:
        provider = _get(cfg, path)
        if not isinstance(provider, str) or not provider.strip():
            continue
        provider = provider.strip()
        out.append(
            {
                "role": role,
                "provider": provider,
                "label": _provider_label(provider),
                "local": is_local_provider(provider),
            }
        )
    return out


def connected_accounts() -> list[dict[str, Any]]:
    """Connected connectors (mail, calendar, chat apps) from the marketplace token store."""
    try:
        from dodaios.marketplace.catalog_data import load_catalog
        from dodaios.marketplace.token_store import TokenStore
        from dodaios.ui.web.marketplace_routes import _plugin_status_meta
    except Exception:  # noqa: BLE001 — no marketplace, no accounts to list
        log.debug("privacy overview: marketplace unavailable", exc_info=True)
        return []
    out: list[dict[str, Any]] = []
    try:
        catalog = load_catalog()
        store = TokenStore()
        for spec in catalog.plugins:
            meta = _plugin_status_meta(spec.id, store)
            if meta.status not in ("connected", "needs_reauth"):
                continue
            out.append(
                {
                    "id": spec.id,
                    "label": getattr(spec, "name", None) or spec.id,
                    "category": str(getattr(spec, "category", "") or ""),
                    "status": meta.status,
                }
            )
    except Exception:  # noqa: BLE001 — a half-read catalog still lists what it read
        log.warning("privacy overview: could not list connected accounts", exc_info=True)
    return out


def memory_state() -> dict[str, Any]:
    try:
        from dodaios.memory.vault.runtime import active

        vault = active()
    except Exception:  # noqa: BLE001 — no vault module, no memory to report
        log.debug("privacy overview: vault unavailable", exc_info=True)
        vault = None
    if vault is None:
        return {"available": False, "count": 0, "learning_paused": False, "paused_until": None}
    count = 0
    try:
        stats = vault.stats()
        raw = stats.get("current") if isinstance(stats, dict) else None
        if raw is None and isinstance(stats, dict):
            raw = stats.get("total") or stats.get("count")
        count = int(raw or 0)
    except Exception:  # noqa: BLE001 — a count is a nicety
        log.debug("privacy overview: vault stats unavailable", exc_info=True)
    until = None
    try:
        until = vault.learning_paused_until()
    except Exception:  # noqa: BLE001 — pause state is a nicety
        log.debug("privacy overview: pause state unavailable", exc_info=True)
    return {
        "available": True,
        "count": count,
        "learning_paused": until is not None,
        "paused_until": until,
    }


def overview(cfg: Any | None = None) -> dict[str, Any]:
    if cfg is None:
        try:
            from dodaios.core.config import load_config

            cfg = load_config()
        except Exception:  # noqa: BLE001 — the page still paints with what it can read
            log.warning("privacy overview: config unavailable", exc_info=True)
            cfg = None
    providers = providers_in_use(cfg) if cfg is not None else []
    channels = []
    for name in ("telegram", "discord"):
        if bool(_get(cfg, f"integrations.{name}.enabled")):
            channels.append(name)
    return {
        "accounts": connected_accounts(),
        "memory": memory_state(),
        "providers": providers,
        "cloud": [p for p in providers if not p["local"]],
        "channels": channels,
        "screen_context": bool(_get(cfg, "screen_context.enabled")),
        "known_recipients": _known_recipient_count(),
    }


def _known_recipient_count() -> int:
    try:
        from .recipients import known_recipients

        return len(known_recipients().items())
    except Exception:  # noqa: BLE001 — a count is a nicety
        return 0


__all__ = ["ROLES", "connected_accounts", "is_local_provider", "memory_state", "overview"]
