#!/usr/bin/env python3
"""Agent done gate: a coding agent may end its turn only when its work has landed.

Every coding CLI's Stop hook calls this script (Claude Code, Codex, Kimi CLI,
OpenCode; see ``docs/agent-done-gate.md``). It answers with one verdict:

    DONE   the work landed: PR merged, CI green on main, local main has it
    NONE   this session has no branch work to land (research, chat)
    HOLD   the PR is a draft / opted out, or the user put the branch on hold
    WAIT   CI is running, the PR is queued, or a merge freeze holds main
    FIX    something only the agent can fix: red checks, conflicts, unpushed
           commits, missing auto-merge, red CI on main for the merge commit
    STUCK  WAIT or FIX did not move within the budget; stop and report

DONE means all of:
    D1 no uncommitted tracked changes in the branch's worktree
    D2 every local commit of the branch is on the remote
    D3 the branch's pull request is merged into main
    D4 the main CI workflows are green for the merge commit (or a later main
       commit that contains it)
    D5 the local main checkout contains the merge commit (the gate
       fast-forwards it; a checkout with local edits is left alone and noted)

Which branches belong to a session: the branch checked out in the hook's
``cwd`` plus every branch the session created or pushed, read from the
commands in its transcript (sessions often ``cd`` into a worktree while the
hook still reports the main checkout).

Usage::

    python scripts/agent_done_gate.py                 # check, human output
    python scripts/agent_done_gate.py --json
    python scripts/agent_done_gate.py --wait [SECONDS] # poll while WAIT
    python scripts/agent_done_gate.py --hold "user wants it local"
    python scripts/agent_done_gate.py --release
    python scripts/agent_done_gate.py --hook claude|codex|kimi < hook.json

Exit codes: 0 = may stop, 3 = must continue (WAIT/FIX). A crash of the gate
itself exits 0 with a warning: a broken gate must never trap a session.

stdlib + ``git`` + ``gh`` only; Windows, macOS and Linux.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci import merge_freeze  # noqa: E402

#: ``run(cmd, cwd)`` or ``run(cmd, cwd, timeout=seconds)``.
Runner = Callable[..., subprocess.CompletedProcess]
#: Commands that only read (or call GitHub) are given up on after this long.
READ_TIMEOUT_S = 120.0
#: A git command that writes a work tree is never killed on a short timer: killed
#: mid-write, it leaves ``index.lock`` behind and a checkout half way to the new
#: commit, which then blocks every later update until someone cleans up by hand.
GIT_WRITE_TIMEOUT_S = 30 * 60.0

MAY_STOP = ("DONE", "NONE", "HOLD", "STUCK")
MUST_CONTINUE = ("WAIT", "FIX")
EXIT_STOP, EXIT_CONTINUE = 0, 3
# Worst first: the session's verdict is the worst over its branches.
SEVERITY = {"FIX": 5, "WAIT": 4, "STUCK": 3, "HOLD": 2, "DONE": 1, "NONE": 0}

OPT_OUT_LABELS = {"no-auto-merge", "do-not-merge", "wip", "needs-human"}
CONFIG_PATH = ".github/agent-done-gate.json"
DEFAULT_CONFIG: dict[str, object] = {
    "base": "main",
    # Empty = every check / every push workflow counts.
    "required_checks": [],
    "main_workflows": [],
    "wait_budget_hours": 3.0,
    "fix_budget_blocks": 8,
    "hook_wait_seconds": 480,
    "poll_seconds": 90,
}
STATE_DIR = "agent-done-gate"
LAND_HINT = "python scripts/agent_land.py"
GATE_HINT = "python scripts/agent_done_gate.py"

_FAILED = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "STARTUP_FAILURE", "ACTION_REQUIRED"}
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_RUN_ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested"}
_RUN_OK = {"success", "neutral", "skipped"}

# Commands that create or publish a branch. Matched only inside command
# strings of the transcript, never inside tool output.
_BRANCH_PATTERNS = (
    re.compile(r"worktree\s+add(?:\s+-{1,2}[\w-]+)*?\s+-[bB]\s+([\w./-]+)"),
    re.compile(r"\b(?:checkout\s+-[bB]|switch\s+-[cC])\s+([\w./-]+)"),
    re.compile(r"\bpush\b(?:\s+-{1,2}[\w-]+)*\s+[\w.-]+\s+(?:HEAD:)?(?:refs/heads/)?([\w./-]+)"),
)
_COMMAND_KEYS = {"command", "cmd", "arguments"}


class GateError(Exception):
    """A fact could not be read; the gate fails open."""


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------


def default_runner(
    cmd: list[str], cwd: Path | None = None, *, timeout: float = READ_TIMEOUT_S
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, 127, "", str(exc))


@dataclass
class Ctx:
    cwd: Path
    run: Runner = default_runner
    now: Callable[[], float] = time.time
    config: dict = field(default_factory=lambda: dict(DEFAULT_CONFIG))
    repo: str = ""
    common_dir: Path | None = None
    _freeze: tuple[float, object] | None = None

    def git(
        self, *args: str, cwd: Path | None = None, timeout: float | None = None
    ) -> subprocess.CompletedProcess:
        if timeout is None:
            return self.run(["git", *args], cwd or self.cwd)
        return self.run(["git", *args], cwd or self.cwd, timeout=timeout)

    def git_out(self, *args: str, cwd: Path | None = None) -> str | None:
        proc = self.git(*args, cwd=cwd)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def gh_json(self, args: list[str]) -> object:
        proc = self.run(["gh", *args], self.cwd)
        if proc.returncode != 0:
            raise GateError(f"gh {' '.join(args[:3])} failed: {(proc.stderr or '').strip()[:200]}")
        try:
            return json.loads(proc.stdout or "null")
        except ValueError as exc:
            raise GateError(f"gh {' '.join(args[:3])} returned no JSON") from exc

    def gh_json_soft(self, args: list[str]) -> object:
        try:
            return self.gh_json(args)
        except GateError:
            return None

    @property
    def base(self) -> str:
        return str(self.config.get("base") or "main")

    def freeze(self, exempt: int | None) -> merge_freeze.Freeze | None:
        """The active merge freeze, cached for ten minutes per gate process."""
        if self._freeze is None or self.now() - self._freeze[0] > 600:
            found = merge_freeze.freezes(self.repo, self.gh_json_soft)
            self._freeze = (self.now(), found)
        for freeze in self._freeze[1]:  # type: ignore[union-attr]
            if not freeze.expired and freeze.number != exempt:
                return freeze
        return None


@dataclass
class Verdict:
    verdict: str
    reason: str
    next: str = ""
    branch: str = ""
    pr: int | None = None
    sha: str = ""
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # True when the branch needs no more watching (landed, deleted, closed).
    forget: bool = False

    @property
    def may_stop(self) -> bool:
        return self.verdict in MAY_STOP


def repo_from_url(url: str) -> str:
    match = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else ""


def load_config(root: Path) -> dict:
    config = dict(DEFAULT_CONFIG)
    path = root / CONFIG_PATH
    try:
        config.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return config


def worktrees(ctx: Ctx) -> dict[str, Path]:
    """branch name -> worktree path, from ``git worktree list --porcelain``."""
    out = ctx.git_out("worktree", "list", "--porcelain") or ""
    found: dict[str, Path] = {}
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line.startswith("branch refs/heads/") and path is not None:
            found[line[len("branch refs/heads/") :]] = path
    return found


def is_ancestor(ctx: Ctx, older: str, newer: str, cwd: Path | None = None) -> bool:
    return ctx.git("merge-base", "--is-ancestor", older, newer, cwd=cwd).returncode == 0


# --------------------------------------------------------------------------
# Which branches belong to this session
# --------------------------------------------------------------------------


def _command_strings(node: object, inside: bool = False):  # noqa: ANN202
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _command_strings(value, inside or key in _COMMAND_KEYS)
    elif isinstance(node, list):
        for value in node:
            yield from _command_strings(value, inside)
    elif inside and isinstance(node, str):
        yield node


def branches_in_transcript(text: str) -> list[str]:
    """Branches the session created or pushed, in order of first mention."""
    found: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not any(word in line for word in ("worktree", "checkout", "switch", "push")):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        for command in _command_strings(record):
            for pattern in _BRANCH_PATTERNS:
                for match in pattern.finditer(command):
                    name = match.group(1).rstrip(".")
                    if name and name not in found:
                        found.append(name)
    return found


# --------------------------------------------------------------------------
# Session state (budget, remembered branches, holds)
# --------------------------------------------------------------------------


def _state_root(ctx: Ctx) -> Path | None:
    return ctx.common_dir / STATE_DIR if ctx.common_dir else None


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]", "_", name)[:120]


def load_state(ctx: Ctx, session: str) -> dict:
    root = _state_root(ctx)
    if not root or not session:
        return {}
    try:
        return json.loads((root / "sessions" / f"{_safe(session)}.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(ctx: Ctx, session: str, state: dict) -> None:
    root = _state_root(ctx)
    if not root or not session:
        return
    path = root / "sessions" / f"{_safe(session)}.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=1), encoding="utf-8")
    except OSError:
        pass


def hold_path(ctx: Ctx, branch: str) -> Path | None:
    root = _state_root(ctx)
    return root / "holds" / f"{_safe(branch)}.json" if root else None


def read_hold(ctx: Ctx, branch: str) -> str | None:
    path = hold_path(ctx, branch)
    try:
        return str(json.loads(path.read_text("utf-8")).get("reason") or "on hold") if path else None
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# One branch
# --------------------------------------------------------------------------


def classify_checks(rollup: list[dict], required: list[str]) -> tuple[list[str], list[str], bool]:
    """(failed names, pending names, every required check present and passed)."""
    failed: list[str] = []
    pending: list[str] = []
    seen: dict[str, str] = {}
    for check in rollup or []:
        name = str(check.get("name") or check.get("context") or "?")
        state = str(check.get("conclusion") or check.get("state") or "").upper()
        status = str(check.get("status") or "").upper()
        if status and status != "COMPLETED" and state not in _FAILED | _PASSED:
            pending.append(name)
            seen[name] = "pending"
        elif state in _FAILED:
            failed.append(name)
            seen[name] = "failed"
        elif state in _PASSED:
            seen[name] = "passed"
        else:
            pending.append(name)
            seen[name] = "pending"
    if required:
        green = all(seen.get(name) == "passed" for name in required)
    else:
        green = bool(seen) and not failed and not pending
    return failed, pending, green


def own_changes(porcelain: str, ignored: list[str]) -> tuple[list[str], list[str]]:
    """(tracked, untracked) changed paths from ``git status --porcelain``.

    Build output and runtime folders (``ignore_dirty`` in the config) change
    on every local build or app run; they are nobody's unfinished work.
    """
    tracked: list[str] = []
    untracked: list[str] = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if any(fnmatch.fnmatch(path, glob) for glob in ignored):
            continue
        (untracked if line.startswith("??") else tracked).append(path)
    return tracked, untracked


def parked_run(ctx: Ctx, sha: str) -> int | None:
    data = ctx.gh_json_soft(["api", f"repos/{ctx.repo}/actions/runs?head_sha={sha}&per_page=30"])
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    for run in runs:
        if run.get("conclusion") == "action_required":
            return int(run.get("id") or 0) or None
    return None


def in_merge_queue(ctx: Ctx, number: int) -> bool:
    owner, name = ctx.repo.split("/", 1)
    query = (
        "query($o:String!,$n:String!,$p:Int!){repository(owner:$o,name:$n)"
        "{pullRequest(number:$p){mergeQueueEntry{state}}}}"
    )
    data = ctx.gh_json_soft(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"o={owner}",
            "-f",
            f"n={name}",
            "-F",
            f"p={number}",
        ]
    )
    try:
        return bool(data["data"]["repository"]["pullRequest"]["mergeQueueEntry"])  # type: ignore[index]
    except (KeyError, TypeError):
        return False


def main_ci_state(ctx: Ctx, sha: str) -> tuple[str, str]:
    """('success'|'pending'|'failure', detail) for the main workflows at ``sha``.

    A failed or cancelled run for ``sha`` is forgiven when a later main commit
    that contains ``sha`` has a green run of the same workflow.
    """
    workflows = [str(w) for w in ctx.config.get("main_workflows") or []]
    data = ctx.gh_json(
        ["api", f"repos/{ctx.repo}/actions/runs?branch={ctx.base}&event=push&per_page=100"]
    )
    runs = data.get("workflow_runs", []) if isinstance(data, dict) else []
    if workflows:
        runs = [r for r in runs if r.get("path") in workflows or r.get("name") in workflows]
    by_workflow: dict[str, list[dict]] = {}
    for run in runs:
        by_workflow.setdefault(str(run.get("path") or run.get("name")), []).append(run)
    own = {
        key: [r for r in group if r.get("head_sha") == sha] for key, group in by_workflow.items()
    }
    expected = set(workflows) if workflows else {key for key, group in own.items() if group}
    if not expected:
        return "pending", f"no main CI run for {sha[:10]} yet"
    ctx.git("fetch", "--quiet", "origin", ctx.base)
    failures: list[str] = []
    pending: list[str] = []
    for key in sorted(expected):
        group = by_workflow.get(key, [])
        mine = sorted(own.get(key, []), key=lambda r: r.get("created_at") or "", reverse=True)
        if any(r.get("conclusion") in _RUN_OK for r in mine):
            continue
        later_green = [
            r
            for r in group
            if r.get("conclusion") in _RUN_OK
            and r.get("head_sha") != sha
            and is_ancestor(ctx, sha, str(r.get("head_sha")))
        ]
        if later_green:
            continue
        label = (mine[0].get("name") if mine else key) or key
        if not mine or any(r.get("status") in _RUN_ACTIVE for r in mine):
            pending.append(str(label))
        elif mine[0].get("conclusion") in ("cancelled", "skipped", None):
            pending.append(f"{label} (cancelled; waiting for a later green main run)")
        else:
            failures.append(f"{label}: {mine[0].get('html_url', '')}")
    if failures:
        return "failure", "; ".join(failures)
    if pending:
        return "pending", ", ".join(pending)
    return "success", ""


def index_lock(checkout: Path) -> Path | None:
    """The ``index.lock`` of the work tree at ``checkout`` (a main or a linked worktree)."""
    dot_git = checkout / ".git"
    if dot_git.is_dir():
        return dot_git / "index.lock"
    try:
        text = dot_git.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    git_dir = Path(text[len("gitdir:") :].strip())
    return (git_dir if git_dir.is_absolute() else checkout / git_dir) / "index.lock"


def sync_local_main(ctx: Ctx, sha: str) -> tuple[bool, str]:
    """D5: make the local main contain ``sha``. Never stashes, never resets."""
    base = ctx.base
    trees = worktrees(ctx)
    if (
        f"refs/heads/{base}"
        and ctx.git_out("rev-parse", "--verify", "--quiet", f"refs/heads/{base}") is None
    ):
        return True, f"no local {base} branch"
    if is_ancestor(ctx, sha, f"refs/heads/{base}"):
        return True, ""
    ctx.git("fetch", "--quiet", "origin", base)
    checkout = trees.get(base)
    if checkout is None:
        ctx.git("fetch", "--quiet", "origin", f"{base}:{base}")
    else:
        lock = index_lock(checkout)
        if lock is not None and lock.exists():
            # Another git command (the app following main, a person's pull) is
            # writing that checkout, or one was killed: either way, not ours to touch.
            return False, (
                f"the local {base} at {checkout} is being updated by another git command; "
                f"left as it is"
            )
        ctx.git(
            "merge",
            "--ff-only",
            "--quiet",
            f"origin/{base}",
            cwd=checkout,
            timeout=GIT_WRITE_TIMEOUT_S,
        )
    if is_ancestor(ctx, sha, f"refs/heads/{base}"):
        return True, f"fast-forwarded the local {base}"
    where = f" at {checkout}" if checkout else ""
    return False, (
        f"the local {base} checkout{where} could not be fast-forwarded (local edits or "
        f"commits of its own); it was left untouched"
    )


def evaluate_branch(ctx: Ctx, branch: str, worktree: Path | None) -> Verdict:
    base = ctx.base
    held = read_hold(ctx, branch)
    if held:
        return Verdict("HOLD", f"branch {branch} is on hold: {held}", branch=branch)
    local = ctx.git_out("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    if local is None:
        return Verdict(
            "NONE", f"branch {branch} does not exist locally", branch=branch, forget=True
        )
    dirty = ""
    untracked: list[str] = []
    if worktree is not None:
        # Not git_out: stripping would eat the leading status column.
        proc = ctx.git("status", "--porcelain", cwd=worktree)
        status = proc.stdout if proc.returncode == 0 else ""
        ignored = [str(glob) for glob in ctx.config.get("ignore_dirty") or []]
        tracked, untracked = own_changes(status, ignored)
        if tracked:
            # `status` also lists files whose only change is a line ending or
            # a timestamp; `diff` compares content after normalization.
            diff = ctx.git("diff", "--name-only", "HEAD", cwd=worktree)
            if diff.returncode == 0:
                changed = set(diff.stdout.split("\n"))
                tracked = [path for path in tracked if path in changed]
        dirty = "\n".join(tracked)
    where = f" in {worktree}" if worktree else ""
    place = str(worktree) if worktree else "its worktree"
    ahead = int(ctx.git_out("rev-list", "--count", f"origin/{base}..refs/heads/{branch}") or 0)
    listed = ctx.gh_json(
        [
            "pr",
            "list",
            "-R",
            ctx.repo,
            "--head",
            branch,
            "--state",
            "all",
            "--limit",
            "5",
            "--json",
            "number,state,isDraft,labels,headRefOid,mergeCommit,mergeStateStatus,"
            "autoMergeRequest,statusCheckRollup,title,isCrossRepository",
        ]
    )
    # A fork's PR can share the branch name; only this repository's own count.
    candidates = listed if isinstance(listed, list) else []
    own = [p for p in candidates if not p.get("isCrossRepository")]
    prs = sorted(own, key=lambda p: -int(p.get("number", 0)))
    pr = prs[0] if prs else None
    checks = {"D1": not dirty}
    loose = ""
    if untracked:
        more = " ..." if len(untracked) > 5 else ""
        loose = f"untracked files{where} are in no commit: {', '.join(untracked[:5])}{more}"

    if pr is None:
        if ahead == 0 and not dirty:
            idle = Verdict("NONE", f"branch {branch} has nothing to land", branch=branch)
            if loose:
                idle.notes.append(loose)
            return idle
        what = (
            "uncommitted changes"
            if ahead == 0
            else f"{ahead} commit(s) that are in no pull request"
        )
        return Verdict(
            "FIX",
            f"branch {branch}{where} has {what}",
            next=f"Commit your own paths and land the branch: run `{LAND_HINT}` in {place}.",
            branch=branch,
            checks=checks,
        )

    number = int(pr["number"])
    head = str(pr.get("headRefOid") or "")
    labels = {str(label.get("name")) for label in pr.get("labels") or []}
    state = str(pr.get("state") or "")
    verdict = Verdict("WAIT", "", branch=branch, pr=number, checks=checks)

    if dirty:
        verdict.verdict, verdict.reason = "FIX", f"uncommitted changes{where} (PR #{number})"
        verdict.next = (
            f"Commit them and push with `{LAND_HINT}`, or revert them if they are not yours."
        )
        return verdict

    # D2: the remote PR head must contain every local commit.
    pushed = local == head
    if not pushed and head:
        if ctx.git("cat-file", "-e", f"{head}^{{commit}}").returncode != 0:
            ctx.git("fetch", "--quiet", "origin", f"pull/{number}/head")
        pushed = is_ancestor(ctx, local, head)
    checks["D2"] = pushed

    if state == "CLOSED":
        if pushed:
            return Verdict(
                "NONE",
                f"PR #{number} was closed without merging",
                branch=branch,
                pr=number,
                forget=True,
            )
        verdict.verdict, verdict.reason = (
            "FIX",
            f"PR #{number} is closed and {branch} has newer commits",
        )
        verdict.next = f"Land the new commits in a new pull request: run `{LAND_HINT}` in {place}."
        return verdict

    if not pushed:
        after = " after it merged" if state == "MERGED" else ""
        verdict.verdict = "FIX"
        verdict.reason = f"{branch} has local commits that are not in PR #{number}{after}"
        verdict.next = f"Push them: run `{LAND_HINT}` in {place}."
        return verdict

    if state == "OPEN":
        checks["D3"] = False
        if pr.get("isDraft") or labels & OPT_OUT_LABELS:
            why = (
                "a draft"
                if pr.get("isDraft")
                else "labelled " + ", ".join(sorted(labels & OPT_OUT_LABELS))
            )
            return Verdict(
                "HOLD", f"PR #{number} is {why}", branch=branch, pr=number, checks=checks
            )
        required = [str(name) for name in ctx.config.get("required_checks") or []]
        failed, pending, green = classify_checks(pr.get("statusCheckRollup") or [], required)
        merge_state = str(pr.get("mergeStateStatus") or "")
        freeze = None if merge_freeze.FREEZE_LABEL in labels else ctx.freeze(exempt=number)
        if merge_state == "DIRTY":
            verdict.verdict, verdict.reason = "FIX", f"PR #{number} conflicts with {base}"
            verdict.next = (
                f"Run `{LAND_HINT}` in {place}: it rebases onto {base} and "
                "resolves generated files; resolve the rest yourself."
            )
            return verdict
        if required and any(name in failed for name in required) or (not required and failed):
            verdict.verdict = "FIX"
            verdict.reason = f"PR #{number} has failing checks: {', '.join(failed)}"
            verdict.next = (
                f"Read the failures (`gh pr checks {number}`), fix them on {branch}, "
                f"push with `{LAND_HINT}`."
            )
            return verdict
        if not green:
            if not pending and not failed:
                run_id = parked_run(ctx, head)
                if run_id:
                    verdict.verdict = "FIX"
                    verdict.reason = f"the CI run of PR #{number} waits for approval"
                    approve = f"repos/{ctx.repo}/actions/runs/{run_id}/approve"
                    verdict.next = f"Approve it: `gh api -X POST {approve}`."
                    return verdict
            early = f"; already failed: {', '.join(failed)}" if failed else ""
            verdict.reason = f"CI is running on PR #{number}{early}"
            verdict.next = f"Wait for it: `{GATE_HINT} --wait`." + (
                " You can start fixing the failed jobs now." if failed else ""
            )
            return verdict
        if freeze is not None:
            verdict.reason = f"PR #{number} is green; {merge_freeze.describe(freeze)}"
            verdict.next = f"Do not request auto-merge yet. Wait: `{GATE_HINT} --wait`."
            return verdict
        if pr.get("autoMergeRequest") is None and not in_merge_queue(ctx, number):
            verdict.verdict = "FIX"
            verdict.reason = f"PR #{number} is green but neither queued nor set to auto-merge"
            verdict.next = f"Request it: `gh pr merge {number} --auto --squash`."
            return verdict
        verdict.reason = f"PR #{number} is green and on its way into the merge queue"
        verdict.next = f"Wait for the merge: `{GATE_HINT} --wait`."
        return verdict

    # MERGED
    checks["D3"] = True
    sha = str((pr.get("mergeCommit") or {}).get("oid") or "")
    verdict.sha = sha
    if not sha:
        verdict.reason = f"PR #{number} merged; its merge commit is not visible yet"
        verdict.next = f"Wait: `{GATE_HINT} --wait`."
        return verdict
    ci, detail = main_ci_state(ctx, sha)
    checks["D4"] = ci == "success"
    if ci == "failure":
        verdict.verdict = "FIX"
        verdict.reason = (
            f"CI on {base} is red for the merge commit {sha[:10]} of PR #{number}: {detail}"
        )
        verdict.next = (
            "Find the cause; if it is this change, land a fix (or a revert) in a new pull "
            f"request from a fresh branch off origin/{base}."
        )
        return verdict
    if ci == "pending":
        verdict.reason = (
            f"PR #{number} merged; CI on {base} is still running for {sha[:10]} ({detail})"
        )
        verdict.next = f"Wait for it: `{GATE_HINT} --wait`."
        return verdict
    ok, note = sync_local_main(ctx, sha)
    checks["D5"] = ok
    done = Verdict(
        "DONE",
        f"PR #{number} merged, CI on {base} green for {sha[:10]}",
        branch=branch,
        pr=number,
        sha=sha,
        checks=checks,
        forget=True,
    )
    if note:
        done.notes.append(note)
    if loose:
        done.notes.append(loose)
    return done


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


def session_branches(ctx: Ctx, transcript: Path | None, state: dict) -> list[str]:
    branches: list[str] = list(state.get("branches") or [])
    current = ctx.git_out("rev-parse", "--abbrev-ref", "HEAD")
    if current and current not in ("HEAD", ctx.base) and current not in branches:
        branches.insert(0, current)
    if transcript is not None:
        try:
            with transcript.open("rb") as handle:
                offset = int(state.get("scanned", 0) or 0)
                if offset > transcript.stat().st_size:
                    offset = 0
                handle.seek(offset)
                data = handle.read()
                # Stop at the last full line: a half-written record is read next time.
                cut = data.rfind(b"\n") + 1
                text = data[:cut].decode("utf-8", "replace")
                state["scanned"] = offset + cut
        except OSError:
            text = ""
        for name in branches_in_transcript(text):
            if name not in branches and name != ctx.base:
                branches.append(name)
    state["branches"] = branches
    return branches


def evaluate(ctx: Ctx, transcript: Path | None = None, state: dict | None = None) -> Verdict:
    state = state if state is not None else {}
    top = ctx.git_out("rev-parse", "--show-toplevel")
    if top is None:
        return Verdict("NONE", f"{ctx.cwd} is not a git repository")
    common = ctx.git_out("rev-parse", "--path-format=absolute", "--git-common-dir")
    ctx.common_dir = Path(common) if common else None
    ctx.config = load_config(Path(top))
    ctx.repo = repo_from_url(ctx.git_out("remote", "get-url", "origin") or "")
    branches = session_branches(ctx, transcript, state)
    if not branches:
        return Verdict("NONE", "no branch work in this session")
    if not ctx.repo:
        return Verdict("NONE", "origin is not a GitHub repository; nothing to check")
    ctx.git("fetch", "--quiet", "origin", ctx.base)
    trees = worktrees(ctx)
    results = [evaluate_branch(ctx, name, trees.get(name)) for name in branches]
    # Landed, deleted or closed branches are forgotten; an empty new branch is
    # kept, since its commits may arrive by a push the transcript never shows.
    state["branches"] = [r.branch for r in results if not r.forget]
    worst = max(results, key=lambda r: SEVERITY[r.verdict])
    others = [r for r in results if r is not worst and r.verdict in MUST_CONTINUE]
    if others:
        worst.notes.append("also: " + "; ".join(f"{r.verdict} {r.reason}" for r in others))
    for result in results:
        if result.verdict == "DONE" and result is not worst:
            worst.notes.extend(result.notes)
    return worst


def apply_budget(ctx: Ctx, verdict: Verdict, state: dict) -> Verdict:
    """Turn a WAIT/FIX that does not move into STUCK, so a session can end."""
    if verdict.verdict not in MUST_CONTINUE:
        state.pop("budget", None)
        return verdict
    now = ctx.now()
    if verdict.verdict == "WAIT":
        key = "WAIT"
    else:
        key = "FIX:" + hashlib.sha1(verdict.reason.encode("utf-8")).hexdigest()[:12]  # noqa: S324
    budget = state.get("budget") or {}
    if budget.get("key") != key:
        budget = {"key": key, "since": now, "blocks": 0}
    budget["blocks"] = int(budget.get("blocks", 0)) + 1
    state["budget"] = budget
    wait_limit = float(ctx.config.get("wait_budget_hours", 3.0)) * 3600
    fix_limit = int(ctx.config.get("fix_budget_blocks", 8))
    over = (key == "WAIT" and now - float(budget["since"]) > wait_limit) or (
        key != "WAIT" and budget["blocks"] > fix_limit
    )
    if not over:
        return verdict
    stuck = Verdict(
        "STUCK",
        f"{verdict.verdict} did not move: {verdict.reason}",
        next="Stop and tell the user exactly what is blocking and what you tried.",
        branch=verdict.branch,
        pr=verdict.pr,
        sha=verdict.sha,
        checks=verdict.checks,
        notes=verdict.notes,
    )
    return stuck


def message(verdict: Verdict) -> str:
    lines = [f"Agent done gate: {verdict.verdict}: {verdict.reason}."]
    if verdict.next:
        lines.append(verdict.next)
    lines.extend(f"Note: {note}." for note in verdict.notes)
    if verdict.verdict in MUST_CONTINUE:
        lines.append(
            f"You are done when `{GATE_HINT}` says DONE. Only if the user told you not to land "
            f'this branch: `{GATE_HINT} --hold "<their words>"`.'
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def check(
    ctx: Ctx,
    *,
    session: str = "",
    transcript: Path | None = None,
    wait_seconds: float = 0,
    budget: bool = True,
) -> Verdict:
    state = {}
    # The state lives in the git common dir, known only after the first look.
    probe = ctx.git_out("rev-parse", "--path-format=absolute", "--git-common-dir")
    ctx.common_dir = Path(probe) if probe else None
    state = load_state(ctx, session)
    verdict = evaluate(ctx, transcript, state)
    deadline = ctx.now() + wait_seconds
    first_key = (verdict.verdict, verdict.reason)
    poll = float(ctx.config.get("poll_seconds", 90))
    while verdict.verdict == "WAIT" and ctx.now() + poll <= deadline:
        time.sleep(poll)
        verdict = evaluate(ctx, None, state)
        if (verdict.verdict, verdict.reason) != first_key:
            break
    if budget and session:
        verdict = apply_budget(ctx, verdict, state)
    # Read by the desktop app (pane status) without asking GitHub again.
    state["last"] = {
        "verdict": verdict.verdict,
        "reason": verdict.reason,
        "next": verdict.next,
        "pr": verdict.pr,
        "branch": verdict.branch,
        "cwd": str(ctx.cwd),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    save_state(ctx, session, state)
    return verdict


def hook_output(cli: str, verdict: Verdict) -> tuple[str, str, int]:
    """(stdout, stderr, exit code) in the CLI's own Stop-hook dialect."""
    text = message(verdict)
    if cli in ("claude", "codex"):
        if verdict.verdict in MUST_CONTINUE:
            return json.dumps({"decision": "block", "reason": text}), "", 0
        if verdict.verdict in ("DONE", "STUCK", "HOLD") or verdict.notes:
            return json.dumps({"systemMessage": text}), "", 0
        return "", "", 0
    if cli == "kimi":
        if verdict.verdict in MUST_CONTINUE:
            return "", text, 2
        return text if verdict.verdict != "NONE" else "", "", 0
    raise ValueError(f"unknown hook dialect {cli!r}")


