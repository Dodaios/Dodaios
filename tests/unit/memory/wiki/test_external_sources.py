"""Read-only external sources: searched next to the vault, never written.

The ``external`` fixture snapshots the source folder (size + sha256 + mtime
per file) and compares it on teardown — a source that changed by a single
byte, or gained a file, fails the test.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import jarvis.memory.wiki.search as search_mod
from jarvis.memory.wiki import external_sources as ext
from jarvis.memory.wiki import fts_index
from jarvis.memory.wiki.atomic_writer import AtomicWriter
from jarvis.memory.wiki.backup import BackupManager
from jarvis.memory.wiki.external_sources import (
    WRITE_DENIED_EXTERNAL_SOURCE,
    ExternalSource,
    ExternalSourceWriteDenied,
)
from jarvis.memory.wiki.protocols import PageUpdate
from jarvis.memory.wiki.search import SearchHit, VaultSearch

from .conftest import FakePageRepository, write_page


def _snapshot(root: Path) -> dict[str, tuple[int, str, int]]:
    state: dict[str, tuple[int, str, int]] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file():
            stat = path.stat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            state[rel] = (stat.st_size, digest, stat.st_mtime_ns)
        else:
            state[rel + "/"] = (0, "", 0)
    return state


@pytest.fixture(autouse=True)
def _index_under_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _db(source: ExternalSource) -> Path:
        return tmp_path / "data" / "external_sources" / f"{source.name}.db"

    monkeypatch.setattr(search_mod, "index_db_path", _db)


@pytest.fixture
def external(tmp_path: Path):
    root = tmp_path / "ak-vault"
    (root / "entities").mkdir(parents=True)
    page = root / "entities" / "zebrafink.md"
    page.write_text("# Zebrafink\n\nDer Zebrafink singt im Altvault.\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(page, (old, old))
    source = ExternalSource(name="ak-memory-vault", path=root.resolve())
    ext.register([source])
    before = _snapshot(root)
    yield source
    ext.register([])
    assert _snapshot(root) == before, "external source was modified"


def _search(vault: Path, tmp_path: Path, sources=()) -> VaultSearch:
    db = tmp_path / "data" / "jarvis.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    fts_index.rebuild_index(vault, conn)
    return VaultSearch(vault, conn=conn, external_sources=sources)


def _entity(slug: str, body: str) -> str:
    return f"---\ntype: entity\nslug: {slug}\n---\n\n{body}\n"


# --------------------------------------------------------------------- guard


def test_guard_denies_paths_inside_a_source(external: ExternalSource) -> None:
    with pytest.raises(ExternalSourceWriteDenied) as info:
        ext.guard_write(external.path / "entities" / "new.md")
    assert info.value.code == WRITE_DENIED_EXTERNAL_SOURCE
    assert str(info.value).startswith(WRITE_DENIED_EXTERNAL_SOURCE)
    with pytest.raises(ExternalSourceWriteDenied):
        ext.guard_write(external.path)


def test_guard_allows_paths_outside(external: ExternalSource, tmp_path: Path) -> None:
    ext.guard_write(tmp_path / "vault" / "x.md")
    ext.guard_write(tmp_path / "ak-vault-sibling" / "x.md")


def test_writer_refuses_a_page_in_the_source(
    external: ExternalSource, vault_root: Path, tmp_path: Path, fake_repo: FakePageRepository
) -> None:
    writer = AtomicWriter(vault_root=vault_root, backup_dir=tmp_path / "backups")
    update = PageUpdate(
        target_path=external.path / "entities" / "zebrafink.md",
        operation="update",
        new_body=_entity("zebrafink", "overwritten"),
    )
    with pytest.raises(ExternalSourceWriteDenied):
        asyncio.run(writer.apply([update], repo=fake_repo))
    assert not (tmp_path / "backups").exists(), "a denied batch must not leave a backup"


def test_writer_refuses_renaming_out_of_the_source(
    external: ExternalSource, vault_root: Path, tmp_path: Path, fake_repo: FakePageRepository
) -> None:
    writer = AtomicWriter(vault_root=vault_root, backup_dir=tmp_path / "backups")
    update = PageUpdate(
        target_path=vault_root / "entities" / "zebrafink.md",
        operation="rename",
        new_body=_entity("zebrafink", "moved"),
        rename_from=external.path / "entities" / "zebrafink.md",
    )
    with pytest.raises(ExternalSourceWriteDenied):
        asyncio.run(writer.apply([update], repo=fake_repo))
    assert not (vault_root / "entities" / "zebrafink.md").exists()


def test_writer_refuses_archiving_in_the_source(
    external: ExternalSource, vault_root: Path, tmp_path: Path, fake_repo: FakePageRepository
) -> None:
    writer = AtomicWriter(vault_root=vault_root, backup_dir=tmp_path / "backups")
    update = PageUpdate(
        target_path=external.path / "entities" / "zebrafink.md",
        operation="archive",
        new_body="",
    )
    with pytest.raises(ExternalSourceWriteDenied):
        asyncio.run(writer.apply([update], repo=fake_repo))


def test_writer_refuses_a_source_as_vault_root(
    external: ExternalSource, tmp_path: Path, fake_repo: FakePageRepository
) -> None:
    writer = AtomicWriter(vault_root=external.path, backup_dir=tmp_path / "backups")
    update = PageUpdate(
        target_path=external.path / "entities" / "neu.md",
        operation="create",
        new_body=_entity("neu", "neu"),
    )
    with pytest.raises(ExternalSourceWriteDenied):
        asyncio.run(writer.apply([update], repo=fake_repo))


def test_backup_refuses_a_source(
    external: ExternalSource, vault_root: Path, tmp_path: Path
) -> None:
    with pytest.raises(ExternalSourceWriteDenied):
        BackupManager(external.path, tmp_path / "backups").snapshot()
    with pytest.raises(ExternalSourceWriteDenied):
        BackupManager(vault_root, external.path / "wiki-backups").snapshot()


def test_writer_still_writes_the_active_vault(
    external: ExternalSource, vault_root: Path, tmp_path: Path, fake_repo: FakePageRepository
) -> None:
    writer = AtomicWriter(vault_root=vault_root, backup_dir=tmp_path / "backups")
    target = vault_root / "entities" / "ruben.md"
    update = PageUpdate(target_path=target, operation="create", new_body=_entity("ruben", "hallo"))
    result = asyncio.run(writer.apply([update], repo=fake_repo))
    assert target in result.applied


def test_society_vault_refuses_a_source(external: ExternalSource) -> None:
    from jarvis.society.memory import resolve_society_vault

    cfg = SimpleNamespace(
        wiki_integration=SimpleNamespace(
            vault_root=external.path,
            external_sources=[{"name": external.name, "path": str(external.path)}],
        )
    )
    with pytest.raises(ExternalSourceWriteDenied):
        resolve_society_vault(cfg)


# -------------------------------------------------------------------- search


def test_hits_carry_their_source(
    external: ExternalSource, vault_root: Path, tmp_path: Path
) -> None:
    write_page(vault_root, "entity", "zebrafink-notiz", body="Zebrafink im aktiven Vault.")
    hits = _search(vault_root, tmp_path, sources=(external,)).search("Zebrafink", k=5)
    by_source = {(h.source, h.source_type): h for h in hits}
    assert ("dodaios", "canonical") in by_source
    ak = by_source[("ak-memory-vault", "external")]
    assert ak.path == external.path / "entities" / "zebrafink.md"
    assert "Altvault" in ak.snippet
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_external_index_lives_outside_the_source(
    external: ExternalSource, vault_root: Path, tmp_path: Path
) -> None:
    _search(vault_root, tmp_path, sources=(external,)).search("Zebrafink")
    assert (tmp_path / "data" / "external_sources" / "ak-memory-vault.db").is_file()


def test_default_search_is_canonical_only(
    external: ExternalSource, vault_root: Path, tmp_path: Path
) -> None:
    write_page(vault_root, "entity", "zebrafink-notiz", body="Zebrafink im aktiven Vault.")
    hits = _search(vault_root, tmp_path).search("Zebrafink")
    assert hits and all(h.source == "dodaios" and h.source_type == "canonical" for h in hits)
    assert not (tmp_path / "data" / "external_sources").exists()


def test_missing_source_only_drops_its_hits(vault_root: Path, tmp_path: Path) -> None:
    write_page(vault_root, "entity", "zebrafink-notiz", body="Zebrafink im aktiven Vault.")
    gone = ExternalSource(name="gone", path=tmp_path / "nope")
    hits = _search(vault_root, tmp_path, sources=(gone,)).search("Zebrafink")
    assert [h.source for h in hits] == ["dodaios"]
    assert not gone.path.exists()


def test_search_hit_defaults_keep_the_old_contract() -> None:
    hit = SearchHit(title="t", path=Path("p"), snippet="", score=0.5)
    assert (hit.source, hit.source_type) == ("dodaios", "canonical")


# -------------------------------------------------------------------- config


def test_parse_sources_accepts_strings_and_tables(tmp_path: Path) -> None:
    sources = ext.parse_sources(
        [
            str(tmp_path / "AI Memory"),
            {"name": "AK Memory Vault", "path": str(tmp_path / "x")},
            "",
            {"path": ""},
        ]
    )
    assert [s.name for s in sources] == ["ai-memory", "ak-memory-vault"]
    assert all(s.path.is_absolute() for s in sources)


def test_config_field_defaults_to_empty() -> None:
    from jarvis.core.config import WikiIntegrationConfig

    assert WikiIntegrationConfig().external_sources == []
    cfg = WikiIntegrationConfig(external_sources=[{"name": "ak", "path": "D:/x"}])
    assert ext.parse_sources(cfg.external_sources)[0].name == "ak"


def test_register_from_config_without_section_keeps_registration(
    external: ExternalSource,
) -> None:
    ext.register_from_config(SimpleNamespace())
    assert ext.registered() == (external,)
