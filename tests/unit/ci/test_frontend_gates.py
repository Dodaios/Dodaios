"""The frontend escapes gate and the duplicate-code gate (scripts/ci)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CI = Path(__file__).resolve().parents[3] / "scripts" / "ci"
sys.path.insert(0, str(_CI))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _CI / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_escapes_count_any_ignores_and_disables() -> None:
    m = _load("check_frontend_escapes")
    src = "\n".join(
        [
            "const a: any = 1;",
            "const b = x as any;",
            "const c = new Map<string, any>();",
            "// a comment that says as any is fine",
            "// @ts-ignore",
            "// @ts-expect-error: the library types are wrong",
            "// @ts-expect-error",
            "// eslint-disable-next-line no-console",
            "// eslint-disable-next-line no-console -- debug output",
            "const company = 1; // not any",
        ]
    )
    assert m.count_source(src) == {"any": 3, "ts-ignore": 2, "eslint": 1}


def test_escapes_baseline_holds_on_the_tree(capsys) -> None:
    m = _load("check_frontend_escapes")
    assert m.main([]) == 0, capsys.readouterr().out


def test_duplicates_find_a_pasted_block_across_files() -> None:
    m = _load("check_duplicates")
    block = "\n".join(f"value_{i} = compute({i}) + other_{i}" for i in range(14))
    files = {
        "a.py": "import os\n" + block + "\nx = 1\n",
        "b.py": "# header\n" + block + "\ny = 2\n",
        "c.py": "\n".join(f"unique_{i} = {i}" for i in range(20)),
    }
    found = m.find_duplicates(files)
    assert set(found) == {("a.py", "b.py"), ("b.py", "a.py")}
    assert found[("a.py", "b.py")] == [(2, 15)]


def test_duplicates_ignore_short_and_comment_only_repeats() -> None:
    m = _load("check_duplicates")
    block = "\n".join(f"v{i} = f({i})" for i in range(11))
    comments = "\n".join(f"# same comment {i}" for i in range(30))
    files = {"a.py": block + "\n" + comments, "b.py": block + "\n" + comments}
    assert m.find_duplicates(files) == {}


def test_duplicates_same_file_needs_distance() -> None:
    m = _load("check_duplicates")
    block = "\n".join(f"v{i} = f({i})" for i in range(12))
    assert m.find_duplicates({"a.py": block + "\n" + block}) != {}
    assert m.find_duplicates({"a.py": block}) == {}


def test_duplicates_baseline_holds_on_the_tree(capsys) -> None:
    m = _load("check_duplicates")
    assert m.main([]) == 0, capsys.readouterr().out


def test_touched_mode_judges_only_touched_files(tmp_path, monkeypatch, capsys) -> None:
    """With a base, a grown count in an untouched file passes; in a touched file it fails."""
    r = _load("_ratchet")
    m = _load("check_duplicates")
    monkeypatch.setattr(r, "CI_DIR", tmp_path)
    (tmp_path / "b.json").write_text('{"files": {"a.py": 5, "b.py": 5}}', encoding="utf-8")
    grown = {"a.py": 9, "b.py": 5}
    monkeypatch.setattr(r, "touched_paths", lambda base: {"b.py"})
    assert r.run("duplicates", lambda: grown, "b.json", "u", "rule", "fix", ["--base", "x"]) == 0
    monkeypatch.setattr(r, "touched_paths", lambda base: {"a.py"})
    assert r.run("duplicates", lambda: grown, "b.json", "u", "rule", "fix", ["--base", "x"]) == 1
    assert m.main.__module__  # the gate goes through r.run, so it inherits this mode
    capsys.readouterr()
