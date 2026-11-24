"""Is the running copy of the app a linked Git worktree?"""

from __future__ import annotations

from pathlib import Path

from dodaios.core.config import PROJECT_ROOT


def running_from_linked_worktree(root: Path | None = None) -> bool:
    """True when *root* (default: the running copy) is a linked Git worktree.

    In a linked worktree ``.git`` is a file (``gitdir: ...``) instead of the
    repository directory. A packaged install has no ``.git`` at all.
    """
    return ((root or PROJECT_ROOT) / ".git").is_file()
