"""Build one code case: worktree, plan, coding run, judge, pull request.

Called by the loop for a ``Kind.CODE`` record in ``building``. Before each step
the record's undo payload names what the step is about to create, and after
it what was created, so an undo, a pause or a restart at any point knows
exactly what exists:

1. a fresh worktree and branch (``dodaios/issue-<n>-...``) from the remote
   default branch, inside the repository (``<repo>/.worktrees/``); a branch of
   that name that already exists here or on GitHub stops the build;
2. at most one cheap planning call; ``large`` stops here;
3. a headless coding thread on a subscription CLI in that worktree;
4. the judge: nothing protected was touched, the tests pass;
5. push the branch (only when ``origin`` fetches from and pushes to the
   repository) and open a pull request that closes the issue, draft unless the
   person opted the repository in to landing. The record moves to
   ``proving``; ``watch`` waits for CI.

A failure records the lesson in the repository's profile, removes what the
run created and moves the record to ``failed``. A pause puts the case back in
the queue instead (nothing is lost); an undo leaves the state to the undo.
No pull request is left behind by a failed build.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Final

from loguru import logger

from ..ledger import now_ms
from ..records import BuildRecord, State
from . import brief as brief_mod
from . import gitcmd, judge
from .context import BRANCH_PREFIX, Context, branch_name, land_repos, parse_signature
from .github import Issue
from .planner import Plan
from .runner import RunResult

_SUMMARY_CHARS: Final[int] = 2_500
_FOOTER: Final[str] = (
    "Built by Dodaios on its own initiative from issue #{number} (self-build `{build_id}`). "
    'Undo it in Dodaios under "Built for you", or close this pull request.'
)
#: Untracked output a test run leaves behind, never the person's work.
_JUNK: Final[tuple[str, ...]] = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".coverage",
)
#: A failure note with this prefix means the case never ran; intake may offer it again.
NOT_RUN: Final[str] = "not run: "


class BuildError(RuntimeError):
    """A step failed; the message is the lesson the profile keeps."""


class Stopped(BuildError):
    """The build was undone (``requeue=False``) or the loop paused (``requeue=True``)."""

    def __init__(self, message: str, *, requeue: bool) -> None:
        super().__init__(message)
        self.requeue = requeue


class Obsolete(BuildError):
    """The issue no longer qualifies; nothing was built and nothing is learned."""


# ------------------------------------------------------------------ git steps


def make_worktree(folder: str, branch: str, base_branch: str) -> dict[str, str]:
    """A fresh worktree on a NEW ``branch`` from ``origin/<base_branch>``."""
    from dodaios.agentic_ide import git_ops

    root = Path(folder)
    if gitcmd.git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], root).ok:
        raise BuildError(f"the branch {branch} already exists here")
    remote = gitcmd.git(
        ["ls-remote", "--exit-code", "--heads", "origin", branch],
        root,
        timeout=gitcmd.NETWORK_TIMEOUT_S,
    )
    if remote.ok:
        raise BuildError(f"the branch {branch} already exists on GitHub")
    if remote.code != 2:  # 2 = no such branch; anything else = origin unreachable
        raise BuildError("origin could not be reached")
    fetch = gitcmd.git(["fetch", "origin", base_branch], root, timeout=gitcmd.NETWORK_TIMEOUT_S)
    if not fetch.ok:
        raise BuildError(f"the default branch {base_branch} could not be fetched")
    base_sha = gitcmd.out(["rev-parse", f"origin/{base_branch}^{{commit}}"], root)
    if not base_sha:
        raise BuildError(f"the default branch {base_branch} could not be read")
    try:
        prepared = git_ops.prepare(root, "new_worktree", branch=branch, base=base_sha)
    except git_ops.GitError as exc:  # re-raised as the build's lesson
        raise BuildError(f"no worktree: {exc}") from exc
    return {"worktree": prepared.folder, "base_sha": base_sha, "base": base_branch}


def planned_worktree(folder: str, branch: str) -> str:
    from dodaios.agentic_ide import git_ops

    return str(git_ops.worktree_path(Path(folder), branch))


def collect(worktree: str, branch: str, base_sha: str, message: str) -> list[str]:
    """Commit whatever the agent left uncommitted; the files changed since the base."""
    root = Path(worktree)
    current = gitcmd.out(["rev-parse", "--abbrev-ref", "HEAD"], root)
    if current != branch:
        raise BuildError(f"the coding agent left the branch (now on {current or 'nothing'})")
    gitcmd.git(["add", "--all"], root)
    if not gitcmd.git(["diff", "--cached", "--quiet"], root).ok:
        done = gitcmd.git(["commit", "-m", message], root)
        if not done.ok:
            raise BuildError(f"the change could not be committed: {done.tail(300)}")
    # "--": git would otherwise also stat the range as a path, which fails on
    # Windows once the worktree path is deep ("Filename too long").
    listing = gitcmd.git(["diff", "--name-only", f"{base_sha}..HEAD", "--"], root)
    if not listing.ok:
        raise BuildError("the change could not be read")
    return [line.strip() for line in listing.out.splitlines() if line.strip()]


def push(worktree: str, branch: str, repo: str) -> str:
    """Push the branch after checking ``origin`` fetches from and pushes to ``repo``."""
    root = Path(worktree)
    for direction in (False, True):
        if gitcmd.origin_repo(root, push=direction).lower() != repo.lower():
            raise BuildError(f"origin does not point at {repo}")
    if not branch.startswith(BRANCH_PREFIX):
        raise BuildError("refusing to push a branch the loop did not create")
    result = gitcmd.git(
        ["push", "--set-upstream", "origin", f"refs/heads/{branch}:refs/heads/{branch}"],
        root,
        timeout=gitcmd.NETWORK_TIMEOUT_S,
    )
    if not result.ok:
        raise BuildError(f"the branch could not be pushed: {result.tail(300)}")
    return gitcmd.out(["rev-parse", "HEAD"], root)


def remove_local(
    folder: str, worktree: str, branch: str, *, head: str = "", force: bool = False
) -> bool:
    """Remove the loop's worktree and local branch. Returns False when it kept them.

    Only a ``dodaios/`` branch. Kept when the branch moved past ``head`` (the
    person added commits) or, without ``force``, when the worktree holds
    uncommitted changes. ``force`` is for a run that is still the loop's own.
    """
    if not branch.startswith(BRANCH_PREFIX):
        return False
    root = Path(folder)
    tip = gitcmd.out(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], root)
    if head and tip and tip != head:
        logger.info("self-build code: kept {}: it has commits the loop did not make", branch)
        return False
    if worktree and Path(worktree).exists():
        if not force and _unsaved(worktree):
            logger.info("self-build code: kept {}: it has uncommitted changes", worktree)
            return False
        removed = gitcmd.git(
            ["worktree", "remove", *(["--force"] if force else []), worktree], root
        )
        if not removed.ok:
            logger.info("self-build code: git left {}: {}", worktree, removed.tail(200))
    gitcmd.git(["worktree", "prune"], root)
    if worktree and not _registered(root, worktree):
        # What git could not delete (Windows: a long path or a held file).
        _sweep(Path(worktree))
        _drop_if_empty(Path(worktree).parent)
    if tip:
        gitcmd.git(["branch", "-D", branch], root)
    return True


def _registered(root: Path, worktree: str) -> bool:
    """Does git still know ``worktree`` as one of the repository's worktrees?"""
    listing = gitcmd.git(["worktree", "list", "--porcelain"], root)
    if not listing.ok:
        return True  # unknown: nothing is deleted
    want = Path(worktree).resolve()
    for line in listing.out.splitlines():
        if line.startswith("worktree ") and Path(line[9:].strip()).resolve() == want:
            return True
    return False


