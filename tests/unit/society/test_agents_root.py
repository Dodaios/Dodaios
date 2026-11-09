"""Agent notebooks live in ``<data dir>/agents`` (ADR-0044), adopted once from the old vault."""

from __future__ import annotations

from types import SimpleNamespace

from dodaios.society import memory as society_memory


def _cfg(tmp_path, vault):
    return SimpleNamespace(
        memory=SimpleNamespace(data_dir=str(tmp_path / "data")),
        wiki_integration=SimpleNamespace(vault_root=str(vault)),
    )


def test_notebooks_move_out_of_the_wiki_vault_by_copy(tmp_path):
    vault = tmp_path / "old-vault"
    notebook = vault / "society" / "scout" / "MEMORY.md"
    notebook.parent.mkdir(parents=True)
    notebook.write_text("# Scout\n", encoding="utf-8")
    society_memory._ADOPTED.clear()

    root = society_memory.resolve_society_vault(_cfg(tmp_path, vault))

    assert root == tmp_path / "data" / "agents"
    assert (root / "society" / "scout" / "MEMORY.md").read_text(encoding="utf-8") == "# Scout\n"
    assert notebook.exists(), "the old copy stays until the vault is archived"


def test_existing_agents_folder_is_never_overwritten(tmp_path):
    vault = tmp_path / "old-vault"
    (vault / "society" / "scout").mkdir(parents=True)
    (vault / "society" / "scout" / "MEMORY.md").write_text("old\n", encoding="utf-8")
    current = tmp_path / "data" / "agents" / "society" / "scout" / "MEMORY.md"
    current.parent.mkdir(parents=True)
    current.write_text("new\n", encoding="utf-8")
    society_memory._ADOPTED.clear()

    society_memory.resolve_society_vault(_cfg(tmp_path, vault))

    assert current.read_text(encoding="utf-8") == "new\n"


def test_an_explicit_root_stays_authoritative(tmp_path):
    cfg = SimpleNamespace(wiki=SimpleNamespace(vault_root=str(tmp_path / "custom")))
    assert society_memory.resolve_society_vault(cfg) == (tmp_path / "custom").resolve()
