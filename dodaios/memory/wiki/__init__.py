"""Knowledge-Wiki package (Karpathy-style structured markdown vault).

The runtime vault lives under ``wiki/obsidian-vault/`` (gitignored — it is
personal data). The canonical schema, README, and seed index live as
templates inside this package and are version-controlled. On first
bootstrap, ``WikiCurator`` (Phase B1) copies missing templates into the
runtime vault.

See ``docs/adr/0013-knowledge-wiki-architecture.md`` for the why.

Phase B5 additions (Agent D):
- ``VaultLock`` — portable file-based exclusive lock.
- ``CuratorScheduler`` — cooldown + lock gate around ``WikiCurator``.
- ``SchedulerConfig`` — re-exported from ``dodaios.core.config``.
- ``SchedulerResult``, ``TriggerSource`` — result + trigger-source types.
"""
from __future__ import annotations

from pathlib import Path

# Phase B5 — Agent D: scheduler + lock
from dodaios.core.config import SchedulerConfig

# Phase B5 — Agent A: integration / bootstrap
from dodaios.memory.wiki.integration import WikiIntegrationHandle, bootstrap_wiki_integration
from dodaios.memory.wiki.lock import VaultLock
from dodaios.memory.wiki.scheduler import (
    CuratorScheduler,
    SchedulerResult,
    TriggerSource,
)

TEMPLATES_DIR: Path = Path(__file__).parent / "templates"

__all__ = [
    "TEMPLATES_DIR",
    # B5 Agent A exports
    "WikiIntegrationHandle",
    "bootstrap_wiki_integration",
    # B5 Agent D exports
    "VaultLock",
    "CuratorScheduler",
    "SchedulerConfig",
    "SchedulerResult",
    "TriggerSource",
]