def _sweep(worktree: Path, *, attempts: int = 5, pause_s: float = 1.0) -> None:
    """Delete what is left of the loop's worktree once git forgot it: caches only.

    Live on Windows the folder stayed behind with the test run's
    ``__pycache__`` when git could not delete a path past the length limit or
    a file a finished process still held. Only a folder that holds nothing but
    such caches is deleted; a short retry covers a handle being released.
    """
    import shutil
    import time

    for attempt in range(attempts):
        if not worktree.is_dir():
            return
        try:
            files = [path for path in worktree.rglob("*") if path.is_file()]
        except OSError:  # unreadable: left alone
            return
        parts = [path.relative_to(worktree).parts for path in files]
        if any(not any(part in _JUNK for part in rel) for rel in parts):
            logger.info("self-build code: kept {}: it holds more than caches", worktree)
            return
        try:
            shutil.rmtree(worktree)
            return
        except OSError:  # still held by a process that is ending: try again shortly
            if attempt + 1 < attempts:
                time.sleep(pause_s)
    logger.info("self-build code: {} is still in use; left for now", worktree)


def _drop_if_empty(folder: Path) -> None:
    """Remove ``<repo>/.worktrees`` once the loop's worktree was the last one in it."""
    from dodaios.agentic_ide import git_ops

    if folder.name != git_ops.WORKTREE_DIR:
        return
    try:
        folder.rmdir()  # only succeeds while empty
    except OSError:  # other worktrees live there, or it is already gone
        pass


