"""A plugin group is one group under two names: ``dodaios.<slot>`` and ``jarvis.<slot>``.

Plugins published before the product was renamed register under
``jarvis.<slot>`` and must keep loading untouched, forever. New plugins register
under ``dodaios.<slot>``. These tests run against a real, temporary
``site-packages`` holding synthetic distributions, and count the scans
``importlib.metadata`` makes through its own extension point (a
``DistributionFinder`` on ``sys.meta_path``), so "one pass over the installed
distributions" is measured rather than asserted from the code's shape.
"""

from __future__ import annotations

import ast
import logging
import sys
import tomllib
from collections.abc import Iterator
from importlib import metadata
from pathlib import Path

import pytest

import jarvis.core.branding as branding
from jarvis.core import entry_points as ep_module
from jarvis.core import registry
from jarvis.core.protocols import PLUGIN_GROUPS

_ROOT = Path(__file__).resolve().parents[3]

#: A slot no real distribution declares, so the answers below are exactly the
#: synthetic distributions and nothing the test environment happens to hold.
_OLD = "jarvis.selftest"
_NEW = "dodaios.selftest"


class _ScanCounter(metadata.DistributionFinder):
    """Counts how often ``importlib.metadata`` enumerates the distributions."""

    def __init__(self) -> None:
        self.scans = 0

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001, ANN201, ARG002
        return None

    def find_distributions(self, context=None):  # noqa: ANN001, ANN201, ARG002
        self.scans += 1
        return iter(())


