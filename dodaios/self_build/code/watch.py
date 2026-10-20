"""After the pull request: CI as the judge, landing, and learning from the outcome.

For every code record with an open pull request the loop asks GitHub, on each
pass, how it stands:

* ``proving``: green CI is the proof (``attach_proof``) and the build goes on
  trial. Red CI fails it: the lesson is kept, the pull request closed and the
  branch deleted. A repository without CI is judged by the local test run
  alone once a grace period showed that no check is coming.
* ``trial``: in a repository the person opted in to landing
  (``[self_build].code_land_repos``), a green pull request is merged.
* merged by the person: ``accepted`` when merged as the loop left it,
  ``corrected`` when they changed it first; the build is kept, and the
  repository's profile and brief learn which.
* closed without merge: the branch and worktree go, the build is ``undone``
  and the profile notes it (triage stays out of a repository that keeps
  closing loop pull requests).

:func:`cleanup` is also the undo: it removes only what the loop created.
"""

from __future__ import annotations

import asyncio
from typing import Any, Final

from loguru import logger

from ..ledger import now_ms
from ..records import BuildRecord, Outcome, State
from . import brief as brief_mod
from .context import BRANCH_PREFIX, Context, has_pull, land_repos, parse_signature
from .github import PullState

#: A pull request with no check at all after this long is judged by local tests.
NO_CI_GRACE_MS: Final[int] = 15 * 60_000
#: CI still pending after this long fails the build.
CI_TIMEOUT_MS: Final[int] = 24 * 3_600_000
_RED: Final[frozenset[str]] = frozenset({"FAILURE", "ERROR"})


async def cleanup(
    ctx: Context, record: BuildRecord, *, close_pull: bool, force: bool = False
) -> None:
    """Remove the loop's own artefacts for ``record``: its open pull request (when
    ``close_pull``), its remote branch, its worktree and local branch.

    Branches are deleted only while they still point at the commit the loop
    pushed, so work the person added on top is never lost. ``force`` is for a
    run that is still the loop's own (``building``): its worktree goes even
    with uncommitted changes.
    """
    from .builder import remove_local, remove_remote

    undo = dict(record.undo)
    branch = str(undo.get("branch") or "")
    folder = str(undo.get("folder") or "")
    # Only a branch this build made itself: a name that already existed is not ours.
    if not branch.startswith(BRANCH_PREFIX) or not folder or not undo.get("created"):
        return
    session_id = str(undo.get("session_id") or "")
    if session_id:
        await _stop_thread(ctx, session_id)
    if close_pull and undo.get("pr_id"):
        api = ctx.github()
        if api is None:
            raise RuntimeError("GitHub is not connected; the pull request cannot be closed")
        state = await asyncio.to_thread(api.pull, str(undo["repo"]), int(undo["pr_number"]))
        if state.state == "MERGED":
            raise RuntimeError("the pull request is merged; revert it in the repository")
        if state.state == "OPEN":
            await asyncio.to_thread(api.close_pull, str(undo["pr_id"]))
    head = str(undo.get("head") or "")
    if undo.get("pushed"):
        await asyncio.to_thread(remove_remote, folder, branch, head)
    await asyncio.to_thread(
        remove_local, folder, str(undo.get("worktree") or ""), branch, head=head, force=force
    )


async def _stop_thread(ctx: Context, session_id: str) -> None:
    stop = getattr(ctx.runner, "stop", None)
    if stop is None:
        return
    try:
        await stop(session_id)
    except Exception:  # noqa: BLE001 - a thread that cannot be stopped ends on its own
        logger.opt(exception=True).debug("self-build code: thread {} not stopped", session_id)


async def watch(ctx: Context, record: BuildRecord) -> None:
    """One look at the pull request of ``record`` and whatever follows from it."""
    if not has_pull(record):
        return
    api = ctx.github()
    if api is None:
        return
    repo = str(record.artefact.get("repo") or "")
    number = int(record.artefact.get("number") or 0)
    pull = await asyncio.to_thread(api.pull, repo, number)
    if pull.state == "MERGED":
        await _merged(ctx, record, pull)
    elif pull.state == "CLOSED":
        await _closed(ctx, record)
    elif record.state == State.PROVING:
        await _prove(ctx, record, pull)
    elif record.state == State.TRIAL:
        await _land(ctx, record, pull)