def _unsaved(worktree: str) -> list[str]:
    """Changes in the worktree someone would miss (caches and builds do not count)."""
    lines = gitcmd.out(["status", "--porcelain"], worktree).splitlines()
    return [line for line in lines if not any(junk in line for junk in _JUNK)]


def remove_remote(folder: str, branch: str, head: str) -> None:
    """Delete the pushed branch, only while it still points at the loop's ``head``."""
    if not branch.startswith(BRANCH_PREFIX) or not head:
        return
    result = gitcmd.git(
        [
            "push",
            f"--force-with-lease=refs/heads/{branch}:{head}",
            "origin",
            f":refs/heads/{branch}",
        ],
        Path(folder),
        timeout=gitcmd.NETWORK_TIMEOUT_S,
    )
    if not result.ok and "remote ref does not exist" not in result.err:
        logger.info("self-build code: kept the remote branch {}: {}", branch, result.tail(200))


# ------------------------------------------------------------------ prompt


def _relevant_files(worktree: str, issue: Issue) -> str:
    try:
        from dodaios.agentic_ide.code_skeleton import skeletons
        from dodaios.agentic_ide.file_index import build_index

        rels = build_index(worktree).suggest(f"{issue.title}\n{issue.body[:1500]}", limit=6)
        outlines = skeletons(worktree, rels, max_files=4, max_total=12_000)
    except Exception as exc:  # noqa: BLE001 - the agent finds the files itself without hints
        logger.debug("self-build code: no file hints: {}", exc)
        return ""
    return "\n\n".join(f"### {rel}\n{text}" for rel, text in outlines.items())


def compose_prompt(
    *,
    issue: Issue,
    repo: str,
    worktree: str,
    branch: str,
    base: str,
    brief_text: str,
    plan: Plan,
    tests: list[str],
) -> str:
    parts = [
        f"Work on issue #{issue.number} of {repo} on your own. Nobody is at the computer to "
        "answer questions, so decide yourself and follow the repository's conventions.",
        f"You work in {worktree}: a fresh git worktree on branch {branch}, made from "
        f"origin/{base}. Stay in this folder.",
        "",
        f"## Issue #{issue.number}: {issue.title}",
        issue.body.strip()[:4_000] or "(no description)",
    ]
    if plan.text:
        parts += ["", "## Suggested plan", plan.text]
    parts += ["", "## Project brief", brief_text]
    hints = _relevant_files(worktree, issue)
    if hints:
        parts += ["", "## Files that look relevant (outlines)", hints]
    parts += [
        "",
        "## Rules",
        "- Keep the change as small as the issue needs, and add or update tests for it.",
        "- Follow the repository's own instruction files shown in the brief.",
        "- Do not touch CI config (.github and the like), deployment, secrets, .env files or "
        "the instruction files (CLAUDE.md). A change that does is thrown away.",
        "- Do not push, open pull requests, comment on GitHub, change git remotes or switch "
        "branches; Dodaios checks your work and does that.",
        "- Run the tests before you finish; Dodaios runs exactly these to judge the "
        "change, so run them the same way: " + "; ".join(tests) + ".",
        "- Commit your work on this branch with a clear message.",
        "- If the issue cannot be done safely, change nothing and say why in one paragraph.",
        "- End with a short summary of what you changed and how you checked it; it becomes "
        "the pull request description, so write it for the repository's reviewers: no paths "
        "on this computer, no notes about its tools or shell. Write it in the language the "
        "issue is written in.",
    ]
    return "\n".join(parts)