class _Site:
    """A temporary ``site-packages`` that synthetic distributions are written to."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def add(self, name: str, entry_points: dict[str, dict[str, str]], module: str = "") -> None:
        # The directory carries the normalised name: ``importlib.metadata``
        # reads a distribution's identity from the stem up to the first dash.
        package = name.replace("-", "_")
        info = self.root / f"{package}-1.0.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n", encoding="utf-8"
        )
        lines: list[str] = []
        for group, entries in entry_points.items():
            lines.append(f"[{group}]")
            lines.extend(f"{key} = {value}" for key, value in entries.items())
            lines.append("")
        (info / "entry_points.txt").write_text("\n".join(lines), encoding="utf-8")
        if module:
            (self.root / f"{package}.py").write_text(module, encoding="utf-8")


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Site]:
    monkeypatch.syspath_prepend(str(tmp_path))
    ep_module.invalidate()
    yield _Site(tmp_path)
    for name in [key for key in sys.modules if key.startswith("selftest_")]:
        del sys.modules[name]


@pytest.fixture
def scans(monkeypatch: pytest.MonkeyPatch) -> _ScanCounter:
    counter = _ScanCounter()
    monkeypatch.setattr(sys, "meta_path", [*sys.meta_path, counter])
    return counter


def _names(group: str) -> list[str]:
    return sorted(ep.name for ep in ep_module.entry_points(group=group))


# ---------------------------------------------------------------------------
# The two spellings
# ---------------------------------------------------------------------------


def test_the_current_and_the_legacy_namespace_come_from_branding() -> None:
    assert branding.PLUGIN_GROUP_NAMESPACE == "dodaios"
    assert branding.LEGACY_PLUGIN_GROUP_NAMESPACES == ("jarvis",)
    assert ep_module.group_spellings("jarvis.tool") == ("dodaios.tool", "jarvis.tool")
    assert ep_module.group_spellings("dodaios.tool") == ("dodaios.tool", "jarvis.tool")


@pytest.mark.parametrize("group", ["console_scripts", "jarvis", "other.tool", "jarvis."])
def test_a_group_outside_the_plugin_namespaces_has_one_spelling(group: str) -> None:
    assert ep_module.group_spellings(group) == (group,)


def test_every_plugin_slot_is_readable_under_the_new_name() -> None:
    for group in PLUGIN_GROUPS:
        current, legacy = ep_module.group_spellings(group)
        assert legacy == group
        assert current == f"dodaios.{group.partition('.')[2]}"


# ---------------------------------------------------------------------------
# Discovery against real synthetic distributions
# ---------------------------------------------------------------------------


def test_a_plugin_published_under_the_old_group_keeps_loading(site: _Site) -> None:
    """The compatibility promise: a third-party plugin nobody touches still loads."""
    site.add(
        "selftest-old", {_OLD: {"alpha": "selftest_old:Alpha"}}, "class Alpha:\n    tag = 'old'\n"
    )

    for asked in (_OLD, _NEW):
        (found,) = ep_module.entry_points(group=asked)
        assert (found.name, found.group) == ("alpha", _OLD)
        assert found.load().tag == "old"


def test_a_plugin_published_under_the_new_group_is_discovered(site: _Site) -> None:
    site.add(
        "selftest-new", {_NEW: {"beta": "selftest_new:Beta"}}, "class Beta:\n    tag = 'new'\n"
    )

    for asked in (_OLD, _NEW):
        (found,) = ep_module.entry_points(group=asked)
        assert (found.name, found.group) == ("beta", _NEW)
        assert found.load().tag == "new"


def test_both_groups_are_one_catalogue(site: _Site) -> None:
    site.add("selftest-old", {_OLD: {"alpha": "selftest_old:Alpha"}})
    site.add("selftest-new", {_NEW: {"beta": "selftest_new:Beta"}})

    assert _names(_OLD) == _names(_NEW) == ["alpha", "beta"]


def test_a_plugin_registered_under_both_groups_loads_once(
    site: _Site, caplog: pytest.LogCaptureFixture
) -> None:
    """One wheel that serves an older host and this one is not a duplicate."""
    site.add(
        "selftest-both",
        {_OLD: {"gamma": "selftest_both:Gamma"}, _NEW: {"gamma": "selftest_both:Gamma"}},
        "class Gamma:\n    pass\n",
    )

    with caplog.at_level(logging.WARNING, logger=ep_module.__name__):
        found = ep_module.entry_points(group=_OLD)

    assert [(ep.name, ep.group) for ep in found] == [("gamma", _NEW)]
    assert caplog.records == []


def test_a_name_claimed_by_two_objects_resolves_to_the_new_group(
    site: _Site, caplog: pytest.LogCaptureFixture
) -> None:
    """The conflict rule: ``dodaios.<slot>`` wins, and the clash is logged."""
    site.add(
        "selftest-clash",
        {_OLD: {"delta": "selftest_clash:Legacy"}, _NEW: {"delta": "selftest_clash:Current"}},
        "class Legacy:\n    pass\n\n\nclass Current:\n    pass\n",
    )

    with caplog.at_level(logging.WARNING, logger=ep_module.__name__):
        (found,) = ep_module.entry_points(group=_OLD)

    assert found.load().__name__ == "Current"
    (record,) = caplog.records
    message = record.getMessage()
    assert "'delta'" in message
    assert "selftest_clash:Legacy" in message and "selftest_clash:Current" in message


def test_the_conflict_rule_holds_across_two_distributions(site: _Site) -> None:
    site.add("selftest-a", {_OLD: {"delta": "selftest_a:Legacy", "kept": "selftest_a:Kept"}})
    site.add("selftest-b", {_NEW: {"delta": "selftest_b:Current"}})

    found = {ep.name: ep.value for ep in ep_module.entry_points(group=_NEW)}

    assert found == {"delta": "selftest_b:Current", "kept": "selftest_a:Kept"}


# ---------------------------------------------------------------------------
# Cost: one scan of the installed distributions per read, not one per spelling
# ---------------------------------------------------------------------------


def test_reading_both_spellings_costs_the_one_scan_a_single_group_costs(
    site: _Site, scans: _ScanCounter
) -> None:
    site.add("selftest-old", {_OLD: {"alpha": "selftest_old:Alpha"}})
    site.add("selftest-new", {_NEW: {"beta": "selftest_new:Beta"}})

    list(metadata.entry_points(group=_OLD))
    baseline = scans.scans
    assert baseline == 1, "importlib.metadata reads one group in one scan"

    assert _names(_OLD) == ["alpha", "beta"]
    assert scans.scans - baseline == 1


def test_the_cache_holds_both_spellings_under_one_entry(site: _Site, scans: _ScanCounter) -> None:
    site.add("selftest-old", {_OLD: {"alpha": "selftest_old:Alpha"}})
    site.add("selftest-new", {_NEW: {"beta": "selftest_new:Beta"}})

    for _ in range(5):
        old = ep_module.entry_points_for(_OLD)
        new = ep_module.entry_points_for(_NEW)

    assert old is new
    assert sorted(ep.name for ep in old) == ["alpha", "beta"]
    assert scans.scans == 1


def test_every_plugin_slot_under_both_names_costs_one_scan_per_slot(
    scans: _ScanCounter,
) -> None:
    """Boot resolves each slot; the second name must not buy a second scan."""
    ep_module.invalidate()
    for group in PLUGIN_GROUPS:
        for spelling in ep_module.group_spellings(group):
            ep_module.entry_points_for(spelling)

    assert scans.scans == len(PLUGIN_GROUPS)


def test_an_interpreter_without_one_sweep_selection_still_finds_both(
    site: _Site, scans: _ScanCounter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback is slower, never wrong."""
    site.add("selftest-old", {_OLD: {"alpha": "selftest_old:Alpha"}})
    site.add("selftest-new", {_NEW: {"beta": "selftest_new:Beta"}})
    monkeypatch.setattr(ep_module, "_ONE_SWEEP", False)

    assert _names(_OLD) == ["alpha", "beta"]
    assert scans.scans == 2


