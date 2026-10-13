"""Git for a coding workspace, addressed like every other workspace action.

A request names a workspace (or leaves it out for the visible one), never a
path: the folder comes from the workspace, so no operation can be pointed
elsewhere on the machine. Reads describe the repository; the other operations
create, put away and restore worktrees, commit, push and open a pull request.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from . import git_ops, git_overview, github_pulls, worktree_archive
from .git_ops import GitError

READ_OPS = frozenset({"state", "worktrees", "pull_requests"})
OPS = (
    "state",
    "worktrees",
    "pull_requests",
    "worktree_create",
    "worktree_archive",
    "worktree_restore",
    "commit",
    "push",
    "pull_request",
)
#: How many changed paths a spoken state answer carries.
_STATE_CHANGES = 20
#: How many pull requests one answer lists.
_PULL_REQUESTS = 15


def _state(folder: str) -> dict[str, Any]:
    info = git_ops.inspect(folder)
    if not info.git_available:
        raise GitError("Git is not installed on this machine.", code="missing")
    if not info.is_repo:
        raise GitError(f"{Path(folder).name} is not a git repository.", code="not_repo")
    changes = [
        {"path": change.path, "staged": change.index, "unstaged": change.worktree}
        for change in info.changes[:_STATE_CHANGES]
    ]
    return {
        "branch": info.branch,
        "detached": info.detached,
        "default_branch": info.default_branch,
        "upstream": info.upstream,
        "ahead": info.ahead,
        "behind": info.behind,
        "staged": info.staged,
        "unstaged": info.unstaged,
        "untracked": info.untracked,
        "conflicted": info.conflicted,
        "lines_added": info.insertions,
        "lines_removed": info.deletions,
        "changes": changes,
        "more_changes": max(0, len(info.changes) - len(changes)),
        "linked_worktree": info.is_worktree,
    }


def _worktrees(folder: str) -> dict[str, Any]:
    info = git_ops.inspect(folder)
    if not info.is_repo:
        raise GitError(f"{Path(folder).name} is not a git repository.", code="not_repo")
    return {
        "worktrees": [
            {
                "folder": tree.path,
                "branch": tree.branch,
                "main": tree.main,
                "here": tree.current,
                **({"locked": True} if tree.locked else {}),
                **({"folder_missing": True} if tree.prunable else {}),
            }
            for tree in info.worktrees
        ],
        "archived": [entry.to_dict() for entry in worktree_archive.archived(folder)],
    }


def _pull_requests(folder: str) -> dict[str, Any]:
    """The repository's open pull requests and the ones of its local branches."""
    seen = git_overview.overview(folder)
    if not seen.available:
        raise GitError(seen.reason or "This folder has no repository.", code="not_repo")
    rows: dict[int, dict[str, Any]] = {}
    for pr in [*(pr for branch in seen.branches for pr in branch.pull_requests),
               *seen.pull_requests]:
        rows.setdefault(pr.number, {
            "number": pr.number,
            "title": pr.title,
            "state": pr.state,
            "branch": pr.head,
            "into": pr.base,
            "url": pr.url,
            "checks": pr.ci.state,
            **({"failed_checks": pr.ci.failed} if pr.ci.failed else {}),
            **({"running_checks": pr.ci.running + pr.ci.pending}
               if pr.ci.running or pr.ci.pending else {}),
            **({"conflicting": True} if pr.conflicting else {}),
            **({"review": pr.review} if pr.review else {}),
            **({"merge_queue_position": pr.queue_position}
               if pr.queue_position is not None else {}),
            **({"here": True} if pr.head == seen.branch else {}),
        })
    listed = sorted(rows.values(), key=lambda row: (not row.get("here"), -row["number"]))
    return {
        "branch": seen.branch,
        "github": (
            {"connected": True, "repository": seen.github.repo}
            if seen.github.available
            else {"connected": False, "reason": seen.github.reason}
        ),
        "pull_requests": listed[:_PULL_REQUESTS],
        "more_pull_requests": max(0, len(listed) - _PULL_REQUESTS),
    }


def _perform(op: str, folder: str, args: dict[str, Any], open_folders: list[str]) -> dict[str, Any]:
    """Run one operation on the worker thread. Raises ``GitError`` with its reason."""
    if op == "state":
        return _state(folder)
    if op == "worktrees":
        return _worktrees(folder)
    if op == "pull_requests":
        return _pull_requests(folder)
    if op == "worktree_create":
        made = git_ops.prepare(
            folder, "new_worktree",
            branch=str(args.get("branch") or ""), base=str(args.get("base") or ""),
        )
        return {
            **made.to_dict(),
            "next_step": (
                "To start agents in it, call workspace-orchestrate open_workspace with this "
                "folder. Nothing runs there yet."
            ),
        }
    if op == "worktree_archive":
        entry = worktree_archive.archive(
            folder, str(args.get("worktree") or ""), open_folders=open_folders,
            drop_ignored=args.get("drop_ignored") is True,
        )
        return {
            "archived": entry.to_dict(),
            "message": (
                f"Archived {entry.branch or Path(entry.path).name}. "
                + ("Its uncommitted, non-ignored work is saved with it. "
                   if entry.uncommitted else "")
                + "The branch and its commits are untouched; worktree_restore brings it back."
            ),
        }
    if op == "worktree_restore":
        return worktree_archive.restore(folder, str(args.get("worktree") or "")).to_dict()
    if op == "commit":
        sha = git_ops.commit_all(folder, str(args.get("message") or ""))
        return {"commit": sha, "message": f"Committed as {sha}."}
    if op == "push":
        upstream = git_ops.push(folder, str(args.get("branch") or ""))
        # What GitHub is known to hold for this folder is now out of date.
        git_overview.clear_github(folder)
        return {"upstream": upstream, "message": f"Pushed to {upstream}."}
    if op == "pull_request":
        url = github_pulls.open_for_branch(
            folder,
            branch=str(args.get("branch") or ""),
            title=str(args.get("title") or ""),
            draft=args.get("draft") is True,
        )
        git_overview.clear_github(folder)
        return {"url": url, "message": "Pull request opened."}
    raise ValueError("Unknown git operation.")


async def run(orchestrator: Any, args: dict[str, Any]) -> dict[str, Any]:
    """Resolve the workspace a request names and run one git operation in its folder."""
    op = str(args.get("op") or "").strip()
    if op not in OPS:
        raise ValueError(f"op must be one of {', '.join(OPS)}.")
    graph = await asyncio.to_thread(orchestrator.graph)
    picked = orchestrator._workspace(args, graph, "")
    if isinstance(picked, dict):
        return picked
    project, workspace = picked
    target = {
        "project_id": project["id"],
        "workspace_id": workspace["id"],
        "workspace": workspace["name"],
    }
    open_folders: list[str] = []
    for session in orchestrator.registry.sessions:
        open_folders.append(session.folder)
        open_folders.extend(pane.cwd(session.folder) for pane in session.terminals)
    try:
        result = await asyncio.to_thread(_perform, op, workspace["folder"], args, open_folders)
    except GitError as exc:
        # Git's own refusal, in one sentence: nothing else happened.
        return {
            "status": "not_accepted", "success": False, "op": op,
            "code": exc.code, "reason": str(exc), **target,
        }
    return {"status": "ok", "op": op, **target, **result}


__all__ = ["OPS", "READ_OPS", "run"]