_LOCAL_PATH: Final[re.Pattern[str]] = re.compile(
    r"(?i)(?<![\w/])(?:[a-z]:[\\/]|/(?:users|home|private|tmp|var/folders)/)[^\s`'\")\]]+"
)
_QUOTED_LOCAL_PATH: Final[re.Pattern[str]] = re.compile(
    r"(?i)`[^`\n]*?(?<![\w/])(?:[a-z]:[\\/]|/(?:users|home|private|tmp|var/folders)/)[^`\n]*`"
)


def scrub(text: str, worktree: str = "") -> str:
    """The agent's summary without this computer's paths (it goes to GitHub)."""
    if worktree:
        for form in {worktree, worktree.replace("\\", "/"), worktree.replace("/", "\\")}:
            text = text.replace(form + "\\", "").replace(form + "/", "").replace(form, ".")
    # A quoted path may hold spaces ("C:\Program Files\..."): the whole span goes.
    text = _QUOTED_LOCAL_PATH.sub("`<local path>`", text)
    return _LOCAL_PATH.sub("<local path>", text)


def pr_body(
    *,
    issue: Issue,
    summary: str,
    tests_detail: str,
    changed: list[str],
    build_id: str,
    plan: Plan,
    worktree: str = "",
) -> str:
    text = re.sub(r"(?im)^\s*(closes|fixes|resolves)\s+#\d+\s*$", "", summary).strip()
    text = scrub(text, worktree)
    lines = [f"Closes #{issue.number}", "", text[:_SUMMARY_CHARS] or "(no summary)", ""]
    lines += ["### Checked", *[f"- {line}" for line in tests_detail.splitlines() if line]]
    shown = ", ".join(f"`{path}`" for path in changed[:15])
    lines.append(f"- Changed files: {shown}" + (" …" if len(changed) > 15 else ""))
    if plan.size:
        lines.append(f"- Estimated size before the run: {plan.size}")
    lines += ["", _FOOTER.format(number=issue.number, build_id=build_id)]
    return "\n".join(lines)


# ------------------------------------------------------------------ the build


def target(ctx: Context, record: BuildRecord) -> tuple[str, Issue, dict[str, Any]]:
    """``(repo, issue, intake data)`` for a code record, from the intake store."""
    parsed = parse_signature(record.signature)
    if parsed is None:
        raise BuildError(f"not a code signature: {record.signature}")
    repo, number = parsed
    seen = ctx.store.issue(repo, number)
    if seen is None or not seen["issue"].get("folder"):
        raise BuildError("the issue is no longer known; it was not seen in the last poll")
    data = seen["issue"]
    return repo, Issue.from_json(data), data


