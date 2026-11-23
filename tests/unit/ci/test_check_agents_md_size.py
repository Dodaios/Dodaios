"""AGENTS.md files have a size cap: 150 lines / 12,000 chars root, 60 lines per folder."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import check_agents_md_size as gate


def _write(root: Path, rel: str, lines: int, width: int = 10) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(("x" * width + "\n") * lines, encoding="utf-8")


def test_small_files_pass(tmp_path):
    _write(tmp_path, "AGENTS.md", 150)
    _write(tmp_path, "dodaios/AGENTS.md", 60)
    assert gate.problems(tmp_path, ["AGENTS.md", "dodaios/AGENTS.md"]) == []


def test_root_too_many_lines(tmp_path):
    _write(tmp_path, "AGENTS.md", 151)
    assert len(gate.problems(tmp_path, ["AGENTS.md"])) == 1


def test_root_too_many_characters(tmp_path):
    _write(tmp_path, "AGENTS.md", 100, width=130)
    assert "characters" in gate.problems(tmp_path, ["AGENTS.md"])[0]


def test_folder_file_capped_at_sixty(tmp_path):
    _write(tmp_path, "AGENTS.md", 10)
    _write(tmp_path, "docs/AGENTS.md", 61)
    assert gate.problems(tmp_path, ["AGENTS.md", "docs/AGENTS.md"]) == [
        "docs/AGENTS.md: 61 lines, limit 60"
    ]


def test_side_project_is_exempt(tmp_path):
    _write(tmp_path, "skillbook/AGENTS.md", 500)
    assert gate.problems(tmp_path, ["skillbook/AGENTS.md"]) == []
