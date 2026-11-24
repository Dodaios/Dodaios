"""The layer gate: what counts as a violation and how the baseline ratchets."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_GATE = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "check_layers.py"
_spec = importlib.util.spec_from_file_location("check_layers", _GATE)
assert _spec is not None and _spec.loader is not None
gate = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("check_layers", gate)
_spec.loader.exec_module(gate)

CFG = {
    "layers": [["platform", "i18n", "assets"], ["core"], [], ["ui"]],
    "default_layer": 2,
    "plugin_allowed": ["core", "platform", "i18n", "plugins"],
}


def _tree(tmp_path: Path, files: dict[str, str]) -> dict:
    for rel, source in files.items():
        path = tmp_path / "dodaios" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return gate.scan(tmp_path, CFG)


def test_core_importing_a_higher_layer_at_module_level_is_flagged(tmp_path: Path) -> None:
    found = _tree(
        tmp_path,
        {"core/a.py": "from dodaios.brain.x import Y\n", "brain/x.py": "Y = 1\n"},
    )
    assert found["module_level"] == [
        "dodaios.core.a -> dodaios.brain [A: core is a lower layer than brain]"
    ]
    assert found["function_level"] == []


def test_function_level_import_is_counted_separately(tmp_path: Path) -> None:
    found = _tree(
        tmp_path,
        {"core/a.py": "def f():\n    from dodaios.ui import z\n", "ui/z.py": ""},
    )
    assert found["module_level"] == []
    assert len(found["function_level"]) == 1


def test_type_checking_imports_do_not_count(tmp_path: Path) -> None:
    source = "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from dodaios.ui import z\n"
    found = _tree(tmp_path, {"core/a.py": source, "ui/z.py": ""})
    assert found["module_level"] == [] and found["function_level"] == []


def test_relative_imports_are_resolved(tmp_path: Path) -> None:
    found = _tree(tmp_path, {"core/a.py": "from ..ui import z\n", "ui/z.py": ""})
    assert len(found["module_level"]) == 1


def test_plugins_may_only_reach_core_platform_i18n(tmp_path: Path) -> None:
    source = "from dodaios.core import p\nfrom dodaios.harness import h\n"
    found = _tree(
        tmp_path,
        {"plugins/tool/t.py": source, "core/p.py": "", "harness/h.py": ""},
    )
    assert found["module_level"] == [
        "dodaios.plugins.tool.t -> dodaios.harness [B: a plugin may import only core/platform/i18n]"
    ]


def test_core_must_not_import_a_specific_plugin(tmp_path: Path) -> None:
    found = _tree(
        tmp_path,
        {"core/a.py": "import dodaios.plugins.tool.t\n", "plugins/tool/t.py": ""},
    )
    assert any("[B: core must not import a specific plugin]" in v for v in found["module_level"])


def test_largest_cycle_counts_packages_in_a_module_level_loop(tmp_path: Path) -> None:
    found = _tree(
        tmp_path,
        {
            "brain/a.py": "from dodaios.voice import b\n",
            "voice/b.py": "from dodaios.speech import c\n",
            "speech/c.py": "from dodaios.brain import a\n",
            "x/d.py": "from dodaios.brain import a\n",
        },
    )
    assert found["largest_cycle_size"] == 3


def _state(modules: list[str], cycle: int, members: list[str] | None = None) -> dict:
    return {
        "module_level": modules,
        "function_level": [],
        "largest_cycle_size": cycle,
        "_cycle_members": members or [],
    }


def test_baseline_only_shrinks() -> None:
    baseline = _state(["old"], 5)
    assert gate.compare(_state(["old"], 5), baseline) == []
    errors = " ".join(gate.compare(_state(["old", "new"], 6, ["a"]), baseline))
    assert "new" in errors and "grew to 6" in errors and "Fix:" in errors
    assert gate.compare(_state([], 4), baseline) == []


def test_repo_matches_its_committed_baseline() -> None:
    baseline = json.loads(gate._BASELINE.read_text(encoding="utf-8"))
    assert gate.compare(gate.scan(), baseline) == []