async def recheck(ctx: Context, repo: str, issue: Issue, data: dict[str, Any]) -> Issue:
    """The issue as it stands right before the build, or :class:`Obsolete`.

    A proposal can wait days for the person's accept or for idle time; by then
    the issue may be closed, taken by someone else, relabelled, or the
    repository may have changed hands. Any of these ends the case before any
    work. GitHub not answering only puts the case back in the queue.
    """
    from dataclasses import replace

    from dodaios.agentic_ide.github_link import GitHubError

    from .intake import repo_of, viewer
    from .triage import triage

    api = ctx.github()
    if api is None:
        raise Stopped("stopped: GitHub is not connected", requeue=True)
    try:
        who = await viewer(ctx)
        fresh = await asyncio.to_thread(api.issue, repo, issue.number)
    except GitHubError as exc:  # re-raised: the case waits for the next pass
        raise Stopped(f"stopped: GitHub could not be asked ({exc})", requeue=True) from exc
    if who is None:
        raise Stopped("stopped: the GitHub account is unknown", requeue=True)
    folder = str(data["folder"])
    origin = await asyncio.to_thread(repo_of, folder)
    if not who.owns(repo) or origin.lower() != repo.lower():
        raise Obsolete("not built: the repository is no longer the person's own")
    if fresh is None or fresh.state.upper() != "OPEN":
        raise Obsolete(f"not built: issue #{issue.number} is closed")
    others = [login for login in fresh.assigned_to if login.lower() != who.login.lower()]
    if others or (fresh.assignees and not fresh.assigned_to):
        raise Obsolete(f"not built: issue #{issue.number} is assigned to someone else")
    profile = await asyncio.to_thread(ctx.store.profile, repo)
    # Assigned to the person themselves is fine; the test command is checked next.
    verdict = triage(replace(fresh, assignees=0), login=who.login, profile=profile, has_tests=True)
    if not verdict.fit:
        raise Obsolete(f"not built: issue #{issue.number} no longer fits ({verdict.reason})")
    await asyncio.to_thread(
        ctx.store.put_issue,
        repo,
        fresh.number,
        updated_at=fresh.updated_at,
        verdict="fit",
        reason=f"{verdict.signal}; rechecked",
        issue={**data, **fresh.to_json()},
    )
    return fresh


def checkpoint(ctx: Context, record: BuildRecord) -> None:
    """Raise :class:`Stopped` once the build was undone or the loop paused."""
    if record.id in ctx.stopping or not ctx.still(record, State.BUILDING):
        raise Stopped("stopped: the build was undone", requeue=False)
    if _paused(ctx):
        raise Stopped("stopped: the self-building loop was paused", requeue=True)


async def _record(
    ctx: Context, record: BuildRecord, stage: str, undo: dict[str, Any], **extra: Any
) -> None:
    artefact = {
        "type": "code",
        "id": "",  # the pull request's URL, once there is one
        "repo": undo["repo"],
        "branch": undo["branch"],
        "stage": stage,
        **_thread(undo),
        **extra,
    }
    await asyncio.to_thread(ctx.ledger.attach_artefact, record.id, artefact, dict(undo))


def _thread(undo: dict[str, Any]) -> dict[str, str]:
    """``{"thread": <agent-chat session id>}`` once the coding run has one: the
    build detail links to it, so the person can read every step."""
    session_id = str(undo.get("session_id") or "")
    return {"thread": session_id} if session_id else {}


async def _fail(ctx: Context, record: BuildRecord, error: BuildError, *, repo: str) -> None:
    from .watch import cleanup

    lesson = str(error).strip()[:400] or "the build failed"
    current = await asyncio.to_thread(ctx.ledger.get, record.id)
    if current is not None and current.undo:
        try:
            await cleanup(ctx, current, close_pull=True, force=True)
        except Exception:  # noqa: BLE001 - logged; what is left is listed in the record
            logger.opt(exception=True).warning("self-build code: cleanup of {} failed", record.id)
    if isinstance(error, Obsolete):
        logger.info("self-build code: {} not built: {}", record.signature, lesson)
        if ctx.still(record, State.BUILDING):
            await asyncio.to_thread(ctx.ledger.set_state, record.id, State.FAILED, lesson)
        return
    if isinstance(error, Stopped):
        if error.requeue and ctx.still(record, State.BUILDING):
            await asyncio.to_thread(ctx.ledger.attach_artefact, record.id, {}, {})
            logger.info("self-build code: {} paused; it waits in the queue", record.signature)
        return  # an undo owns the record's state
    logger.info("self-build code: {} failed: {}", record.signature, lesson)
    if repo:
        parsed = parse_signature(record.signature)
        await asyncio.to_thread(
            ctx.store.add_to_profile,
            repo,
            "lessons",
            {"number": parsed[1] if parsed else 0, "lesson": lesson},
        )
    if ctx.still(record, State.BUILDING, State.PROVING):
        await asyncio.to_thread(ctx.ledger.set_state, record.id, State.FAILED, lesson)