def _set_hold(ctx: Ctx, reason: str | None) -> int:
    branch = ctx.git_out("rev-parse", "--abbrev-ref", "HEAD") or ""
    common = ctx.git_out("rev-parse", "--path-format=absolute", "--git-common-dir")
    ctx.common_dir = Path(common) if common else None
    path = hold_path(ctx, branch)
    if not branch or branch == "HEAD" or path is None:
        print("No branch checked out here; nothing to hold.")
        return 2
    if reason is None:
        path.unlink(missing_ok=True)
        print(f"Released {branch}: the gate checks it again.")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    path.write_text(json.dumps({"reason": reason, "since": stamp}), encoding="utf-8")
    print(f"{branch} is on hold ({reason}). Tell the user it was not landed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cwd", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--wait", nargs="?", type=float, const=540.0, default=0.0)
    parser.add_argument("--hook", choices=("claude", "codex", "kimi"))
    parser.add_argument("--session", default="")
    parser.add_argument("--transcript", type=Path, default=None)
    parser.add_argument("--hold", metavar="REASON")
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    payload: dict = {}
    if args.hook:
        try:
            payload = json.loads(sys.stdin.read() or "{}")
        except ValueError:
            payload = {}
    cwd = args.cwd or Path(payload.get("cwd") or os.getcwd())
    ctx = Ctx(cwd=cwd)
    if args.hold is not None or args.release:
        return _set_hold(ctx, None if args.release else args.hold)

    session = args.session or str(payload.get("session_id") or "")
    transcript = args.transcript or (
        Path(payload["transcript_path"]) if payload.get("transcript_path") else None
    )
    wait = args.wait
    if args.hook and not wait:
        wait = float(load_config(cwd).get("hook_wait_seconds", 480))
    try:
        verdict = check(
            ctx,
            session=session,
            transcript=transcript,
            wait_seconds=wait,
            budget=bool(args.hook or session),
        )
    except Exception as exc:  # noqa: BLE001 - fail open, always
        verdict = Verdict("NONE", f"the gate could not check ({type(exc).__name__}: {exc})")
        verdict.notes.append("gate error; the session may stop, but nothing was verified")

    if args.hook:
        out, err, code = hook_output(args.hook, verdict)
        if out:
            print(out)
        if err:
            print(err, file=sys.stderr)
        return code
    if args.json:
        extra = {"may_stop": verdict.may_stop, "message": message(verdict)}
        print(json.dumps(asdict(verdict) | extra, indent=1))
    else:
        print(message(verdict))
    return EXIT_STOP if verdict.may_stop else EXIT_CONTINUE


if __name__ == "__main__":
    sys.exit(main())
