"""The process-wide memory vault and the helpers prompt builders and tools call.

``prompt_block()`` is what every engine (chat, realtime voice, GPT-Live)
puts into its instructions; ``remember_explicitly()`` is what a "remember
that ..." request writes. Both are cheap: the block is cached and only
rebuilt after a write.
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path
from typing import Any

from dodaios.memory.vault.models import WriteResult
from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

VAULT_FILENAME = "vault.db"

_HEADER = (
    "## What you know about the user (long-term memory)\n"
    "Use it when it helps; never recite it. Search it with memory-search for "
    "anything not listed here."
)

_active: MemoryVault | None = None
_lock = threading.Lock()
_cache: dict[bool, tuple[int, str]] = {}
_generation = 0
_budgets = {"full": 2400, "compact": 1200}


def vault_path(config: Any) -> Path:
    """``memory.vault.path`` if set, else ``<memory.data_dir>/memory/vault.db``."""
    memory = getattr(config, "memory", None)
    vault_cfg = getattr(memory, "vault", None)
    explicit = str(getattr(vault_cfg, "path", "") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    from dodaios.core.config import DATA_DIR

    data_dir = str(getattr(memory, "data_dir", "") or "").strip()
    base = Path(data_dir) if data_dir and data_dir not in ("./data", "data") else DATA_DIR
    return base / "memory" / VAULT_FILENAME


def open_from_config(config: Any) -> MemoryVault | None:
    """Open the vault and make it the active one; ``None`` when switched off."""
    vault_cfg = getattr(getattr(config, "memory", None), "vault", None)
    if vault_cfg is not None and not getattr(vault_cfg, "enabled", True):
        set_active(None)
        return None
    if _active is not None:
        return _active
    if vault_cfg is not None:
        _budgets["full"] = int(getattr(vault_cfg, "profile_max_chars", 2400))
        _budgets["compact"] = max(400, _budgets["full"] // 2)
    vault = MemoryVault(vault_path(config))
    set_active(vault)
    return vault


def set_active(vault: MemoryVault | None) -> None:
    global _active
    with _lock:
        old, _active = _active, vault
        changed()
    if old is not None and old is not vault:
        try:
            old.close()
        except Exception:  # noqa: BLE001 — closing an old handle never fails a swap
            log.debug("memory vault: could not close the old handle", exc_info=True)


def active() -> MemoryVault | None:
    return _active


def changed() -> None:
    """Drop the cached prompt block; called after every write."""
    global _generation
    _generation += 1
    _cache.clear()


def budget_chars(*, compact: bool = False) -> int:
    """Characters the always-on block may use (voice gets the compact budget)."""
    return _budgets["compact" if compact else "full"]


def prompt_block(*, compact: bool = False) -> str:
    """The always-on memory block, ``""`` while no vault runs or it is empty."""
    vault = _active
    if vault is None:
        return ""
    cached = _cache.get(compact)
    if cached is not None and cached[0] == _generation:
        return cached[1]
    try:
        body = vault.profile_block(max_chars=_budgets["compact" if compact else "full"])
    except Exception:  # noqa: BLE001 — a vault fault never breaks a prompt build
        log.warning("memory vault: could not build the prompt block", exc_info=True)
        return ""
    block = f"{_HEADER}\n{body}" if body else ""
    _cache[compact] = (_generation, block)
    return block


# Words that hint at a kind, in the shipped input languages.
_WORDS = {
    "procedural": (
        "always never don't stop immer nie niemals siempre nunca"  # i18n-allow
    ),
    "preference": (
        "like love hate prefer favorite favourite "
        "mag liebe hasse lieber bevorzuge prefiero gusta"  # i18n-allow
    ),
    "relationship": (
        "wife husband partner girlfriend boyfriend mother father mom dad sister brother "
        "son daughter friend colleague boss "
        "frau mann freundin freund mutter vater schwester bruder sohn tochter "  # i18n-allow
        "kollege kollegin chef chefin"  # i18n-allow
    ),
    "project": (
        "project deadline goal plan launch projekt ziel abgabe frist"  # i18n-allow
    ),
}

_KIND_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(r"\b(" + "|".join(map(re.escape, words.split())) + r")\b", re.I))
    for kind, words in _WORDS.items()
)


def guess_kind(text: str) -> str:
    """A kind for an explicit request, without a model call."""
    for kind, pattern in _KIND_HINTS:
        if pattern.search(text):
            return kind
    return "profile"


def remember_explicitly(
    content: str, *, evidence: str = "", source: str = "remember tool", kind: str | None = None
) -> WriteResult:
    """Save an explicit "remember that ..." in the user's own words.

    Raises ``LookupError`` while no vault runs.
    """
    vault = _active
    if vault is None:
        raise LookupError("the memory vault is not running")
    result = vault.remember(
        content,
        kind or guess_kind(content),
        origin="user",
        source={"via": source, "evidence": evidence[:500]},
    )
    if result.action == "added":
        changed()
    return result
