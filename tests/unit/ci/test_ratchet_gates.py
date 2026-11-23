"""The count ratchets (file size, function size, broad except, type ignore, source-text tests).

The gates run in run_gates.py. These tests check that each one detects what it claims
to and that a failure tells the agent how to fix it.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

_CI = Path(__file__).resolve().parents[3] / "scripts" / "ci"
sys.path.insert(0, str(_CI))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _CI / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = mod  # worker processes pickle functions by module name
    spec.loader.exec_module(mod)
    return mod


def test_compare_reports_new_grown_and_stale() -> None:
    r = _load("_ratchet")
    new, grown, stale = r.compare({"a": 3, "b": 2, "c": 1}, {"a": 2, "b": 5, "gone": 4})
    assert new == {"c": (0, 1)}
    assert grown == {"a": (2, 3)}
    assert stale == {"b": (5, 2), "gone": (4, 0)}


def test_failure_message_tells_how_to_fix(tmp_path, monkeypatch, capsys) -> None:
    r = _load("_ratchet")
    monkeypatch.setattr(r, "CI_DIR", tmp_path)
    (tmp_path / "x.json").write_text('{"files": {"gone.py": 7}}', encoding="utf-8")
    code = r.run("file-size", lambda: {"new.py": 9}, "x.json", "lines", "rule", "split it", [])
    out = capsys.readouterr().out
    assert code == 1
    assert "New violations" in out and "How to fix: split it" in out


def test_stale_entries_are_a_note_not_a_failure(tmp_path, monkeypatch, capsys) -> None:
    r = _load("_ratchet")
    monkeypatch.setattr(r, "CI_DIR", tmp_path)
    (tmp_path / "x.json").write_text('{"files": {"a.py": 7, "gone.py": 3}}', encoding="utf-8")
    code = r.run("file-size", lambda: {"a.py": 5}, "x.json", "lines", "rule", "fix", [])
    out = capsys.readouterr().out
    assert code == 0
    assert "can be tightened" in out and "check_file_size.py --update" in out


def test_update_refuses_increase(tmp_path, monkeypatch) -> None:
    r = _load("_ratchet")
    monkeypatch.setattr(r, "CI_DIR", tmp_path)
    (tmp_path / "x.json").write_text('{"files": {"a.py": 1}}', encoding="utf-8")
    assert r.run("t", lambda: {"a.py": 2}, "x.json", "u", "rule", "fix", ["--update"]) == 1
    assert r.run("t", lambda: {"a.py": 1}, "x.json", "u", "rule", "fix", ["--update"]) == 0
    assert (
        r.run("t", lambda: {"a.py": 3}, "x.json", "u", "r", "f", ["--update", "--allow-increase"])
        == 0
    )


def test_function_size_counts_lines_and_complexity() -> None:
    import ast

    gate = _load("check_function_size")
    big = "def big():\n" + "    x = 1\n" * 300
    branchy = "class C:\n    def branchy(self, a):\n" + "".join(
        f"        if a == {i}:\n            pass\n" for i in range(21)
    )
    found = dict(gate.functions(ast.parse(big + branchy)))
    assert set(found) == {"big", "C.branchy"}
    assert found["big"].end_lineno - found["big"].lineno + 1 > gate.MAX_LINES
    assert gate.complexity(found["C.branchy"]) > gate.MAX_COMPLEXITY
    assert gate.complexity(found["big"]) <= gate.MAX_COMPLEXITY


def test_broad_except_detects_and_honours_marker(tmp_path) -> None:
    gate = _load("check_broad_except")
    path = tmp_path / "m.py"
    path.write_text(
        textwrap.dedent(
            """
            try: pass
            except Exception: pass
            try: pass
            except BaseException: pass
            try: pass
            except: pass
            try: pass
            except ValueError: pass
            try: pass
            except Exception: pass  # broad-except: plugin boundary
            """
        ),
        encoding="utf-8",
    )
    assert gate.count_file(path) == 3


def test_type_ignore_only_counts_bare() -> None:
    gate = _load("check_type_ignore")
    src = "a = 1  # type: ignore\nb = 2  # type: ignore[attr-defined]\ns = '# type: ignore'\n"
    assert gate.count_source(src) == 1


def test_source_text_tests_counts_product_reads(tmp_path) -> None:
    gate = _load("check_source_text_tests")
    path = tmp_path / "test_x.py"
    path.write_text(
        textwrap.dedent(
            """
            import inspect
            from pathlib import Path
            SRC = Path("dodaios") / "a.py"
            def test_reads():
                assert "x" in SRC.READ()
            def test_inspects():
                assert inspect.GETSRC(len)
            def test_tmp(tmp_path):
                assert (tmp_path / "f").READ()
            def test_clean():
                assert 1
            """
        ),
        encoding="utf-8",
    )
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("READ", "read_text")
        .replace("GETSRC", "getsource"),
        encoding="utf-8",
    )
    assert gate.count_python(path) == 2
    front = tmp_path / "a.test.ts"
    front.write_text("import s from './a.tsx?raw'\nreadFileSync(x)\nok()\n", encoding="utf-8")
    assert gate.count_frontend(front) == 2
