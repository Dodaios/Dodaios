"""Per-task git worktree manager (ADR-0009 section 3).

Layout: ``<repo_parent>/jarvis-agent-outputs/<ts>__<mission>__<uuid>/tasks/
<NN>__<task>/workspace/``; branch ``agent/<task>-<uuid>``. Paths are capped at
200 chars (MAX_PATH margin).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

logger = logging.getLogger(__name__)

# Worktree root path cap; files inside need ~60 more chars to stay under MAX_PATH.
_MAX_WORKTREE_PATH_LEN = 200

_SLUG_RE = re.compile(r"[^a-z0-9]+")

# Sidecar in the TASK dir (outside the diff) holding the worktree's BASE commit
# SHA; diffing against it keeps files a worker ``git commit``s.
BASE_SHA_SIDECAR: str = ".mission_base_sha"


class SourceCheckoutUnavailableError(RuntimeError):
    """The installed application tree is not a usable source checkout.

    Lean missions never raise it.
    """

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        super().__init__(
            "This Dodaios-Agent task requires the Dodaios source "
            "checkout, but this installation only contains application "
            "files without Git history. Repository-independent tasks remain "
            "available in isolated workspaces."
        )


def read_worktree_base_sha(workspace: Path) -> str | None:
    """Return the recorded base commit SHA for a worktree, or ``None`` if absent/unreadable."""
    try:
        raw = (workspace.parent / BASE_SHA_SIDECAR).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return raw if re.fullmatch(r"[0-9a-fA-F]{7,40}", raw) else None

# Run-dir name shape ``<ts>__<slug>__<8-hex>``. Only these transient dirs are
# swept; persistent ``mission_<id>`` archives share the root but hold deliverables.
_RUN_DIR_RE = re.compile(r"^\d{8}T\d{6}__.+__[0-9a-f]{8}$")

# Regenerable dependency/cache trees, never a deliverable (a fresh ``npm install``
# can blow the 10 s ``git add -A`` cap). Build-output dirs may be deliverables: not listed.
_DEPENDENCY_EXCLUDE_DIRS: tuple[str, ...] = (
    "node_modules/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".pnpm-store/",
    ".yarn/cache/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
)


def _slugify(value: str) -> str:
    """Lowercase, non-alphanum -> '-', trimmed."""
    out = _SLUG_RE.sub("-", value.lower()).strip("-")
    return out or "x"


def resolve_outputs_root(repo_root: Path) -> Path:
    """Return the mission outputs root (not created).

    ``JARVIS_ISOLATION_ROOT``, ``JARVIS_DATA_DIR``, else ``<repo_root>.parent/
    jarvis-agent-outputs/`` (legacy ``sub-agents-outputs/`` if only that exists).
    """
    explicit_root = os.environ.get("JARVIS_ISOLATION_ROOT", "").strip()
    if explicit_root:
        return Path(explicit_root).expanduser().resolve()

    data_root = os.environ.get("JARVIS_DATA_DIR", "").strip()
    if data_root:
        return Path(data_root).expanduser().resolve() / "jarvis-agent-outputs"

    parent = repo_root.resolve().parent
    new_dir = parent / "jarvis-agent-outputs"
    old_dir = parent / "sub-agents-outputs"
    if not new_dir.exists() and old_dir.exists():
        return old_dir  # back-compat: keep existing missions accessible
    return new_dir


def resolve_readable_outputs_roots(repo_root: Path) -> tuple[Path, ...]:
    """Return output roots that may hold mission history, primary first.

    Adds the legacy sibling unless an explicit root is set.
    """
    primary = resolve_outputs_root(repo_root)
    if os.environ.get("JARVIS_ISOLATION_ROOT", "").strip():
        return (primary,)
    if os.environ.get("JARVIS_DATA_DIR", "").strip():
        return (primary,)

    legacy = repo_root.resolve().parent / "sub-agents-outputs"
    if legacy.is_dir() and legacy != primary:
        return (primary, legacy)
    return (primary,)


class WorktreeManager:
    """Manages `git worktree add/remove` for worker tasks (synchronous, not thread-safe)."""

    def __init__(
        self,
        *,
        repo_root: Path,
        outputs_root: Path | None = None,
    ) -> None:
        """``repo_root``: main repo; ``outputs_root``: optional outputs override."""
        self._repo_root = repo_root.resolve()
        self._outputs_root = (
            outputs_root.resolve()
            if outputs_root is not None
            else resolve_outputs_root(self._repo_root)
        )


    def create(
        self,
        *,
        mission_slug: str,
        task_id: str,
        base_branch: str = "main",
        needs_repo: bool = True,
    ) -> Path:
        """Create a new workspace and return the `workspace/` path.

        ``needs_repo=False`` makes a LEAN repo (``git init`` plus one empty
        commit, no host files); both modes have a resolvable HEAD so diff capture
        works alike. Raises ``ValueError`` (path over 200 chars),
        ``SourceCheckoutUnavailableError`` or ``subprocess.CalledProcessError``.
        """
        mission_part = _slugify(mission_slug)
        task_part = _slugify(task_id)
        ts = time.strftime("%Y%m%dT%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]

        run_dir_name = f"{ts}__{mission_part}__{short_uuid}"
        task_dir_name = (
            task_part
            if task_part.startswith(tuple("0123456789"))
            else f"01__{task_part}"
        )

        workspace = (
            self._outputs_root / run_dir_name / "tasks" / task_dir_name / "workspace"
        )

        # Check capability first so frozen installs report the missing checkout.
        if needs_repo:
            self._require_source_checkout()

        if len(str(workspace)) > _MAX_WORKTREE_PATH_LEN:
            raise ValueError(
                f"Worktree path is too long ({len(str(workspace))} > "
                f"{_MAX_WORKTREE_PATH_LEN}): {workspace}"
            )

        if not needs_repo:
            workspace.parent.mkdir(parents=True, exist_ok=True)
            return self._create_lean(workspace)

        workspace.parent.mkdir(parents=True, exist_ok=True)

        branch_name = f"agent/{task_part}-{short_uuid}"

        cmd = [
            "git",
            "worktree",
            "add",
            "-b",
            branch_name,
            str(workspace),
            base_branch,
        ]
        logger.info("WorktreeManager.create: %s", " ".join(cmd))
        self._run_git(cmd)

        self._write_base_sha(workspace)
        return workspace

    # Explicit identity: a fresh ``git init`` has none.
    _LEAN_COMMIT_NAME = "Dodaios"
    _LEAN_COMMIT_EMAIL = "noreply@personal-jarvis.local"

    def _create_lean(self, workspace: Path) -> Path:
        """Create a lean workspace: a standalone repo with one empty commit so ``HEAD`` exists."""
        workspace.mkdir(parents=True, exist_ok=True)
        logger.info("WorktreeManager.create (lean): git init at %s", workspace)
        self._run_git_in(["git", "init", "-b", "main", str(workspace)], cwd=workspace)
        self._run_git_in(
            [
                "git",
                "-c",
                f"user.name={self._LEAN_COMMIT_NAME}",
                "-c",
                f"user.email={self._LEAN_COMMIT_EMAIL}",
                "commit",
                "--allow-empty",
                "-m",
                "lean-workspace-init",
            ],
            cwd=workspace,
        )
        # Lean only: a full worktree's ``.git`` is a FILE and shares the host exclude.
        self._write_dependency_excludes(workspace)
        self._write_base_sha(workspace)
        return workspace

    def _require_source_checkout(self) -> None:
        """Raise early unless ``repo_root`` is a real Git working tree.

        ``.git`` may be a directory or a linked-worktree file.
        """
        if shutil.which("git") is None:
            raise FileNotFoundError(2, "Git executable was not found", "git")

        if not (self._repo_root / ".git").exists():
            raise SourceCheckoutUnavailableError(self._repo_root)

        try:
            result = self._run_git(["git", "rev-parse", "--show-toplevel"])
        except subprocess.CalledProcessError as exc:
            raise SourceCheckoutUnavailableError(self._repo_root) from exc

        raw_top = (result.stdout or "").strip()
        try:
            top = Path(raw_top).resolve(strict=False)
        except OSError as exc:
            raise SourceCheckoutUnavailableError(self._repo_root) from exc
        if not raw_top or top != self._repo_root:
            raise SourceCheckoutUnavailableError(self._repo_root)

    def _write_base_sha(self, workspace: Path) -> None:
        """Persist the base commit SHA beside (not inside) the tree; best-effort."""
        try:
            r = self._run_git_in(["git", "rev-parse", "HEAD"], cwd=workspace)
            sha = (r.stdout or "").strip()
            if sha:
                (workspace.parent / BASE_SHA_SIDECAR).write_text(
                    sha, encoding="utf-8"
                )
        except (subprocess.CalledProcessError, OSError) as exc:
            logger.warning(
                "could not record base SHA for %s: %s — committed deliverables "
                "may not be captured for this task", workspace, exc,
            )

    def _write_dependency_excludes(self, workspace: Path) -> None:
        """Append `_DEPENDENCY_EXCLUDE_DIRS` to the lean repo's exclude file."""
        exclude_file = workspace / ".git" / "info" / "exclude"
        try:
            exclude_file.parent.mkdir(parents=True, exist_ok=True)
            with exclude_file.open("a", encoding="utf-8") as fh:
                fh.write(
                    "\n# Dodaios: regenerable dependency/cache trees "
                    "(keeps `git add -A` cheap; never a deliverable)\n"
                )
                fh.write("\n".join(_DEPENDENCY_EXCLUDE_DIRS) + "\n")
        except OSError as exc:
            logger.warning(
                "could not write dependency excludes to %s: %s",
                exclude_file, exc,
            )

    # Backoff for the Windows file-handle race in `git worktree remove`.
    _REMOVE_RETRY_DELAYS_S: tuple[float, ...] = (0.05, 0.1, 0.2)

    def remove(self, path: Path, *, force: bool = False) -> None:
        """Remove a worktree via `git worktree remove`.

        Retries absorb Windows handle races; with ``force`` the last resort is
        ``rmtree``. A lean workspace (``.git`` a directory) is not a registered
        worktree, so its tree is removed directly.
        """
        if self._is_lean_workspace(path):
            self._remove_lean(path)
            return

        cmd = ["git", "worktree", "remove"]
        if force:
            cmd.append("--force")
        cmd.append(str(path))
        logger.info("WorktreeManager.remove: %s", " ".join(cmd))

        last_exc: subprocess.CalledProcessError | None = None
        attempts = (None,) + self._REMOVE_RETRY_DELAYS_S  # 1 initial + 3 retries
        for idx, delay in enumerate(attempts):
            if delay is not None:
                time.sleep(delay)
                logger.debug(
                    "WorktreeManager.remove retry %d (after %.0fms): %s",
                    idx, delay * 1000.0, path,
                )
            try:
                self._run_git(cmd)
                return  # success
            except subprocess.CalledProcessError as exc:
                last_exc = exc
                continue

        if force:
            logger.warning(
                "git worktree remove failed after %d attempts "
                "(last exit=%s) — manual rmtree for %s",
                len(attempts),
                last_exc.returncode if last_exc else "?",
                path,
            )
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)
            return
        assert last_exc is not None
        raise last_exc

    def prune_orphans(self) -> None:
        """Call `git worktree prune` to remove stale entries."""
        cmd = ["git", "worktree", "prune"]
        logger.info("WorktreeManager.prune_orphans: %s", " ".join(cmd))
        self._run_git(cmd)

    # Boot-time defense against leaked worktree dirs.
    def prune_and_sweep_leaked(
        self, *, max_age_hours: float = 6.0,
    ) -> dict[str, int]:
        """Prune git's worktree state, then remove stale leaked run-dirs.

        Run-dirs older than ``max_age_hours`` that no live worktree claims are
        removed. Best-effort: failures are logged and counted. Returns a report.
        """
        report = {"pruned": 0, "swept_run_dirs": 0, "errors": 0}
        # No git on PATH: no worktrees exist; skip quietly.
        if shutil.which("git") is None:
            logger.info(
                "WorktreeManager.prune_and_sweep_leaked: git not on PATH — "
                "worktree sweep skipped (no git means no worktrees can exist here)."
            )
            report["skipped_no_git"] = 1
            return report
        has_source_checkout = (self._repo_root / ".git").exists()
        if has_source_checkout:
            try:
                self.prune_orphans()
                report["pruned"] = 1
            # Best-effort: OSError (git vanished) and non-zero exit must not escape.
            except (subprocess.CalledProcessError, OSError) as exc:
                logger.warning("prune_and_sweep_leaked: prune failed: %s", exc)
                report["errors"] += 1
        else:
            # Frozen/container installs have no host worktree registry.
            logger.info(
                "WorktreeManager.prune_and_sweep_leaked: source checkout "
                "unavailable — host worktree registry skipped"
            )
            report["skipped_no_source_checkout"] = 1

        if not self._outputs_root.is_dir():
            return report

        # Paths git currently considers a worktree (``worktree <path>`` lines).
        active_paths: set[Path] = set()
        if has_source_checkout:
            try:
                out = self._run_git(["git", "worktree", "list", "--porcelain"])
                for line in out.stdout.splitlines():
                    if line.startswith("worktree "):
                        p = Path(line[len("worktree "):].strip()).resolve()
                        active_paths.add(p)
                        # Layout: outputs_root/<run-dir>/tasks/<task-id>/workspace.
                        if p.parent.parent.parent.parent == self._outputs_root:
                            active_paths.add(p.parent.parent.parent)
            except (subprocess.CalledProcessError, OSError) as exc:
                logger.warning(
                    "prune_and_sweep_leaked: worktree list failed: %s", exc,
                )
                report["errors"] += 1
                return report

        cutoff = time.time() - max_age_hours * 3600.0
        for child in self._outputs_root.iterdir():
            if not child.is_dir():
                continue
            # Only transient run-dirs; never the persistent ``mission_<id>`` archives.
            if not _RUN_DIR_RE.match(child.name):
                continue
            try:
                age = child.stat().st_mtime
            except OSError:
                continue
            if age >= cutoff:
                continue  # young enough -- could still be in flight
            resolved = child.resolve()
            if resolved in active_paths:
                continue  # git still claims it -- skip
            # Cross-check: is any active-worktree path INSIDE this run-dir?
            if any(
                str(ap).startswith(str(resolved) + ("\\" if "\\" in str(ap) else "/"))
                for ap in active_paths
            ):
                continue
            logger.info(
                "prune_and_sweep_leaked: removing stale run-dir %s "
                "(age_hours=%.1f, threshold=%.1f)",
                child, (time.time() - age) / 3600.0, max_age_hours,
            )
            try:
                # ``onerror`` clears git's read-only bits; else re-swept every boot.
                shutil.rmtree(child, onerror=self._on_rmtree_error)
                # onerror swallows failures; treat partial removal as still-stale.
                if child.exists():
                    logger.warning(
                        "prune_and_sweep_leaked: partial removal of %s "
                        "(handles still held by another process)", child,
                    )
                    report["errors"] += 1
                else:
                    report["swept_run_dirs"] += 1
            except OSError as exc:
                logger.warning(
                    "prune_and_sweep_leaked: rmtree %s failed: %s",
                    child, exc,
                )
                report["errors"] += 1

        return report


    @staticmethod
    def _is_lean_workspace(path: Path) -> bool:
        """True for a lean (``.git`` directory) workspace; a linked worktree has a ``.git`` FILE."""
        git_path = path / ".git"
        if git_path.is_dir():
            return True
        if git_path.is_file():
            return False
        # No `.git` at all → not a registered worktree; safe to rmtree.
        return True

    @staticmethod
    def _on_rmtree_error(
        func: Callable[..., object], target: str, _exc_info: object
    ) -> None:
        """``rmtree`` onerror handler: clear git's read-only bit and retry once."""
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass

    @classmethod
    def _remove_lean(cls, path: Path) -> None:
        """Tear down a lean workspace with ``rmtree`` (no git call); never raises."""
        logger.info("WorktreeManager.remove (lean rmtree): %s", path)
        if path.exists():
            shutil.rmtree(path, onerror=cls._on_rmtree_error)
            if path.exists():
                logger.warning(
                    "lean workspace partial removal (handles held): %s", path
                )

    def _run_git_in(
        self, cmd: list[str], *, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        """Like :meth:`_run_git` but with ``cwd`` set (lean init/commit run inside the new repo)."""
        if cmd and cmd[0] == "git":
            patched = ["git", "-c", "core.longpaths=true", *cmd[1:]]
        else:
            patched = list(cmd)
        try:
            return subprocess.run(  # noqa: S603 — no shell=True, args controlled
                patched,
                cwd=str(cwd),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW_CREATIONFLAGS,
            )
        except subprocess.CalledProcessError as exc:
            logger.error(
                "git command failed (exit=%s): %s\nstderr: %s\nstdout: %s",
                exc.returncode,
                " ".join(patched),
                (exc.stderr or "").strip(),
                (exc.stdout or "").strip(),
            )
            raise

    def _run_git(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Synchronous git call, cwd=repo_root, no shell=True.

        Injects ``-c core.longpaths=true`` so deep paths do not fail on Windows,
        and logs git's output on failure. A missing ``git`` raises
        ``FileNotFoundError``/``OSError`` unmodified; the caller reports it (AP-23).
        """
        if cmd and cmd[0] == "git":
            patched = ["git", "-c", "core.longpaths=true", *cmd[1:]]
        else:
            patched = list(cmd)
        try:
            return subprocess.run(  # noqa: S603 — no shell=True, args controlled
                patched,
                cwd=self._repo_root,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW_CREATIONFLAGS,
            )
        except subprocess.CalledProcessError as exc:
            logger.error(
                "git command failed (exit=%s): %s\nstderr: %s\nstdout: %s",
                exc.returncode,
                " ".join(patched),
                (exc.stderr or "").strip(),
                (exc.stdout or "").strip(),
            )
            raise