async def _prove(ctx: Context, record: BuildRecord, pull: PullState) -> None:
    ledger = ctx.ledger
    tests = str(record.artefact.get("tests") or "local tests passed")
    age = now_ms() - int(record.artefact.get("opened_ms") or record.updated_ms)
    if pull.checks == "SUCCESS":
        await asyncio.to_thread(
            ledger.attach_proof,
            record.id,
            passed=True,
            judge="tests+ci",
            detail=f"{tests}\nCI passed on {pull.head_oid[:10]}",
        )
    elif pull.checks in _RED:
        failing = ", ".join(pull.failing) or "a check"
        await asyncio.to_thread(
            ledger.attach_proof,
            record.id,
            passed=False,
            judge="tests+ci",
            detail=f"{tests}\nCI failed: {failing}",
        )
        await _fail_after_pull(ctx, record, f"CI failed on the pull request: {failing}")
        return
    elif not pull.checks and age >= NO_CI_GRACE_MS:
        await asyncio.to_thread(
            ledger.attach_proof,
            record.id,
            passed=True,
            judge="tests",
            detail=f"{tests}\nNo CI runs on this repository; the local tests are the proof.",
        )
    elif age >= CI_TIMEOUT_MS:
        await _fail_after_pull(ctx, record, "CI did not finish within a day")
        return
    else:
        return  # CI still running
    record = await asyncio.to_thread(
        ledger.set_state, record.id, State.TRIAL, "proven; the pull request waits for review"
    )
    await _land(ctx, record, pull)


async def _land(ctx: Context, record: BuildRecord, pull: PullState) -> None:
    """Merge a green pull request, only in a repository the person opted in."""
    repo = str(record.artefact.get("repo") or "")
    if repo.lower() not in land_repos(ctx.config()) or pull.draft:
        return
    if pull.checks not in ("SUCCESS", "") or not record.proof.get("passed"):
        return
    api = ctx.github()
    if api is None:
        return
    try:
        await asyncio.to_thread(api.merge_pull, pull.id, head_oid=pull.head_oid)
    except Exception as exc:  # noqa: BLE001 - not mergeable yet (review rule, conflict): wait
        logger.info("self-build code: {} not merged yet: {}", record.signature, exc)
        return
    logger.info("self-build code: landed {} (#{})", record.signature, pull.number)


async def _merged(ctx: Context, record: BuildRecord, pull: PullState) -> None:
    ledger = ctx.ledger
    head = str(record.undo.get("head") or "")
    changed = bool(head) and pull.head_oid != head
    outcome = Outcome.CORRECTED if changed else Outcome.ACCEPTED
    if record.state == State.PROVING:
        await asyncio.to_thread(
            ledger.attach_proof,
            record.id,
            passed=True,
            judge="merged",
            detail="The person merged the pull request.",
        )
        record = await asyncio.to_thread(ledger.set_state, record.id, State.TRIAL, "merged")
    await asyncio.to_thread(ledger.record_use, record.id, outcome)
    if record.state != State.KEPT:
        note = "merged after changes by the person" if changed else "merged as built"
        await asyncio.to_thread(ledger.set_state, record.id, State.KEPT, note)
    await _learn(ctx, record, "merged", changed=changed)
    try:
        await cleanup(ctx, record, close_pull=False)
    except Exception:  # noqa: BLE001 - leftovers of a merged build are harmless
        logger.opt(exception=True).info("self-build code: cleanup after merge incomplete")


async def _closed(ctx: Context, record: BuildRecord) -> None:
    await asyncio.to_thread(ctx.ledger.record_use, record.id, Outcome.IGNORED)
    await cleanup(ctx, record, close_pull=False)
    await _learn(ctx, record, "closed")
    if record.state in (State.PROVING, State.TRIAL, State.ARCHIVED, State.KEPT):
        await asyncio.to_thread(
            ctx.ledger.set_state, record.id, State.UNDONE, "closed on GitHub without merge"
        )


async def _fail_after_pull(ctx: Context, record: BuildRecord, lesson: str) -> None:
    await cleanup(ctx, record, close_pull=True)
    parsed = parse_signature(record.signature)
    if parsed:
        await asyncio.to_thread(
            ctx.store.add_to_profile,
            parsed[0],
            "lessons",
            {"number": parsed[1], "lesson": lesson},
        )
        await _fold(ctx, record, parsed[0])
    await asyncio.to_thread(ctx.ledger.set_state, record.id, State.FAILED, lesson)


async def _learn(ctx: Context, record: BuildRecord, field: str, *, changed: bool = False) -> None:
    parsed = parse_signature(record.signature)
    if parsed is None:
        return
    repo, number = parsed
    seen = await asyncio.to_thread(ctx.store.issue, repo, number)
    issue: dict[str, Any] = (seen or {}).get("issue") or {}
    entry = {
        "number": number,
        "title": str(issue.get("title") or record.title),
        "labels": list(issue.get("labels") or []),
        "changed": changed,
    }
    await asyncio.to_thread(ctx.store.add_to_profile, repo, field, entry)
    await _fold(ctx, record, repo)


async def _fold(ctx: Context, record: BuildRecord, repo: str) -> None:
    folder = str(record.undo.get("folder") or "")
    if not folder:
        return
    profile = await asyncio.to_thread(ctx.store.profile, repo)
    await asyncio.to_thread(brief_mod.note_outcomes, ctx.store, folder, profile)