async def _guarded(ctx: Context, record: BuildRecord, step: Any) -> None:
    repo = ""
    try:
        repo, issue, data = target(ctx, record)
        await step(repo, issue, data)
    except BuildError as exc:  # _fail logs it, keeps the lesson and settles the record
        await _fail(ctx, record, exc, repo=repo)
    except Exception as exc:  # noqa: BLE001 - an unexpected error fails this build only
        logger.opt(exception=exc).warning("self-build code: build {} crashed", record.id)
        await _fail(ctx, record, BuildError(f"unexpected error: {type(exc).__name__}"), repo=repo)


async def build(
    ctx: Context, record: BuildRecord, *, provider: str, drop_env: tuple[str, ...] = ()
) -> None:
    """Run one build to ``proving`` (pull request open), ``failed``, or back to the queue.

    ``drop_env``: variables the coding CLI's process must not see (``seat``).
    """

    async def step(repo: str, issue: Issue, data: dict[str, Any]) -> None:
        await _build(
            ctx, record, repo=repo, issue=issue, data=data, provider=provider, drop_env=drop_env
        )

    await _guarded(ctx, record, step)


async def resume(ctx: Context, record: BuildRecord, result: RunResult | None) -> None:
    """Carry on a build whose coding run ended while the app was not running."""

    async def step(repo: str, issue: Issue, data: dict[str, Any]) -> None:
        if result is None or not result.ok:
            error = (result.error if result else "") or "no answer"
            raise BuildError(f"the coding run did not finish: {error}")
        brief, _ = await asyncio.to_thread(
            brief_mod.refresh, ctx.store, str(data["folder"]), repo=repo
        )
        await finish(
            ctx,
            record,
            repo=repo,
            issue=issue,
            undo=dict(record.undo),
            summary=result.summary,
            tests=brief.test_commands,
            setup=brief.setup_commands,
            plan=Plan(),
        )

    await _guarded(ctx, record, step)


async def _build(
    ctx: Context,
    record: BuildRecord,
    *,
    repo: str,
    issue: Issue,
    data: dict[str, Any],
    provider: str,
    drop_env: tuple[str, ...] = (),
) -> None:
    folder = str(data["folder"])
    issue = await recheck(ctx, repo, issue, data)
    brief, _ = await asyncio.to_thread(brief_mod.refresh, ctx.store, folder, repo=repo)
    tests = brief.test_commands
    if not tests:
        raise BuildError("no test command in this repository")
    # GitHub's own default branch, read at intake; the local guess only as a fallback.
    base = str(data.get("base") or "") or brief.default_branch or "main"
    branch = branch_name(issue.number, issue.title)
    undo: dict[str, Any] = {
        "repo": repo,
        "folder": folder,
        "branch": branch,
        "base": base,
        "worktree": planned_worktree(folder, branch),
    }
    await _record(ctx, record, "worktree", undo)
    checkpoint(ctx, record)
    made = await asyncio.to_thread(make_worktree, folder, branch, base)
    undo.update(made, created=True)
    await _record(ctx, record, "worktree", undo)
    checkpoint(ctx, record)

    plan = Plan()
    if ctx.plan is not None:
        plan = await ctx.plan(record.id, issue, brief.render())
        if plan.size == "large":
            raise BuildError("estimated as large work, not for an unattended agent")
    checkpoint(ctx, record)

    from . import commands

    prompt = compose_prompt(
        issue=issue,
        repo=repo,
        worktree=undo["worktree"],
        branch=branch,
        base=base,
        brief_text=brief.render(),
        plan=plan,
        tests=[commands.runnable(cmd) for cmd in tests],
    )

    async def remember_session(session_id: str) -> None:
        undo["session_id"] = session_id
        await _record(ctx, record, "coding", undo)

    def should_stop() -> bool:
        try:
            checkpoint(ctx, record)
        except Stopped:  # the answer to "should the run stop?", not an error
            return True
        return False

    result = await ctx.runner.run(
        provider=provider,
        folder=undo["worktree"],
        prompt=prompt,
        title=f"#{issue.number} {issue.title}",
        timeout_s=ctx.run_timeout_s,
        should_stop=should_stop,
        on_session=remember_session,
        drop_env=drop_env,
    )
    checkpoint(ctx, record)
    if not result.ok:
        raise BuildError(f"the coding run did not finish: {result.error or 'no answer'}")
    await finish(
        ctx,
        record,
        repo=repo,
        issue=issue,
        undo=undo,
        summary=result.summary,
        tests=tests,
        setup=brief.setup_commands,
        plan=plan,
    )


