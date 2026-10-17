"""The society vault follows ``[wiki_integration].vault_root``, not boot order."""

from __future__ import annotations

from types import SimpleNamespace

from jarvis.memory.wiki.vault_root import resolve_vault_root
from jarvis.society.memory import resolve_society_vault


def test_configured_wiki_integration_root_wins_over_last_resolution(tmp_path):
    configured = tmp_path / "configured"
    elsewhere = tmp_path / "elsewhere"
    configured.mkdir()
    elsewhere.mkdir()
    cfg = SimpleNamespace(wiki_integration=SimpleNamespace(vault_root=configured))

    resolve_vault_root(elsewhere)  # some other consumer resolved a root first

    assert resolve_society_vault(cfg) == resolve_vault_root(configured).path


def test_result_does_not_depend_on_what_was_resolved_before(tmp_path):
    configured = tmp_path / "configured"
    other = tmp_path / "other"
    configured.mkdir()
    other.mkdir()
    cfg = SimpleNamespace(wiki_integration=SimpleNamespace(vault_root=configured))

    first = resolve_society_vault(cfg)
    resolve_vault_root(other)
    second = resolve_society_vault(cfg)

    assert first == second
