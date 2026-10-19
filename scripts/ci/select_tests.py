#!/usr/bin/env python3
"""Pick the test files a change can plausibly affect (impact selection).

Used where running everything is expensive and a full run follows anyway:
the macOS tests of a merge-queue group (the whole suite on macOS is 27
runner-minutes on five shared slots and runs nightly) and
``scripts/agent_land.py``'s fast local check.

Selection is textual and deliberately generous — FAIL OPEN:

* a changed test file selects itself;
* a changed ``dodaios/a/b.py`` selects every test that names ``jarvis.a.b``
  (import or monkeypatch target) and every ``test_b*.py``;
* any other changed file (frontend source, docs, assets) selects the tests
  that mention its path or its file stem;
* a change the agent-runtime lane covers adds that lane's whole suite
  (``agent_runtime_suite.SUITE``);
* conftest, packaging, lockfiles or the pipeline itself select EVERYTHING,
  and so does a selection larger than :data:`ALL_RATIO` of the suite.

``--one-runner`` sizes the selection for the one macOS runner of a merge
group. A change that reaches everything (or more than :data:`SHARD_FILES`
files) runs the macOS-focused set instead, the tests of the code that asks
for or acts on a macOS facility. Every selection is then filled up to
:data:`MAC_BUDGET_SECONDS` of test history with the tests most likely to
behave differently on macOS: the focused set, the tests of the other
directories the macOS lane watches, and every test that names macOS itself.

Writes the file list to ``--out`` and ``mode=all|selected|none``,
``count=N`` and ``shards=[...]`` (how many runners the selection needs) to
``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci import agent_runtime_suite, classify_changes  # noqa: E402
from scripts.ci.run_tests_parallel import discover, estimate, load_durations  # noqa: E402

ALL_RATIO = 0.35
#: A selection up to this many files still fits one runner in about the time
#: the other legs of a run take; a larger one gets two, everything gets three.
SHARD_FILES = 450
FULL_SHARDS = 3
#: What the macOS job of a merge group may spend on tests, as the sum of the
#: per-file history. The runner has three workers: 389 s of history ran in
#: 157 s and 384 s in 142 s (2026-10-13), so 660 s is about five minutes and
#: the job ends before the Windows shards the gate waits for (8 to 9 minutes).
MAC_BUDGET_SECONDS = 660.0
_MAC_WORDS = re.compile(r"darwin|macos", re.IGNORECASE)
_EVERYTHING_PREFIXES = (".github/workflows/", "scripts/ci/", "tests/fakes/", "tests/fixtures/")
_EVERYTHING_FILES = {
    "conftest.py",
    "tests/conftest.py",
    "tests/unit/conftest.py",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "dodaios/__init__.py",
}
# The contract guards: cheap, and they pin the invariants a
# change anywhere in dodaios/ can break without importing them by name.
SMOKE = (
    "tests/unit/brain/test_routing.py",
    "tests/unit/brain/test_output_filter.py",
    "tests/unit/sessions/test_hangup_reason_parity.py",
    "tests/unit/core/test_turn_language.py",
)
_MIN_STEM = 5


def _needles(path: str) -> list[str]:
    stem = Path(path).stem
    if path.startswith("dodaios/") and path.endswith(".py"):
        dotted = path[:-3].replace("/", ".")
        if dotted.endswith(".__init__"):
            dotted = dotted[: -len(".__init__")]
        parent, _, leaf = dotted.rpartition(".")
        needles = [dotted, f"from {parent} import {leaf}" if parent else dotted]
        return needles
    needles = [path]
    if len(stem) >= _MIN_STEM and stem not in {"index", "__init__", "README", "types"}:
        needles.append(stem)
    return needles


def select(changed: list[str], tests: list[str], texts: dict[str, str]) -> tuple[str, list[str]]:
    changed = [c.strip().replace("\\", "/") for c in changed if c.strip()]
    if not changed:
        return "all", list(tests)
    if any(c.startswith(_EVERYTHING_PREFIXES) or c in _EVERYTHING_FILES for c in changed):
        return "all", list(tests)
    if any(Path(c).name == "conftest.py" for c in changed):
        return "all", list(tests)
    chosen: set[str] = set()
    touches_product = False
    test_set = set(tests)
    for path in changed:
        if path in test_set:
            chosen.add(path)
            continue
        if path.startswith("dodaios/"):
            touches_product = True
        stem = Path(path).stem
        if path.endswith(".py") and stem != "__init__":
            pattern = re.compile(rf"(^|/)test_{re.escape(stem)}(_[^/]*)?\.py$")
            chosen.update(t for t in tests if pattern.search(t))
        needles = _needles(path)
        for test, text in texts.items():
            if any(needle in text for needle in needles):
                chosen.add(test)
    if touches_product:
        chosen.update(t for t in SMOKE if t in test_set)
    if any(agent_runtime_suite.touches(path) for path in changed):
        # The runtimes are driven by the chat and the society; a change on
        # either side runs the whole chain, not only the importing tests.
        for entry in agent_runtime_suite.SUITE:
            chosen.update(t for t in tests if t == entry or t.startswith(entry.rstrip("/") + "/"))
    if len(chosen) > ALL_RATIO * max(1, len(tests)):
        return "all", list(tests)
    if not chosen:
        return "none", []
    return "selected", sorted(chosen)


def mac_focus(tests: list[str]) -> list[str]:
    """The tests of the macOS lane's own code, plus the contract guards.

    About 200 files and two to three minutes on one runner: what a merge
    group runs on macOS when its change reaches the whole suite.
    """
    prefixes = tuple(p for p in classify_changes._MACOS_PREFIXES if p.startswith("tests/"))
    return sorted({t for t in tests if t.startswith(prefixes)} | {t for t in SMOKE if t in tests})


def mac_lane_tests(tests: list[str]) -> list[str]:
    """The unit tests of every product directory the macOS lane watches."""
    prefixes = tuple(
        "tests/unit/" + (p[len("dodaios/") :] if p.startswith("dodaios/") else p)
        for p in classify_changes._MACOS_PREFIXES
        if p.endswith("/") and not p.startswith(("tests/", "packaging/"))
    )
    return sorted(t for t in tests if t.startswith(prefixes))


def mac_aware(tests: list[str], texts: dict[str, str]) -> list[str]:
    """The tests that name macOS: they branch on the platform or skip by it."""
    return sorted(t for t in tests if _MAC_WORDS.search(texts.get(t, "")))


def one_runner(
    mode: str,
    chosen: list[str],
    tests: list[str],
    texts: dict[str, str] | None = None,
    durations: dict[str, float] | None = None,
    budget: float = MAC_BUDGET_SECONDS,
) -> tuple[str, list[str]]:
    """Size a selection for one macOS runner; ``none`` stays ``none``.

    What the change reaches always runs (the focused set for a change that
    reaches everything). The rest of the budget goes to the tests a macOS-only
    failure is most likely to show in, cheapest first so the budget covers as
    many files as it can.
    """
    if mode == "none":
        return mode, chosen
    history = durations or {}
    focus = mac_focus(tests)
    kept = set(focus if mode == "all" or len(chosen) > SHARD_FILES else chosen)
    spent = sum(estimate(file, history) for file in kept)
    for tier in (focus, mac_lane_tests(tests), mac_aware(tests, texts or {})):
        for file in sorted(set(tier) - kept, key=lambda f: (estimate(f, history), f)):
            cost = estimate(file, history)
            if spent + cost > budget:
                break
            kept.add(file)
            spent += cost
    return "selected", sorted(kept)


def shards_for(mode: str, count: int) -> list[int]:
    """The runners a selection needs: none, one, two, or the full split."""
    if mode == "none":
        return []
    if mode == "all":
        return list(range(1, FULL_SHARDS + 1))
    return [1] if count <= SHARD_FILES else [1, 2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--changed-from", type=Path, help="File with changed paths (else stdin).")
    parser.add_argument("--out", type=Path, default=Path("selected-tests.txt"))
    parser.add_argument(
        "--one-runner",
        action="store_true",
        help="Size the selection for the one macOS runner of a merge group.",
    )
    parser.add_argument(
        "--durations",
        type=Path,
        help="Per-file duration history: what the selection costs (--one-runner).",
    )
    args = parser.parse_args(argv)

    if args.changed_from:
        changed = args.changed_from.read_text(encoding="utf-8").splitlines()
    else:
        changed = sys.stdin.read().splitlines()
    tests = discover(["tests"])
    texts = {
        t: (REPO_ROOT / t).read_text(encoding="utf-8", errors="replace").replace("\\", "/")
        for t in tests
    }
    mode, chosen = select(changed, tests, texts)
    shard_list = shards_for(mode, len(chosen))
    if args.one_runner:
        reached = len(chosen) if mode == "selected" else 0
        history = load_durations(args.durations)
        mode, chosen = one_runner(mode, chosen, tests, texts, history)
        shard_list = [1] if chosen else []
        cost = sum(estimate(file, history) for file in chosen)
        print(f"reached={reached} one-runner files={len(chosen)} history={cost:.0f}s")
    args.out.write_text("\n".join(chosen) + ("\n" if chosen else ""), encoding="utf-8")
    print(f"mode={mode} count={len(chosen)} of {len(tests)}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            shards = json.dumps(shard_list, separators=(",", ":"))
            handle.write(f"mode={mode}\ncount={len(chosen)}\nshards={shards}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
