"""Build one code case: worktree, plan, coding run, judge, pull request.

Called by the loop for a ``Kind.CODE`` record in ``building``. Each step
records what it made in the ledger before the next one starts, so an undo (or
a restart) at any point knows exactly what exists:

1. a fresh worktree and branch (``dodaios/issue-<n>-...``) from the remote
   default branch, inside the repository (``<repo>/.worktrees/``);
2. at most one cheap planning call; ``large`` stops here;
3. a headless coding thread on a subscription CLI in that worktree;
4. the judge: nothing protected was touched, the tests pass;
5. push the branch and open a pull request that closes the issue, draft unless
   the person opted the repository in to landing. The record moves to
   ``proving``; ``watch`` waits for CI.

A failure at any step records the lesson in the repository's profile, removes
what the run created and moves the record to ``failed``. No pull request is
left behind by a failed build.
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


class BuildError(RuntimeError):
    """A step failed; the message is the lesson the profile keeps."""


# ------------------------------------------------------------------ git steps


def make_worktree(folder: str, branch: str, base_branch: str) -> dict[str, str]:
    """A fresh worktree on ``branch`` from ``origin/<base_branch>``."""
    from dodaios.agentic_ide import git_ops

    root = Path(folder)
    fetch = gitcmd.git(["fetch", "origin", base_branch], root, timeout=gitcmd.NETWORK_TIMEOUT_S)
    base = f"origin/{base_branch}" if fetch.ok else base_branch
    base_sha = gitcmd.out(["rev-parse", f"{base}^{{commit}}"], root)
    if not base_sha:
        raise BuildError(f"the default branch {base_branch} could not be read")
    try:
        prepared = git_ops.prepare(root, "new_worktree", branch=branch, base=base_sha)
    except git_ops.GitError as exc:  # re-raised as the build's lesson
        raise BuildError(f"no worktree: {exc}") from exc
    if not prepared.created:
        raise BuildError(f"the branch {branch} already exists")
    return {"worktree": prepared.folder, "base_sha": base_sha, "base": base_branch}


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
    listing = gitcmd.git(["diff", "--name-only", f"{base_sha}..HEAD"], root)
    if not listing.ok:
        raise BuildError("the change could not be read")
    return [line.strip() for line in listing.out.splitlines() if line.strip()]


def push(worktree: str, branch: str, repo: str) -> str:
    """Push the branch to ``origin`` after checking origin IS ``repo``. Returns the head sha."""
    from dodaios.agentic_ide.github_link import remote_repository

    root = Path(worktree)
    if remote_repository(root).lower() != repo.lower():
        raise BuildError(f"origin does not point at {repo}")
    if not branch.startswith(BRANCH_PREFIX):
        raise BuildError("refusing to push a branch the loop did not create")
    result = gitcmd.git(
        ["push", "--set-upstream", "origin", f"{branch}:{branch}"],
        root,
        timeout=gitcmd.NETWORK_TIMEOUT_S,
    )
    if not result.ok:
        raise BuildError(f"the branch could not be pushed: {result.tail(300)}")
    return gitcmd.out(["rev-parse", "HEAD"], root)


def remove_local(folder: str, worktree: str, branch: str) -> None:
    """Remove the loop's worktree and local branch (only a ``dodaios/`` branch)."""
    if not branch.startswith(BRANCH_PREFIX):
        return
    root = Path(folder)
    if worktree and Path(worktree).exists():
        gitcmd.git(["worktree", "remove", "--force", worktree], root)
    gitcmd.git(["worktree", "prune"], root)
    gitcmd.git(["branch", "-D", branch], root)


def remove_remote(folder: str, branch: str) -> None:
    if not branch.startswith(BRANCH_PREFIX):
        return
    result = gitcmd.git(
        ["push", "origin", "--delete", branch], Path(folder), timeout=gitcmd.NETWORK_TIMEOUT_S
    )
    if not result.ok and "remote ref does not exist" not in result.err:
        logger.warning(
            "self-build code: remote branch {} not deleted: {}", branch, result.tail(200)
        )


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
        "the instruction files (AGENTS.md, CLAUDE.md). A change that does is thrown away.",
        "- Do not push, open pull requests, comment on GitHub or switch branches; Dodaios "
        "checks your work and does that.",
        "- Run the tests before you finish; they must pass: " + "; ".join(tests) + ".",
        "- Commit your work on this branch with a clear message.",
        "- If the issue cannot be done safely, change nothing and say why in one paragraph.",
        "- End with a short summary of what you changed and how you checked it; it becomes "
        "the pull request description.",
    ]
    return "\n".join(parts)