def test_this_interpreter_selects_in_one_sweep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ep_module, "_ONE_SWEEP", None)
    assert ep_module._selects_in_one_sweep() is True


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------


def test_the_registry_serves_a_slot_under_either_name(site: _Site) -> None:
    site.add(
        "selftest-tool",
        {"dodaios.tool": {"selftest-new-tool": "selftest_tool:NewTool"}},
        "class NewTool:\n    pass\n",
    )
    site.add(
        "selftest-legacy-tool",
        {"jarvis.tool": {"selftest-old-tool": "selftest_legacy_tool:OldTool"}},
        "class OldTool:\n    pass\n",
    )

    for group in ("jarvis.tool", "dodaios.tool"):
        listed = registry.list_plugins(group)
        assert listed.count("selftest-new-tool") == 1
        assert listed.count("selftest-old-tool") == 1
        assert registry.load(group, "selftest-new-tool").__name__ == "NewTool"
        assert registry.load(group, "selftest-old-tool").__name__ == "OldTool"

    with pytest.raises(ValueError, match="Unknown plugin group"):
        registry.list_plugins("dodaios.nonexistent")


def _shipped_python_files() -> list[Path]:
    return [
        path
        for path in (_ROOT / "jarvis").rglob("*.py")
        if "node_modules" not in path.parts
    ]


def test_no_module_reads_a_plugin_group_behind_the_helpers_back() -> None:
    """A direct ``importlib.metadata`` read sees one spelling and misses the other."""
    offenders: list[str] = []
    for path in _shipped_python_files():
        relative = path.relative_to(_ROOT).as_posix()
        if relative == "jarvis/core/entry_points.py":
            continue
        source = path.read_text(encoding="utf-8-sig")
        if "entry_points" not in source:
            continue
        for node in ast.walk(ast.parse(source)):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "importlib.metadata"
                and any(alias.name == "entry_points" for alias in node.names)
            ):
                offenders.append(f"{relative}:{node.lineno}: imports entry_points")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "entry_points"
                and isinstance(node.func.value, (ast.Name, ast.Attribute))
                and ast.unparse(node.func.value).endswith(("metadata", "_md"))
            ):
                offenders.append(f"{relative}:{node.lineno}: calls metadata.entry_points")
    assert not offenders, "read plugin groups through jarvis.core.entry_points:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    "module",
    [
        "jarvis.brain.provider_registry",
        "jarvis.channels.manager",
        "jarvis.diagnostics.doctor",
        "jarvis.harness.manager",
    ],
)
def test_a_manager_discovers_through_the_helper(module: str) -> None:
    import importlib

    assert importlib.import_module(module).entry_points is ep_module.entry_points


# ---------------------------------------------------------------------------
# First-party plugins
# ---------------------------------------------------------------------------


def _declared_groups() -> dict[str, dict[str, str]]:
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    return project.get("entry-points", {})


def test_a_first_party_plugin_is_never_declared_with_two_targets() -> None:
    """Whichever spelling ``pyproject.toml`` uses, one name means one object.

    A stale ``*.dist-info`` (an install updated without rebuilding its
    environment) holds the entry points of the version that wrote it; a fresh
    one holds today's. Both load each first-party plugin exactly once as long
    as the two spellings never disagree about a name.
    """
    groups = _declared_groups()
    for group in PLUGIN_GROUPS:
        current, legacy = ep_module.group_spellings(group)
        ours, theirs = groups.get(current, {}), groups.get(legacy, {})
        clashes = {name for name in ours.keys() & theirs.keys() if ours[name] != theirs[name]}
        assert not clashes, f"{current} and {legacy} disagree about {sorted(clashes)}"


def test_first_party_plugins_stay_reachable_by_a_host_that_reads_only_the_old_group() -> None:
    """A rollback to an older version reads ``jarvis.<slot>`` and nothing else."""
    groups = _declared_groups()
    for group in PLUGIN_GROUPS:
        current, legacy = ep_module.group_spellings(group)
        missing = sorted(set(groups.get(current, {})) - set(groups.get(legacy, {})))
        assert not missing, f"{missing} are only in {current}; an older host cannot load them"
