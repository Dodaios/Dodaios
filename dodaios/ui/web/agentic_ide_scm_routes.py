"""REST routes for the Git tab's source control (``/api/agentic-ide/git/scm``).

Every route names an open workspace, never a path: the repository is the one
that workspace's folder is in, so no request can point git elsewhere on the
machine. Paths in the bodies are repository-relative. Handlers are plain
``def`` so git runs in the anyio threadpool, never on the event loop.

A failed git call answers 422 with ``{"detail": {"message", "code"}}``, the
same shape as the rest of the Git tab's routes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from dodaios.agentic_ide import scm
from dodaios.agentic_ide.git_ops import GitError
from dodaios.agentic_ide.session import get_registry

router = APIRouter(prefix="/api/agentic-ide/git/scm", tags=["agentic-ide-git"])


def _folder(workspace_id: str) -> Path:
    session = get_registry().get(workspace_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return Path(session.folder)


def _fail(exc: GitError) -> HTTPException:
    return HTTPException(status_code=422, detail={"message": str(exc), "code": exc.code})


class WorkspaceBody(BaseModel):
    workspace_id: str = Field(..., min_length=1)


class PathsBody(WorkspaceBody):
    paths: list[str] = Field(..., min_length=1, max_length=20_000)


class StageAllBody(WorkspaceBody):
    tracked_only: bool = False


class DiscardAllBody(WorkspaceBody):
    untracked: bool = Field(False, description="Also remove untracked files")


class CommitBody(WorkspaceBody):
    message: str = Field("", max_length=20_000)
    amend: bool = False
    all_changes: bool = Field(False, description="Stage every change first")
    include_untracked: bool = True
    signoff: bool = False
    no_verify: bool = False
    allow_empty: bool = False


class FetchBody(WorkspaceBody):
    remote: str = Field("", max_length=200)
    prune: bool = False
    all_remotes: bool = False


class PullBody(WorkspaceBody):
    rebase: bool = False
    remote: str = Field("", max_length=200)
    branch: str = Field("", max_length=300)


class PushBody(WorkspaceBody):
    remote: str = Field("", max_length=200)
    force: bool = False
    tags: bool = False


class SyncBody(WorkspaceBody):
    rebase: bool = False


class RemoteBody(WorkspaceBody):
    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field("", max_length=2000)


class RefBody(WorkspaceBody):
    ref: str = Field(..., min_length=1, max_length=300)


class CheckoutBody(RefBody):
    detached: bool = False


class BranchBody(WorkspaceBody):
    name: str = Field(..., min_length=1, max_length=300)
    start: str = Field("", max_length=300)
    switch: bool = True


class RenameBody(WorkspaceBody):
    name: str = Field(..., min_length=1, max_length=300)
    old: str = Field("", max_length=300)


class DeleteBranchBody(WorkspaceBody):
    name: str = Field(..., min_length=1, max_length=300)
    force: bool = False


class TagBody(WorkspaceBody):
    name: str = Field(..., min_length=1, max_length=300)
    message: str = Field("", max_length=5000)
    ref: str = Field("", max_length=300)


class StashBody(WorkspaceBody):
    message: str = Field("", max_length=2000)
    include_untracked: bool = False
    staged: bool = False


class StashRefBody(WorkspaceBody):
    ref: str = Field("", max_length=40)
    pop: bool = False


class StashDropBody(WorkspaceBody):
    ref: str = Field("", max_length=40)
    everything: bool = False


class OperationBody(WorkspaceBody):
    action: Literal["continue", "abort"]


def _ok(**extra: object) -> dict:
    return {"ok": True, **extra}


@router.get("/status", summary="Staged, unstaged, untracked and conflicting files")
def status(workspace_id: str = Query(..., min_length=1)) -> dict:
    return scm.read_status(_folder(workspace_id)).to_dict()


@router.get("/refs", summary="Local branches, remote branches and tags")
def refs(workspace_id: str = Query(..., min_length=1)) -> dict:
    try:
        return scm.list_refs(_folder(workspace_id))
    except GitError as exc:
        raise _fail(exc) from exc


@router.get("/graph", summary="One page of the commit graph")
def graph(
    workspace_id: str = Query(..., min_length=1),
    scope: Literal["auto", "all", "current"] = "auto",
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=scm.MAX_GRAPH_PAGE),
) -> dict:
    try:
        return scm.graph(_folder(workspace_id), scope=scope, skip=skip, limit=limit)
    except GitError as exc:
        raise _fail(exc) from exc


@router.get("/commit", summary="A commit's message and changed files")
def commit_details(
    workspace_id: str = Query(..., min_length=1), commit: str = Query(..., min_length=4)
) -> dict:
    try:
        return scm.commit_details(_folder(workspace_id), commit)
    except GitError as exc:
        raise _fail(exc) from exc


@router.get("/commit/file", summary="Both sides of one file in a commit")
def commit_file(
    workspace_id: str = Query(..., min_length=1),
    commit: str = Query(..., min_length=4),
    path: str = Query(..., min_length=1),
    original: str = "",
) -> dict:
    try:
        return scm.commit_file_diff(_folder(workspace_id), commit, path, original=original)
    except GitError as exc:
        raise _fail(exc) from exc


@router.get("/stashes", summary="The stash list")
def stashes(workspace_id: str = Query(..., min_length=1)) -> dict:
    try:
        return {"stashes": scm.list_stashes(_folder(workspace_id))}
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/stage", summary="Stage files")
def stage(body: PathsBody) -> dict:
    try:
        scm.stage(_folder(body.workspace_id), body.paths)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/stage-all", summary="Stage every change")
def stage_all(body: StageAllBody) -> dict:
    try:
        scm.stage_all(_folder(body.workspace_id), tracked_only=body.tracked_only)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/unstage", summary="Unstage files")
def unstage(body: PathsBody) -> dict:
    try:
        scm.unstage(_folder(body.workspace_id), body.paths)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/unstage-all", summary="Unstage every file")
def unstage_all(body: WorkspaceBody) -> dict:
    try:
        scm.unstage_all(_folder(body.workspace_id))
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/discard", summary="Discard the working-tree changes of files")
def discard(body: PathsBody) -> dict:
    try:
        scm.discard(_folder(body.workspace_id), body.paths)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/discard-all", summary="Discard every working-tree change")
def discard_all(body: DiscardAllBody) -> dict:
    try:
        scm.discard_all(_folder(body.workspace_id), untracked=body.untracked)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/ignore", summary="Add files to .gitignore")
def ignore(body: PathsBody) -> dict:
    try:
        return _ok(file=scm.ignore(_folder(body.workspace_id), body.paths))
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/commit", summary="Commit the staged changes")
def commit(body: CommitBody) -> dict:
    try:
        sha = scm.commit(
            _folder(body.workspace_id),
            body.message,
            amend=body.amend,
            all_changes=body.all_changes,
            include_untracked=body.include_untracked,
            signoff=body.signoff,
            no_verify=body.no_verify,
            allow_empty=body.allow_empty,
        )
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok(commit=sha)


@router.post("/undo-commit", summary="Undo the last commit, keeping its changes staged")
def undo_commit(body: WorkspaceBody) -> dict:
    try:
        return _ok(message=scm.undo_last_commit(_folder(body.workspace_id)))
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/operation", summary="Continue or abort a merge, rebase, cherry-pick or revert")
def operation(body: OperationBody) -> dict:
    try:
        if body.action == "continue":
            scm.continue_operation(_folder(body.workspace_id))
        else:
            scm.abort_operation(_folder(body.workspace_id))
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/fetch", summary="Fetch from the remotes")
def fetch(body: FetchBody) -> dict:
    try:
        scm.fetch(
            _folder(body.workspace_id),
            remote=body.remote,
            prune=body.prune,
            all_remotes=body.all_remotes,
        )
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/pull", summary="Pull into the current branch")
def pull(body: PullBody) -> dict:
    try:
        scm.pull(
            _folder(body.workspace_id), rebase=body.rebase, remote=body.remote, branch=body.branch
        )
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/push", summary="Push the current branch")
def push(body: PushBody) -> dict:
    try:
        upstream = scm.push(
            _folder(body.workspace_id), remote=body.remote, force=body.force, tags=body.tags
        )
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok(upstream=upstream)


@router.post("/push-tags", summary="Push every tag")
def push_tags(body: PushBody) -> dict:
    try:
        scm.push_tags(_folder(body.workspace_id), remote=body.remote)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/sync", summary="Pull, then push")
def sync(body: SyncBody) -> dict:
    try:
        scm.sync(_folder(body.workspace_id), rebase=body.rebase)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/remote/add", summary="Add a remote")
def add_remote(body: RemoteBody) -> dict:
    try:
        scm.add_remote(_folder(body.workspace_id), body.name, body.url)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/remote/remove", summary="Remove a remote")
def remove_remote(body: RemoteBody) -> dict:
    try:
        scm.remove_remote(_folder(body.workspace_id), body.name)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/checkout", summary="Check out a branch, remote branch, tag or commit")
def checkout(body: CheckoutBody) -> dict:
    try:
        return _ok(
            branch=scm.checkout(_folder(body.workspace_id), body.ref, detached=body.detached)
        )
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/branch/create", summary="Create a branch")
def create_branch(body: BranchBody) -> dict:
    try:
        name = scm.create_branch(
            _folder(body.workspace_id), body.name, start=body.start, switch=body.switch
        )
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok(branch=name)


@router.post("/branch/rename", summary="Rename a branch")
def rename_branch(body: RenameBody) -> dict:
    try:
        return _ok(branch=scm.rename_branch(_folder(body.workspace_id), body.name, old=body.old))
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/branch/delete", summary="Delete a local branch")
def delete_branch(body: DeleteBranchBody) -> dict:
    try:
        scm.delete_branch(_folder(body.workspace_id), body.name, force=body.force)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/merge", summary="Merge a branch into the current one")
def merge(body: RefBody) -> dict:
    try:
        return _ok(result=scm.merge(_folder(body.workspace_id), body.ref))
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/rebase", summary="Rebase the current branch onto another")
def rebase(body: RefBody) -> dict:
    try:
        return _ok(result=scm.rebase(_folder(body.workspace_id), body.ref))
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/cherry-pick", summary="Apply one commit onto the current branch")
def cherry_pick(body: RefBody) -> dict:
    try:
        return _ok(result=scm.cherry_pick(_folder(body.workspace_id), body.ref))
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/revert", summary="Commit the inverse of one commit")
def revert(body: RefBody) -> dict:
    try:
        return _ok(result=scm.revert(_folder(body.workspace_id), body.ref))
    except GitError as exc:
        raise _fail(exc) from exc


@router.post("/tag/create", summary="Create a tag")
def create_tag(body: TagBody) -> dict:
    try:
        scm.create_tag(_folder(body.workspace_id), body.name, message=body.message, ref=body.ref)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/tag/delete", summary="Delete a tag")
def delete_tag(body: TagBody) -> dict:
    try:
        scm.delete_tag(_folder(body.workspace_id), body.name)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/stash", summary="Stash the working-tree changes")
def stash(body: StashBody) -> dict:
    try:
        scm.stash(
            _folder(body.workspace_id),
            message=body.message,
            include_untracked=body.include_untracked,
            staged=body.staged,
        )
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/stash/apply", summary="Apply or pop a stash")
def stash_apply(body: StashRefBody) -> dict:
    try:
        scm.stash_apply(_folder(body.workspace_id), body.ref, pop=body.pop)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


@router.post("/stash/drop", summary="Drop a stash, or every stash")
def stash_drop(body: StashDropBody) -> dict:
    try:
        scm.stash_drop(_folder(body.workspace_id), body.ref, everything=body.everything)
    except GitError as exc:
        raise _fail(exc) from exc
    return _ok()


class FollowMainBody(BaseModel):
    enabled: bool


def _follow_status() -> dict:
    from dodaios.core.main_follow import FollowStatus, get_follower

    follower = get_follower()
    if follower is None:
        status = FollowStatus(reason="This app instance does not follow main.")
        try:
            from dodaios.core.config import load_config

            status.enabled = bool(getattr(load_config().agentic_ide, "follow_main", False))
        except Exception as exc:  # noqa: BLE001 -- unreadable config: the toggle shows off
            status.reason = f"The configuration could not be read: {exc}"
        return status.to_dict()
    return follower.status.to_dict()


@router.get("/follow-main", summary="Does this app keep itself on the newest main?")
def follow_main_status() -> dict:
    return _follow_status()


@router.post(
    "/follow-main/clear-lock", summary="Remove a stale git lock that blocks following main"
)
def clear_follow_lock() -> dict:
    """Only a lock older than ten minutes is removed; a younger one answers 409."""
    from dodaios.core.main_follow import get_follower

    follower = get_follower()
    if follower is None:
        raise HTTPException(status_code=404, detail="This app instance does not follow main.")
    if not follower.clear_stale_lock():
        raise HTTPException(status_code=409, detail="The git lock is too recent to be stale.")
    return _follow_status()


@router.put("/follow-main", summary="Keep this app on the newest main, or stop")
def set_follow_main(body: FollowMainBody) -> dict:
    """Saved in ``[agentic_ide] follow_main``; the follower looks again at once."""
    from dodaios.core import config_writer
    from dodaios.core.main_follow import get_follower

    config_writer.set_agentic_ide_follow_main(body.enabled)
    follower = get_follower()
    if follower is not None:
        follower.status.enabled = body.enabled
        follower.poke()
    return _follow_status()


@router.get("/session-file", summary="Both sides of one file an agent session changed")
def session_file(
    workspace_id: str = Query(..., min_length=1),
    pane: str = Query(..., min_length=1),
    path: str = Query(..., min_length=1),
    base: str = Query(..., min_length=7, max_length=64),
) -> dict:
    """The file at the commit before the session's first change, and as it is now.

    The pane's own worktree is read when it has one, like its review list.
    """
    session = get_registry().get(workspace_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    term = next((entry for entry in session.terminals if entry.name == pane), None)
    if term is None:
        raise HTTPException(status_code=404, detail="Terminal not found.")
    try:
        return scm.session_file_diff(term.folder or session.folder, path, base)
    except GitError as exc:
        raise _fail(exc) from exc