def pr_body(
    *,
    issue: Issue,
    summary: str,
    tests_detail: str,
    changed: list[str],
    build_id: str,
    plan: Plan,
) -> str:
    text = re.sub(r"(?im)^\s*(closes|fixes|resolves)\s+#\d+\s*$", "", summary).strip()
    lines = [f"Closes #{issue.number}", "", text[:_SUMMARY_CHARS] or "(no summary)", ""]
    lines += ["### Checked", *[f"- {line}" for line in tests_detail.splitlines() if line]]
    shown = ", ".join(f"`{path}`" for path in changed[:15])
    lines.append(f"- Changed files: {shown}" + (" …" if len(changed) > 15 else ""))
    if plan.size:
        lines.append(f"- Estimated size before the run: {plan.size}")
    lines += ["", _FOOTER.format(number=issue.number, build_id=build_id)]
    return "\n".join(lines)


# ------------------------------------------------------------------ the build


def target(ctx: Context, record: BuildRecord) -> tuple[str, Issue, str]:
    """``(repo, issue, folder)`` for a code record, from the intake store."""
    parsed = parse_signature(record.signature)
    if parsed is None:
        raise BuildError(f"not a code signature: {record.signature}")
    repo, number = parsed
    seen = ctx.store.issue(repo, number)
    if seen is None or not seen["issue"].get("folder"):
        raise BuildError("the issue is no longer known; it was not seen in the last poll")
    data = seen["issue"]
    return repo, Issue.from_json(data), str(data["folder"])


async def _fail(ctx: Context, record: BuildRecord, lesson: str, *, repo: str = "") -> None:
    from .watch import cleanup

    lesson = lesson.strip()[:400] or "the build failed"
    logger.info("self-build code: {} failed: {}", record.signature, lesson)
    current = await asyncio.to_thread(ctx.ledger.get, record.id)
    if current is not None and current.undo:
        await cleanup(ctx, current, close_pull=True)
    if repo:
        parsed = parse_signature(record.signature)
        number = parsed[1] if parsed else 0
        await asyncio.to_thread(
            ctx.store.add_to_profile, repo, "lessons", {"number": number, "lesson": lesson}
        )
    if ctx.still(record, State.BUILDING, State.PROVING):
        await asyncio.to_thread(ctx.ledger.set_state, record.id, State.FAILED, lesson)


async def build(ctx: Context, record: BuildRecord, *, provider: str) -> None:
    """Run one build to ``proving`` (pull request open) or ``failed``."""
    repo = ""
    try:
        repo, issue, folder = target(ctx, record)
        await _build(ctx, record, repo=repo, issue=issue, folder=folder, provider=provider)
    except BuildError as exc:  # _fail logs it, keeps the lesson and fails the record
        await _fail(ctx, record, str(exc), repo=repo)
    except Exception as exc:  # noqa: BLE001 - an unexpected error fails this build only
        logger.opt(exception=exc).warning("self-build code: build {} crashed", record.id)
        await _fail(ctx, record, f"unexpected error: {type(exc).__name__}", repo=repo)


async def resume(ctx: Context, record: BuildRecord, result: RunResult | None) -> None:
    """Carry on a build whose coding run ended while the app was not running."""
    repo = ""
    try:
        repo, issue, folder = target(ctx, record)
        if result is None or not result.ok:
            error = (result.error if result else "") or "no answer"
            raise BuildError(f"the coding run did not finish: {error}")
        brief, _ = await asyncio.to_thread(brief_mod.refresh, ctx.store, folder, repo=repo)
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
    except BuildError as exc:  # _fail logs it, keeps the lesson and fails the record
        await _fail(ctx, record, str(exc), repo=repo)
    except Exception as exc:  # noqa: BLE001 - an unexpected error fails this build only
        logger.opt(exception=exc).warning("self-build code: resume {} crashed", record.id)
        await _fail(ctx, record, f"unexpected error: {type(exc).__name__}", repo=repo)