async def finish(
    ctx: Context,
    record: BuildRecord,
    *,
    repo: str,
    issue: Issue,
    undo: dict[str, Any],
    summary: str,
    tests: list[list[str]],
    setup: list[list[str]],
    plan: Plan,
) -> None:
    """Judge the finished run and open the pull request (also used on resume)."""
    ledger = ctx.ledger
    worktree, branch = str(undo["worktree"]), str(undo["branch"])
    message = f"fix: {issue.title.strip()[:60]} (#{issue.number})"
    changed = await asyncio.to_thread(collect, worktree, branch, str(undo["base_sha"]), message)
    if not changed:
        raise BuildError(
            "the coding agent changed nothing" + (f": {summary[:200]}" if summary else "")
        )
    blocked = judge.guard(changed)
    if blocked:
        raise BuildError("the change touched protected files: " + ", ".join(blocked[:5]))
    passed, detail = await asyncio.to_thread(judge.run_tests, worktree, setup=setup, tests=tests)
    if not passed:
        await asyncio.to_thread(
            ledger.attach_proof, record.id, passed=False, judge="tests", detail=detail
        )
        raise BuildError("the tests failed: " + detail.splitlines()[0][:200])
    checkpoint(ctx, record)

    api = ctx.github()
    if api is None:
        raise BuildError("GitHub is not connected")
    undo["head"] = gitcmd.out(["rev-parse", "HEAD"], worktree)
    undo["pushed"] = True  # before the push: an undo meanwhile still deletes it
    await _record(ctx, record, "pushing", undo)
    undo["head"] = await asyncio.to_thread(push, worktree, branch, repo)
    await _record(ctx, record, "pushed", undo)
    checkpoint(ctx, record)
    draft = repo.lower() not in land_repos(ctx.config())
    pull = await asyncio.to_thread(
        api.create_pull,
        repo,
        head=branch,
        base=str(undo["base"]),
        title=issue.title.strip()[:120] or f"Fix #{issue.number}",
        body=pr_body(
            issue=issue,
            summary=summary,
            tests_detail=detail,
            changed=changed,
            build_id=record.id,
            plan=plan,
            worktree=worktree,
        ),
        draft=draft,
    )
    undo.update({"pr_id": pull.id, "pr_number": pull.number, "pr_url": pull.url})
    artefact = {
        "type": "code",
        "id": pull.url,
        "stage": "pull_request",
        "repo": repo,
        "number": pull.number,
        "url": pull.url,
        "branch": branch,
        "draft": draft,
        "tests": detail[:500],
        "changed": changed[:30],
        "opened_ms": now_ms(),
        **_thread(undo),
    }
    await asyncio.to_thread(ledger.attach_artefact, record.id, artefact, dict(undo))
    checkpoint(ctx, record)
    await asyncio.to_thread(
        ledger.set_state, record.id, State.PROVING, "pull request opened; waiting for CI"
    )


def _paused(ctx: Context) -> bool:
    from .. import policy

    return policy.paused(ctx.ledger)
