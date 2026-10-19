"""Places the managed AGENTS.md marker file in a mission worktree and hides it from git."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

logger = logging.getLogger(__name__)

__all__ = ["materialize_worker_contract"]


_STUB_HEADER = "<!-- managed by Dodaios Mission-Manager — do not edit -->"


def _agents_md(mission_id: str) -> str:
    """AGENTS.md placed in each mission worktree; the contract lives in the task message."""
    return (
        f"{_STUB_HEADER}\n"
        f"# Dodaios mission `{mission_id}`\n\n"
        "Runtime file, not part of the project. Instructions are in the task message.\n"
    )


# The file sits in the worktree root (claude --print reads AGENTS.md from its
# cwd) and in the per-worktree ``.git/info/exclude`` so it never shows up in
# the diff the critic reviews.


def materialize_worker_contract(worktree: Path, mission_id: str) -> Path:
    """Write ``AGENTS.md`` into ``worktree`` and gitignore it locally.

    Called by ``Kontrollierer`` right after ``WorktreeManager.create()``
    returns a fresh per-task worktree.

    The path is added to the worktree's *local* exclude file
    (``<gitdir>/info/exclude``) -- not to ``.gitignore``, which would be
    tracked and pollute the diff. The exclude file is per-worktree
    (each worktree's ``.git`` is a file pointing to its own gitdir
    under ``<main>/.git/worktrees/<name>/``), so other worktrees and the
    main repo are not affected.

    Best-effort: filesystem / git errors are logged at WARNING but do
    NOT propagate; a mission start never blocks on this file.

    Args:
        worktree: Path returned by ``WorktreeManager.create()``.
        mission_id: Mission-Manager id -- embedded into AGENTS.md header.

    Returns:
        Path to the materialised ``AGENTS.md`` (even if the gitignore
        step failed -- the file is on disk either way).
    """
    if not worktree.is_dir():
        # If the worktree path does not exist yet, callers are misusing
        # this helper. Raise rather than silently dropping the file
        # somewhere it will never be read.
        raise FileNotFoundError(
            f"materialize_worker_contract: worktree does not exist: {worktree}"
        )
    if not mission_id or not mission_id.strip():
        raise ValueError("materialize_worker_contract: mission_id required")

    agents_path = worktree / "AGENTS.md"
    try:
        agents_path.write_text(
            _agents_md(mission_id), encoding="utf-8", newline="\n",
        )
    except OSError as exc:
        logger.warning(
            "materialize_worker_contract: write %s failed: %s",
            agents_path, exc,
        )
        return agents_path

    # Resolve the worktree's gitdir so we can write the exclude file
    # without affecting the main repo. ``git rev-parse --git-dir`` from
    # within the worktree returns the absolute path to the per-worktree
    # gitdir (e.g. ``<main>/.git/worktrees/<name>/``).
    try:
        proc = subprocess.run(  # noqa: S603 - no shell, args controlled
            ["git", "rev-parse", "--git-dir"],
            cwd=str(worktree),
            check=True,
            capture_output=True,
            text=True,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
        gitdir = Path(proc.stdout.strip())
        if not gitdir.is_absolute():
            gitdir = (worktree / gitdir).resolve()
    except (subprocess.CalledProcessError, OSError) as exc:
        logger.warning(
            "materialize_worker_contract: git rev-parse failed in %s: %s",
            worktree, exc,
        )
        return agents_path

    info_dir = gitdir / "info"
    exclude_path = info_dir / "exclude"
    try:
        info_dir.mkdir(parents=True, exist_ok=True)
        existing = ""
        if exclude_path.exists():
            existing = exclude_path.read_text(encoding="utf-8")
        # Idempotent: only append if the marker line is not already in.
        # We use an exact match on the entry so a future rename here
        # would not silently leave the old entry stale.
        marker = "AGENTS.md"
        if marker not in existing.splitlines():
            sep = "" if existing.endswith("\n") or not existing else "\n"
            exclude_path.write_text(
                f"{existing}{sep}{marker}\n", encoding="utf-8",
            )
    except OSError as exc:
        logger.warning(
            "materialize_worker_contract: exclude write %s failed: %s",
            exclude_path, exc,
        )

    return agents_path
