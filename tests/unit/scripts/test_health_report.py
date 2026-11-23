"""Tests for ``scripts/health_report.py`` on a tiny fixture tree."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "health_report.py"
_spec = importlib.util.spec_from_file_location("health_report", SCRIPT)
hr = importlib.util.module_from_spec(_spec)
sys.modules["health_report"] = hr
_spec.loader.exec_module(hr)


def test_read_text_strips_bom_so_the_file_parses(tmp_path):
    f = tmp_path / "a.py"
    f.write_bytes(b"\xef\xbb\xbfx = 1\n")
    text = hr.read_text(f)
    assert text == "x = 1\n"
    assert hr.parse(text) is not None


def test_long_functions_and_patterns():
    src = "def big():\n" + "    pass\n" * 5 + "\ndef small():\n    pass\n"
    tree = ast.parse(src)
    assert hr.long_functions({"m.py": tree}, limit=3) == [("m.py:1 big", 6)]
    code = (
        "def f():\n    global X\n    try:\n        pass\n    except Exception:\n        pass\n"
        "    try:\n        pass\n    except:\n        pass\n    y = 1  # type: ignore\n"
    )
    counts = hr.pattern_counts({"m.py": code}, {"m.py": ast.parse(code)})
    assert counts == {
        "except_exception": 1,
        "bare_except": 1,
        "type_ignore": 1,
        "global_statements": 1,
    }


def test_largest_scc_finds_the_cycle():
    edges = {("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")}
    assert hr.largest_scc({"a", "b", "c", "d"}, edges) == ["a", "b", "c"]
    assert len(hr.largest_scc({"a", "b"}, {("a", "b")})) == 1


def test_package_edges_separate_module_level_from_lazy():
    core = "import dodaios.ui\n\ndef f():\n    from dodaios import brain\n"
    trees = {
        "dodaios/core/x.py": ast.parse(core),
        "dodaios/ui/__init__.py": ast.parse(""),
    }
    packages = {"core", "ui", "brain"}
    all_edges, top_edges = hr.package_edges(trees, packages)
    assert all_edges == {("core", "ui"), ("core", "brain")}
    assert top_edges == {("core", "ui")}


def test_comment_share_counts_comments_and_docstrings():
    src = '"""doc\nmore"""\n# c\nx = 1\n'
    out = hr.comment_share({"m.py": src}, {"m.py": ast.parse(src)})
    assert out == {"lines": 4, "comment_lines": 1, "docstring_lines": 2}


def test_tests_reading_source_and_env_names():
    src = (
        "def test_a(tmp_path):\n    Path('dodaios/x.py').read_text()\n"
        "def test_b():\n    pass\n"
    )
    out = hr.tests_reading_source({"t.py": src}, {"t.py": ast.parse(src)})
    assert out == {"files": 1, "test_functions": 1}
    names = hr.env_names({"a.py": "JARVIS_A DODAIOS_B JARVIS_A"})
    assert names == {"JARVIS": ["JARVIS_A"], "DODAIOS": ["DODAIOS_B"]}


def test_collect_on_a_tiny_git_repo(tmp_path):
    (tmp_path / "dodaios" / "core").mkdir(parents=True)
    (tmp_path / "dodaios" / "ui").mkdir()
    (tmp_path / "dodaios" / "__init__.py").write_text("")
    (tmp_path / "dodaios" / "core" / "__init__.py").write_text("import dodaios.ui\n")
    (tmp_path / "dodaios" / "ui" / "__init__.py").write_text("# jarvis\nimport dodaios.core\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "s.sh").write_text("echo hi\n")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)

    report = hr.collect(tmp_path, workers=1)

    assert report["dodaios_python"]["modules"] == 3
    assert report["dodaios_python"]["packages"] == 2
    assert report["import_graph"]["largest_scc_all_imports"] == 2
    assert report["import_graph"]["core_imports_upper_layers_at_module_level"] is True
    assert report["jarvis_name"]["occurrences_in_py"] == 1
    assert report["scripts_files"] == 1
    assert "Repo health" in hr.to_markdown(report)
