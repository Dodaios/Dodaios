"""Tests for ``scripts/cleanup_pick.py`` on a fixture repo."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "cleanup_pick.py"
_spec = importlib.util.spec_from_file_location("cleanup_pick", SCRIPT)
cp = importlib.util.module_from_spec(_spec)
sys.modules["cleanup_pick"] = cp
_spec.loader.exec_module(cp)


def _fn(name: str, n: int, value: int = 1) -> str:
    return f"def {name}():\n" + f"    x = {value}\n" * (n - 1) + "\n"


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "dodaios").mkdir()
    (tmp_path / "scripts" / "ci").mkdir(parents=True)
    (tmp_path / "dodaios" / "big.py").write_text(_fn("just_over", 230))
    (tmp_path / "dodaios" / "far.py").write_text(_fn("way_over", 900))
    # two functions with identical bodies in one file
    (tmp_path / "dodaios" / "dup.py").write_text(_fn("a", 8) + _fn("b", 8))
    (tmp_path / "dodaios" / "quiet.py").write_text("try:\n    pass\nexcept Exception:\n    pass\n")
    (tmp_path / "scripts" / "ci" / "silent-handlers-baseline.json").write_text(
        json.dumps({"total": 1, "files": {"dodaios/quiet.py": 1, "dodaios/gone.py": 2}})
    )
    return tmp_path


def _files(root):
    return sorted(p.relative_to(root).as_posix() for p in (root / "dodaios").glob("*.py"))


def _patch(monkeypatch):
    monkeypatch.setattr(cp, "tracked_python", lambda r: _files(r))
    monkeypatch.setattr(cp, "dead_code_candidates", lambda *a: [])


def test_long_function_window_excludes_giants(tmp_path):
    root = _repo(tmp_path)
    longs, _ = cp.scan_functions(root, _files(root), set())
    assert [c["symbol"] for c in longs] == ["just_over"]


def test_duplicates_found_in_one_file(tmp_path):
    root = _repo(tmp_path)
    _, dupes = cp.scan_functions(root, _files(root), set())
    assert {c["file"] for c in dupes} >= {"dodaios/dup.py"}


def test_silent_handlers_skip_missing_files(tmp_path):
    root = _repo(tmp_path)
    base = cp.load_json(root / "scripts/ci/silent-handlers-baseline.json")
    found = cp.silent_handler_candidates(root, base, set())
    assert [c["file"] for c in found] == ["dodaios/quiet.py"]


def test_skip_set_removes_files(tmp_path):
    root = _repo(tmp_path)
    longs, _ = cp.scan_functions(root, _files(root), {"dodaios/big.py"})
    assert longs == []


def test_rotation_moves_with_the_day(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    _patch(monkeypatch)
    seen = {cp.pick(root, None, dt.date(2026, 1, d), set())["category"] for d in range(1, 9)}
    assert seen == {"duplicate_cluster", "long_function", "silent_handlers"}


def test_nothing_to_do_gives_none(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    _patch(monkeypatch)
    assert cp.pick(root, None, dt.date(2026, 1, 1), set(_files(root))) is None


def test_brief_names_file_rules_and_update_command():
    p = {"category": "silent_handlers", "file": "dodaios/quiet.py", "symbol": "1", "line": 1,
         "size": 4, "score": 4}
    text = cp.brief(p)
    assert "dodaios/quiet.py" in text and "agent_land.py" in text
    assert "check_silent_exception_handlers.py --update" in text


def test_main_json_and_exit_code(tmp_path, monkeypatch, capsys):
    root = _repo(tmp_path)
    _patch(monkeypatch)
    monkeypatch.setattr(cp, "files_changed_recently", lambda r: set())
    code = cp.main(["--json", "--root", str(root), "--no-gh", "--category", "long_function"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["symbol"] == "just_over"
    monkeypatch.setattr(cp, "files_changed_recently", lambda r: set(_files(r)))
    assert cp.main(["--root", str(root), "--no-gh"]) == 3
