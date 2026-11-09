#!/usr/bin/env python3
"""Check that the Verse module graph is exactly the DAG of architecture.md section 2.

Every ``*.Build.cs`` under ``unreal/Verse/Source`` is parsed; every string
literal naming a ``Verse*`` module counts as an edge, whichever dependency
list it sits in. The check fails when:

* a module directory exists that the table does not know, or a module in the
  table has no ``<Module>.Build.cs``;
* a module depends on a Verse module the table does not allow (rule 1);
* a module misses an edge the table lists (the table is exact, not a ceiling);
* the Verse graph has a cycle;
* a module no longer links an engine module that the engine table of
  architecture.md section 2 lists for it (``ENGINE`` below).

Engine modules a ``Build.cs`` names beyond the engine table are printed as
notes, not failures: each one is a change request to the integration owner,
who adds it to the table. A new Verse edge is a contract change: update the
table in ``docs/verse/unreal/architecture.md`` and ``ALLOWED`` below in the
same pull request.

    python scripts/unreal/check_build_dag.py            # the repo tree
    python scripts/unreal/check_build_dag.py --source <dir>
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = REPO_ROOT / "unreal" / "Verse" / "Source"

FEATURE = (
    "VerseCore",
    "VerseBridge",
    "VerseMovement",
    "VerseDestruction",
    "VerseCombat",
    "VerseGore",
    "VerseDecks",
    "VerseCrew",
    "VerseScreens",
    "VerseBot",
    "VerseUI",
    "VerseStream",
    "VerseAbilities",
)

#: architecture.md section 2, "May depend on (besides engine)".
ALLOWED: dict[str, frozenset[str]] = {
    "VerseCore": frozenset(),
    "VerseBridge": frozenset({"VerseCore"}),
    "VerseMovement": frozenset({"VerseCore"}),
    "VerseDestruction": frozenset({"VerseCore"}),
    "VerseCombat": frozenset({"VerseCore", "VerseMovement", "VerseDestruction"}),
    "VerseGore": frozenset({"VerseCore"}),
    "VerseDecks": frozenset({"VerseCore", "VerseBridge"}),
    "VerseCrew": frozenset({"VerseCore", "VerseBridge", "VerseDecks"}),
    "VerseScreens": frozenset({"VerseCore", "VerseBridge", "VerseDecks"}),
    "VerseBot": frozenset({"VerseCore", "VerseMovement", "VerseCombat", "VerseDestruction"}),
    "VerseUI": frozenset({"VerseCore", "VerseBridge", "VerseCombat", "VerseCrew", "VerseDecks"}),
    "VerseStream": frozenset({"VerseCore", "VerseBridge"}),
    "VerseAbilities": frozenset({"VerseCore", "VerseMovement"}),
    # Primary module: every runtime module except the harness.
    "Verse": frozenset(FEATURE),
    # DeveloperTool, Editor target only: every runtime module.
    "VerseHarness": frozenset(FEATURE) | {"Verse"},
}

#: Engine modules every module links; the engine table leaves them out.
BASE_ENGINE = frozenset({"Core", "CoreUObject", "Engine"})

#: architecture.md section 2, engine table: modules linked beyond ``BASE_ENGINE``.
ENGINE: dict[str, frozenset[str]] = {
    "VerseCore": frozenset({"GameplayTags", "Json"}),
    "VerseBridge": frozenset({"Json", "Slate", "SlateCore", "InputCore", "Sockets"}),
    "VerseMovement": frozenset({"EnhancedInput"}),
    "VerseDestruction": frozenset(
        {
            "NetCore",
            "Chaos",
            "GeometryCollectionEngine",
            "NavigationSystem",
            "MeshDescription",
            "PhysicsCore",
        }
    ),
    "VerseCombat": frozenset(
        {
            "NetCore",
            "GameplayTags",
            "GameplayAbilities",
            "GameplayTasks",
            "Json",
            "MeshDescription",
            "StaticMeshDescription",
        }
    ),
    "VerseGore": frozenset({"Niagara"}),
    "VerseDecks": frozenset({"Json"}),
    "VerseCrew": frozenset({"Json", "NavigationSystem"}),
    "VerseScreens": frozenset({"Json"}),
    "VerseBot": frozenset(
        {"AIModule", "NavigationSystem", "StateTreeModule", "GameplayStateTreeModule"}
    ),
    "VerseUI": frozenset(
        {
            "InputCore",
            "EnhancedInput",
            "Json",
            "Slate",
            "SlateCore",
            "RenderCore",
            "RHI",
            "ImageCore",
        }
    ),
    "VerseStream": frozenset(),
    "VerseAbilities": frozenset({"AudioExtensions"}),
    "Verse": frozenset(
        {
            "NetCore",
            "DeveloperSettings",
            "EngineSettings",
            "GameplayAbilities",
            "GameplayTags",
            "GameplayTasks",
        }
    ),
    "VerseHarness": frozenset(),
}

_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_LITERAL = re.compile(r'"(Verse[A-Za-z0-9_]*)"')
_MODULE_LIST = re.compile(
    r"(?:Public|Private)DependencyModuleNames\.AddRange\(\s*new\s+string\[\]\s*\{([^}]*)\}"
)
_ANY_LITERAL = re.compile(r'"([A-Za-z0-9_]+)"')


def edges_of(build_cs: Path) -> set[str]:
    """Verse module names a Build.cs names as string literals (comments ignored)."""
    text = _COMMENT.sub("", build_cs.read_text(encoding="utf-8-sig"))
    return set(_LITERAL.findall(text))


def engine_modules_of(build_cs: Path) -> set[str]:
    """Engine modules in the dependency lists of a Build.cs, without ``BASE_ENGINE``."""
    text = _COMMENT.sub("", build_cs.read_text(encoding="utf-8-sig"))
    names: set[str] = set()
    for block in _MODULE_LIST.findall(text):
        names.update(_ANY_LITERAL.findall(block))
    return {n for n in names if not n.startswith("Verse")} - BASE_ENGINE


def engine_notes(source: Path) -> list[str]:
    """Engine modules a Build.cs links that the engine table does not list (notes only)."""
    notes: list[str] = []
    for name in sorted(ENGINE):
        build_cs = source / name / f"{name}.Build.cs"
        if build_cs.is_file():
            for extra in sorted(engine_modules_of(build_cs) - ENGINE[name]):
                notes.append(
                    f"{name} links engine module {extra}, which the engine table does not list"
                )
    return notes


def find_cycle(graph: dict[str, set[str]]) -> list[str]:
    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        state[node] = 1
        stack.append(node)
        for dep in sorted(graph.get(node, ())):
            if state.get(dep) == 1:
                return stack[stack.index(dep) :] + [dep]
            if dep not in state:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        state[node] = 2
        return []

    for node in sorted(graph):
        if node not in state:
            found = visit(node)
            if found:
                return found
    return []


def check(source: Path) -> list[str]:
    problems: list[str] = []
    if not source.is_dir():
        return [f"{source}: no Unreal source folder"]
    graph: dict[str, set[str]] = {}
    for module_dir in sorted(p for p in source.iterdir() if p.is_dir()):
        name = module_dir.name
        build_cs = module_dir / f"{name}.Build.cs"
        if name not in ALLOWED:
            problems.append(
                f"{name}: not in the architecture table (a new module is a contract change)"
            )
            continue
        if not build_cs.is_file():
            problems.append(f"{name}: missing {build_cs.name}")
            continue
        found = edges_of(build_cs) - {name}
        graph[name] = found
        for extra in sorted(found - ALLOWED[name]):
            problems.append(f"{name} -> {extra}: edge not allowed by architecture.md section 2")
        for missing in sorted(ALLOWED[name] - found):
            problems.append(
                f"{name} -> {missing}: edge listed in architecture.md section 2 is missing"
            )
        for missing in sorted(ENGINE.get(name, frozenset()) - engine_modules_of(build_cs)):
            problems.append(
                f"{name}: engine module {missing} listed in architecture.md section 2 is not linked"
            )
    for name in sorted(set(ALLOWED) - set(graph)):
        if not any(p.startswith(f"{name}:") for p in problems):
            problems.append(f"{name}: module folder missing under {source}")
    cycle = find_cycle(graph)
    if cycle:
        problems.append("cycle: " + " -> ".join(cycle))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args(argv)
    if args.source == DEFAULT_SOURCE and not DEFAULT_SOURCE.exists():
        print("check_build_dag: no unreal/Verse/Source in this tree, nothing to check")
        return 0
    problems = check(args.source)
    for line in engine_notes(args.source):
        print(f"check_build_dag: note: {line}")
    for line in problems:
        print(f"check_build_dag: {line}")
    if problems:
        return 1
    print(f"check_build_dag: {len(ALLOWED)} modules match architecture.md section 2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