async def _build(
    ctx: Context, record: BuildRecord, *, repo: str, issue: Issue, folder: str, provider: str
) -> None:
    ledger = ctx.ledger
    brief, _ = await asyncio.to_thread(brief_mod.refresh, ctx.store, folder, repo=repo)
    tests = brief.test_commands
    if not tests:
        raise BuildError("no test command in this repository")
    base = brief.default_branch or "main"
    branch = branch_name(issue.number, issue.title)
    made = await asyncio.to_thread(make_worktree, folder, branch, base)
    worktree = made["worktree"]
    undo: dict[str, Any] = {
        "repo": repo,
        "folder": folder,
        "worktree": worktree,
        "branch": branch,
        "base_sha": made["base_sha"],
        "base": made["base"],
    }
    record = await asyncio.to_thread(
        ledger.attach_artefact,
        record.id,
        {"type": "branch", "repo": repo, "branch": branch, "stage": "worktree"},
        undo,
    )
    if not ctx.still(record, State.BUILDING):
        raise BuildError("stopped before the run")

    plan = Plan()
    if ctx.plan is not None:
        plan = await ctx.plan(record.id, issue, brief.render())
        if plan.size == "large":
            raise BuildError("estimated as large work, not for an unattended agent")

    from . import commands

    shown_tests = [commands.shown(cmd) for cmd in tests]
    prompt = compose_prompt(
        issue=issue,
        repo=repo,
        worktree=worktree,
        branch=branch,
        base=base,
        brief_text=brief.render(),
        plan=plan,
        tests=shown_tests,
    )

    async def remember_session(session_id: str) -> None:
        undo["session_id"] = session_id
        await asyncio.to_thread(
            ledger.attach_artefact,
            record.id,
            {
                "type": "branch",
                "repo": repo,
                "branch": branch,
                "stage": "coding",
                "thread": session_id,
            },
            dict(undo),
        )

    result = await ctx.runner.run(
        provider=provider,
        folder=worktree,
        prompt=prompt,
        title=f"#{issue.number} {issue.title}",
        timeout_s=ctx.run_timeout_s,
        should_stop=lambda: not ctx.still(record, State.BUILDING) or _paused(ctx),
        on_session=remember_session,
    )
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
    if not ctx.still(record, State.BUILDING) or _paused(ctx):
        raise BuildError("stopped before the pull request")

    api = ctx.github()
    if api is None:
        raise BuildError("GitHub is not connected")
    head = await asyncio.to_thread(push, worktree, branch, repo)
    undo["pushed"] = True
    undo["head"] = head
    await asyncio.to_thread(
        ledger.attach_artefact,
        record.id,
        {"type": "branch", "repo": repo, "branch": branch, "stage": "pushed"},
        dict(undo),
    )
    draft = repo.lower() not in land_repos(ctx.config())
    pull = await asyncio.to_thread(
        api.create_pull,
        repo,
        head=branch,
        base=str(undo.get("base") or "") or _base_of(ctx, undo),
        title=issue.title.strip()[:120] or f"Fix #{issue.number}",
        body=pr_body(
            issue=issue,
            summary=summary,
            tests_detail=detail,
            changed=changed,
            build_id=record.id,
            plan=plan,
        ),
        draft=draft,
    )
    undo.update({"pr_id": pull.id, "pr_number": pull.number, "pr_url": pull.url})
    artefact = {
        "type": "pull_request",
        "repo": repo,
        "number": pull.number,
        "url": pull.url,
        "branch": branch,
        "draft": draft,
        "tests": detail[:500],
        "changed": changed[:30],
        "opened_ms": now_ms(),
    }
    await asyncio.to_thread(ledger.attach_artefact, record.id, artefact, dict(undo))
    await asyncio.to_thread(
        ledger.set_state, record.id, State.PROVING, "pull request opened; waiting for CI"
    )


def _base_of(ctx: Context, undo: dict[str, Any]) -> str:
    loaded = brief_mod.load(ctx.store, str(undo["folder"]))
    return (loaded.default_branch if loaded else "") or "main"


def _paused(ctx: Context) -> bool:
    from .. import policy

    return policy.paused(ctx.ledger)
