"""What changed in the team's folder, read with git and without touching it.

A snapshot is the tree id of the whole working tree (tracked and untracked
files, ignore rules respected), written through a throwaway index so the
person's own index, refs and files stay exactly as they are. The only trace
is unreferenced objects in the repository's object store, which git's own
housekeeping removes. Two snapshots
give the diff the reviewers read, and tell whether a phase that must not
change files did.

Outside a git repository there is no snapshot: the caller says so in the
thread and the reviewers read the files themselves.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

log = logging.getLogger(__name__)

__all__ = ["Change", "GitWorkspace"]

_TIMEOUT_S = 120


@dataclass(frozen=True, slots=True)
class Change:
    files: tuple[str, ...]
    stat: str
    patch: str
    truncated: bool


def _git(cwd: str, *args: str, env: dict[str, str] | None = None) -> str | None:
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", cwd, "-c", "core.quotepath=off", *args],  # noqa: S607 - git from PATH
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_S,
            env=env,
            creationflags=NO_WINDOW_CREATIONFLAGS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("team thread: git %s failed in %s: %s", args[0] if args else "", cwd, exc)
        return None
    if done.returncode != 0:
        log.info(
            "team thread: git %s exited %s: %s",
            args[0],
            done.returncode,
            (done.stderr or "").strip()[:300],
        )
        return None
    return done.stdout


class GitWorkspace:
    """Snapshots and diffs of one folder. Every method blocks; call it off the loop."""

    def snapshot(self, cwd: str) -> str | None:
        """The tree id of the working tree as it is now, or ``None`` without git."""
        if (_git(cwd, "rev-parse", "--is-inside-work-tree") or "").strip() != "true":
            return None
        index = (_git(cwd, "rev-parse", "--git-path", "index") or "").strip()
        scratch = tempfile.mkdtemp(prefix="team-thread-index-")
        try:
            temp_index = os.path.join(scratch, "index")
            if index:
                source = Path(index) if os.path.isabs(index) else Path(cwd) / index
                if source.is_file():
                    # Start from the real index: its stat cache spares rehashing the tree.
                    shutil.copyfile(source, temp_index)
            env = {**os.environ, "GIT_INDEX_FILE": temp_index}
            if _git(cwd, "add", "-A", "--ignore-errors", env=env) is None:
                return None
            tree = (_git(cwd, "write-tree", env=env) or "").strip()
            return tree or None
        except OSError as exc:
            log.info("team thread: snapshot of %s failed: %s", cwd, exc)
            return None
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    def change(self, cwd: str, base: str, head: str, *, limit: int = 40_000) -> Change:
        """What differs between two snapshots, the patch capped at ``limit`` characters."""
        if base == head:
            return Change((), "", "", False)
        names = _git(cwd, "diff", "--name-only", base, head) or ""
        stat = _git(cwd, "diff", "--stat=120", base, head) or ""
        patch = _git(cwd, "diff", base, head) or ""
        truncated = len(patch) > limit
        return Change(
            files=tuple(line for line in names.splitlines() if line.strip()),
            stat=stat.strip(),
            patch=patch[:limit],
            truncated=truncated,
        )
