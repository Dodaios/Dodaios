"""The project brief: what the code builder knows about one of the person's repositories.

A brief is stored per repository checkout (``self_build_code.db``) and made of
parts. Each part remembers the key it was built for, and a refresh rebuilds
only the parts whose key changed:

* ``git``: HEAD, branch, default branch, GitHub repository (HEAD moves).
* ``structure``: stack, top folders, languages, a file map (the tree changes).
* ``commands``: how to set up and test, what CI runs (the tree changes).
* ``conventions``: AGENTS.md, CLAUDE.md and the like (one changes on disk).
* ``activity``: recent commits, what the person worked on (HEAD moves).
* ``github``: open issues and pull requests (each issue poll, ``intake``).
* ``outcomes``: merged / changed / closed loop PRs, lessons (``watch``).

Everything here is deterministic: git calls and file reads, no model. Keys
are read with three cheap git calls and a few ``stat`` calls, so an unchanged
project costs almost nothing to refresh.
"""

from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from loguru import logger

from . import commands, gitcmd
from .store import CodeStore

#: Instruction files whose rules the coding agent must follow.
INSTRUCTION_FILES: Final[tuple[str, ...]] = (
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    "CONTRIBUTING.md",
)
_PER_FILE_CHARS: Final[int] = 2_500
_CONVENTIONS_CHARS: Final[int] = 6_000
_MAP_CHARS: Final[int] = 1_800
_RENDER_CHARS: Final[int] = 9_000
#: Parts this module builds from the checkout.
LOCAL_PARTS: Final[tuple[str, ...]] = ("git", "structure", "commands", "conventions", "activity")
_SKIP_DIRS: Final[frozenset[str]] = frozenset(
    {"node_modules", ".venv", "venv", "env", "dist", "build", "target", "__pycache__", ".git"}
)


@dataclass(frozen=True, slots=True)
class Brief:
    project_key: str
    folder: str
    repo: str
    parts: dict[str, Any]
    keys: dict[str, str]
    updated_ms: int = 0

    @property
    def test_commands(self) -> list[list[str]]:
        return [list(c) for c in (self.parts.get("commands") or {}).get("test") or []]

    @property
    def setup_commands(self) -> list[list[str]]:
        return [list(c) for c in (self.parts.get("commands") or {}).get("setup") or []]

    @property
    def default_branch(self) -> str:
        return str((self.parts.get("git") or {}).get("default_branch") or "")

    def render(self, max_chars: int = _RENDER_CHARS) -> str:
        """The brief as the text a coding agent reads first."""
        p = self.parts
        g = p.get("git") or {}
        s = p.get("structure") or {}
        c = p.get("commands") or {}
        a = p.get("activity") or {}
        lines = [f"Repository: {self.repo or '(no GitHub remote)'}"]
        if g.get("default_branch"):
            lines.append(f"Default branch: {g['default_branch']}")
        if s.get("stacks"):
            lines.append("Stack: " + ", ".join(s["stacks"]))
        if s.get("languages"):
            lines.append("Languages: " + ", ".join(s["languages"]))
        if s.get("top_level"):
            lines.append("Top-level folders: " + ", ".join(s["top_level"]))
        if c.get("test"):
            lines.append("Tests: " + " && ".join(commands.shown(cmd) for cmd in c["test"]))
        if c.get("ci"):
            lines.append("CI: " + " | ".join(c["ci"]))
        if a.get("mine"):
            lines.append("The person's recent commits here:")
            lines += [f"  - {subject}" for subject in a["mine"][:8]]
        if a.get("hot_paths"):
            lines.append("Where they have been working: " + ", ".join(a["hot_paths"]))
        outcomes = p.get("outcomes") or {}
        if outcomes.get("lessons"):
            lines.append("Earlier loop attempts here went wrong because:")
            lines += [f"  - {lesson}" for lesson in outcomes["lessons"][-5:]]
        if outcomes.get("changed"):
            lines.append("The person changed these loop PRs before merging:")
            lines += [f"  - {item}" for item in outcomes["changed"][-3:]]
        conventions = p.get("conventions") or {}
        for name, text in (conventions.get("files") or {}).items():
            lines += ["", f"--- {name} ---", text]
        if s.get("map"):
            lines += ["", "--- File map ---", s["map"]]
        text = "\n".join(lines)
        return text if len(text) <= max_chars else text[: max_chars - 1].rstrip() + "…"


# ------------------------------------------------------------------ keys


def project_key(folder: str | Path) -> str:
    """One key per repository checkout: every worktree shares its main checkout's."""
    from dodaios.agentic_ide.github_link import folder_key

    return folder_key(folder)


def _stamp(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        try:
            info = path.stat()
        except OSError:  # a file deleted meanwhile simply leaves the stamp
            continue
        digest.update(f"{path.name}:{info.st_size}:{info.st_mtime_ns}\n".encode())
    return digest.hexdigest()[:20]


def part_keys(folder: str | Path) -> dict[str, str]:
    root = Path(folder)
    head = gitcmd.out(["rev-parse", "HEAD"], root)
    tree = gitcmd.out(["rev-parse", "HEAD^{tree}"], root)
    present = [root / name for name in INSTRUCTION_FILES if (root / name).is_file()]
    return {
        "git": head,
        "structure": tree,
        "commands": tree,
        "conventions": _stamp(present) if present else "none",
        "activity": head,
    }


# ------------------------------------------------------------------ parts


def default_branch(root: Path) -> str:
    ref = gitcmd.out(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], root)
    if ref.startswith("origin/"):
        return ref.partition("/")[2]
    for name in ("main", "master", "trunk", "develop"):
        if gitcmd.git(["show-ref", "--verify", "--quiet", f"refs/heads/{name}"], root).ok:
            return name
    return gitcmd.out(["rev-parse", "--abbrev-ref", "HEAD"], root)


def _git_part(root: Path, repo: str) -> dict[str, Any]:
    return {
        "head": gitcmd.out(["rev-parse", "HEAD"], root),
        "branch": gitcmd.out(["rev-parse", "--abbrev-ref", "HEAD"], root),
        "default_branch": default_branch(root),
        "repo": repo,
    }


def _languages(root: Path) -> list[str]:
    listing = gitcmd.out(["ls-files"], root)
    counts: Counter[str] = Counter()
    for line in listing.splitlines()[:50_000]:
        suffix = Path(line).suffix.lower()
        if suffix and len(suffix) <= 6:
            counts[suffix] += 1
    return [f"{ext} ({n})" for ext, n in counts.most_common(6)]


def _structure_part(root: Path) -> dict[str, Any]:
    from dodaios.agentic_ide.folders import probe_project

    profile = probe_project(root)
    file_map = ""
    try:
        from dodaios.agentic_ide.file_index import build_index

        file_map = build_index(root).render_map(max_chars=_MAP_CHARS)
    except Exception as exc:  # noqa: BLE001 - the map is optional; the brief still helps
        logger.debug("self-build code: file map unavailable for {}: {}", root, exc)
    return {
        "stacks": list(profile.stacks),
        "top_level": [d for d in profile.top_level_dirs if d not in _SKIP_DIRS][:20],
        "languages": _languages(root),
        "map": file_map,
    }


def _conventions_part(root: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    budget = _CONVENTIONS_CHARS
    for name in INSTRUCTION_FILES:
        path = root / name
        if budget <= 0 or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:  # an unreadable instruction file is left out of the brief
            continue
        clip = text[: min(_PER_FILE_CHARS, budget)]
        files[name] = clip + ("…" if len(text) > len(clip) else "")
        budget -= len(clip)
    return {"files": files}


def _activity_part(root: Path) -> dict[str, Any]:
    email = gitcmd.out(["config", "user.email"], root).lower()
    log = gitcmd.out(["log", "-n", "40", "--format=%ae%x1f%ct%x1f%s"], root)
    recent: list[str] = []
    mine: list[str] = []
    for line in log.splitlines():
        author, _, rest = line.partition("\x1f")
        _stamp_, _, subject = rest.partition("\x1f")
        recent.append(subject)
        if email and author.lower() == email:
            mine.append(subject)
    hot: Counter[str] = Counter()
    if email:
        names = gitcmd.out(
            ["log", f"--author={email}", "--since=30.days", "--name-only", "--format="], root
        )
        for name in names.splitlines():
            parts = Path(name.strip()).parts
            if parts:
                hot["/".join(parts[:2]) if len(parts) > 2 else parts[0]] += 1
    return {
        "recent": recent[:15],
        "mine": mine[:15],
        "hot_paths": [path for path, _n in hot.most_common(8)],
        "person_active": bool(mine),
    }


def _build_part(part: str, root: Path, repo: str) -> Any:
    if part == "git":
        return _git_part(root, repo)
    if part == "structure":
        return _structure_part(root)
    if part == "commands":
        return commands.detect(root)
    if part == "conventions":
        return _conventions_part(root)
    if part == "activity":
        return _activity_part(root)
    raise ValueError(part)


# ------------------------------------------------------------------ refresh


def load(store: CodeStore, folder: str | Path) -> Brief | None:
    row = store.brief(project_key(folder))
    if row is None:
        return None
    return Brief(
        project_key=row["project_key"],
        folder=row["folder"],
        repo=row["repo"],
        parts=row["parts"],
        keys=row["keys"],
        updated_ms=row["updated_ms"],
    )


def refresh(store: CodeStore, folder: str | Path, *, repo: str = "") -> tuple[Brief, list[str]]:
    """The stored brief, with every stale local part rebuilt. Returns the brief
    and the names of the parts that were rebuilt (empty: nothing changed)."""
    root = Path(folder)
    key = project_key(root)
    old = store.brief(key) or {"parts": {}, "keys": {}, "repo": ""}
    keys = part_keys(root)
    parts = dict(old["parts"])
    stored_keys = dict(old["keys"])
    rebuilt: list[str] = []
    repo = repo or str(old.get("repo") or "")
    for part in LOCAL_PARTS:
        if part in parts and stored_keys.get(part) == keys[part] and keys[part]:
            continue
        try:
            parts[part] = _build_part(part, root, repo)
        except Exception as exc:  # noqa: BLE001 - one unreadable part must not lose the rest
            logger.warning("self-build code: brief part {} failed for {}: {}", part, root, exc)
            continue
        stored_keys[part] = keys[part]
        rebuilt.append(part)
    if rebuilt or repo != old.get("repo"):
        store.put_brief(key, folder=os.fspath(root), repo=repo, parts=parts, keys=stored_keys)
    return (
        Brief(project_key=key, folder=os.fspath(root), repo=repo, parts=parts, keys=stored_keys),
        rebuilt,
    )


def note_outcomes(store: CodeStore, folder: str | Path, profile: dict[str, Any]) -> None:
    """Fold the repository's outcome profile into its brief (``outcomes`` part)."""
    merged = [e for e in profile.get("merged", []) if isinstance(e, dict)]
    summary = {
        "merged": len([e for e in merged if not e.get("changed")]),
        "changed": [f"#{e.get('number')} {e.get('title', '')}" for e in merged if e.get("changed")][
            -5:
        ],
        "closed": len(profile.get("closed", [])),
        "lessons": [
            str(e.get("lesson") or "") for e in profile.get("lessons", []) if isinstance(e, dict)
        ][-8:],
    }
    store.set_part(project_key(folder), "outcomes", summary)
