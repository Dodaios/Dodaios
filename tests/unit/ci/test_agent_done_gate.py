"""`scripts/agent_done_gate.py`: an agent may stop only when its work has landed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import agent_done_gate as gate
from scripts.ci import merge_freeze

REPO = "acme/widget"
MAIN_SHA = "m" * 40
MERGE_SHA = "s" * 40
HEAD_SHA = "h" * 40


class FakeWorld:
    """Answers the git and gh commands the gate runs, from plain fields."""

    def __init__(self, tmp: Path) -> None:
        self.top = tmp / "repo"
        self.common = tmp / "repo" / ".git"
        self.common.mkdir(parents=True, exist_ok=True)
        self.current = "main"
        self.trees: dict[str, Path] = {"main": self.top}
        self.local: dict[str, str] = {"main": MAIN_SHA}
        self.ahead: dict[str, int] = {}
        self.status: dict[Path, str] = {}
        self.eol_only: set[str] = set()
        self.prs: dict[str, list[dict]] = {}
        self.ancestors: set[tuple[str, str]] = set()
        self.main_runs: list[dict] = []
        self.freeze_prs: list[dict] = []
        self.freeze_events: dict[int, list[dict]] = {}
        self.parked: list[dict] = []
        self.queued: set[int] = set()
        self.ff_works = True
        self.is_repo = True
        self.commands: list[list[str]] = []
        self.timeouts: list[tuple[list[str], float | None]] = []

    def ok(self, cmd: list[str], out: object = "") -> subprocess.CompletedProcess:
        text = out if isinstance(out, str) else json.dumps(out)
        return subprocess.CompletedProcess(cmd, 0, text, "")

    def fail(self, cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(cmd, 1, "", "no")

    def __call__(
        self, cmd: list[str], cwd: Path | None = None, timeout: float | None = None
    ) -> subprocess.CompletedProcess:
        self.commands.append(cmd)
        self.timeouts.append((cmd, timeout))
        if cmd[0] == "git":
            return self.git(cmd, cmd[1:], cwd)
        return self.gh(cmd, cmd[1:])

    def git(self, cmd: list[str], args: list[str], cwd: Path | None) -> subprocess.CompletedProcess:
        if not self.is_repo:
            return self.fail(cmd)
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            return self.ok(cmd, str(self.top))
        if args[:3] == ["rev-parse", "--path-format=absolute", "--git-common-dir"]:
            return self.ok(cmd, str(self.common))
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return self.ok(cmd, self.current)
        if args[:3] == ["rev-parse", "--verify", "--quiet"]:
            name = args[3].removeprefix("refs/heads/")
            return self.ok(cmd, self.local[name]) if name in self.local else self.fail(cmd)
        if args[:2] == ["remote", "get-url"]:
            return self.ok(cmd, f"https://github.com/{REPO}.git")
        if args[:3] == ["worktree", "list", "--porcelain"]:
            lines = []
            for branch, path in self.trees.items():
                lines += [f"worktree {path}", "HEAD x", f"branch refs/heads/{branch}", ""]
            return self.ok(cmd, "\n".join(lines))
        if args[:2] == ["status", "--porcelain"]:
            return self.ok(cmd, self.status.get(cwd, ""))
        if args[:3] == ["diff", "--name-only", "HEAD"]:
            lines = self.status.get(cwd, "").splitlines()
            paths = [line[3:] for line in lines if not line.startswith("??")]
            return self.ok(cmd, "\n".join(p for p in paths if p not in self.eol_only))
        if args[:2] == ["rev-list", "--count"]:
            name = args[2].split("refs/heads/")[-1]
            return self.ok(cmd, str(self.ahead.get(name, 0)))
        if args[:2] == ["merge-base", "--is-ancestor"]:
            older, newer = args[2], args[3]
            if older == newer or (older, newer) in self.ancestors:
                return self.ok(cmd)
            return self.fail(cmd)
        if args[:2] == ["merge", "--ff-only"]:
            if self.ff_works:
                self.ancestors.add((MERGE_SHA, "refs/heads/main"))
                return self.ok(cmd)
            return self.fail(cmd)
        if args[:2] == ["cat-file", "-e"]:
            return self.ok(cmd)
        if args[0] == "fetch":
            return self.ok(cmd)
        raise AssertionError(f"unexpected git {args}")

    def gh(self, cmd: list[str], args: list[str]) -> subprocess.CompletedProcess:
        if args[:2] == ["pr", "list"] and "--head" in args:
            return self.ok(cmd, self.prs.get(args[args.index("--head") + 1], []))
        if args[:2] == ["pr", "list"] and "--label" in args:
            return self.ok(cmd, self.freeze_prs)
        if args[0] == "api" and args[1].startswith(f"repos/{REPO}/issues/"):
            number = int(args[1].split("/")[4])
            return self.ok(cmd, self.freeze_events.get(number, []))
        if args[0] == "api" and "actions/runs?branch=" in args[1]:
            return self.ok(cmd, {"workflow_runs": self.main_runs})
        if args[0] == "api" and "actions/runs?head_sha=" in args[1]:
            return self.ok(cmd, {"workflow_runs": self.parked})
        if args[:2] == ["api", "graphql"]:
            number = int(next(a for a in args if a.startswith("p=")).split("=")[1])
            entry = {"state": "QUEUED"} if number in self.queued else None
            return self.ok(
                cmd, {"data": {"repository": {"pullRequest": {"mergeQueueEntry": entry}}}}
            )
        raise AssertionError(f"unexpected gh {args}")

    # helpers -----------------------------------------------------------
    def branch(self, name: str, *, ahead: int = 1, sha: str = HEAD_SHA) -> Path:
        path = self.top.parent / name.replace("/", "-")
        self.trees[name] = path
        self.local[name] = sha
        self.ahead[name] = ahead
        return path

    def pr(self, branch: str, **fields: object) -> dict:
        pr = {
            "number": 7,
            "state": "OPEN",
            "isDraft": False,
            "labels": [],
            "headRefOid": HEAD_SHA,
            "mergeCommit": None,
            "mergeStateStatus": "CLEAN",
            "autoMergeRequest": None,
            "statusCheckRollup": [],
            "title": "feat: x",
        }
        pr.update(fields)
        self.prs[branch] = [pr]
        return pr


def gate_ci(conclusion: str | None, status: str = "COMPLETED") -> dict:
    return {"name": "CI gate", "status": status, "conclusion": conclusion}


def main_run(sha: str, conclusion: str | None, status: str = "completed") -> dict:
    return {
        "path": ".github/workflows/ci.yml",
        "name": "CI",
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "created_at": "2026-10-19T10:00:00Z",
        "html_url": "https://example.invalid/run",
    }


@pytest.fixture
def world(tmp_path: Path) -> FakeWorld:
    world = FakeWorld(tmp_path)
    (world.top / ".github").mkdir(parents=True, exist_ok=True)
    (world.top / gate.CONFIG_PATH).write_text(
        json.dumps(
            {
                "required_checks": ["CI gate"],
                "main_workflows": [".github/workflows/ci.yml"],
                "ignore_dirty": ["app/dist/*"],
            }
        ),
        encoding="utf-8",
    )
    return world


def run_gate(world: FakeWorld, branches: list[str] | None = None) -> gate.Verdict:
    ctx = gate.Ctx(cwd=world.top, run=world)
    return gate.evaluate(ctx, None, {"branches": branches or []})


# --------------------------------------------------------------------------
# NONE / HOLD
# --------------------------------------------------------------------------


def test_outside_a_repository_the_session_may_stop(world: FakeWorld) -> None:
    world.is_repo = False
    assert run_gate(world).verdict == "NONE"


def test_a_session_on_main_with_no_branch_work_stops_at_once_without_asking_github(
    world: FakeWorld,
) -> None:
    verdict = run_gate(world)
    assert verdict.verdict == "NONE"
    assert not any(cmd[0] == "gh" for cmd in world.commands)


def test_a_branch_with_nothing_on_it_needs_no_landing(world: FakeWorld) -> None:
    world.branch("claude/idea", ahead=0)
    assert run_gate(world, ["claude/idea"]).verdict == "NONE"


def test_a_draft_or_an_opted_out_pull_request_is_a_hold(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", isDraft=True)
    assert run_gate(world, ["claude/x"]).verdict == "HOLD"
    world.pr("claude/x", labels=[{"name": "needs-human"}])
    assert run_gate(world, ["claude/x"]).verdict == "HOLD"


def test_a_branch_the_user_put_on_hold_is_not_checked(world: FakeWorld) -> None:
    world.branch("claude/x", ahead=3)
    ctx = gate.Ctx(cwd=world.top, run=world)
    ctx.common_dir = world.common
    path = gate.hold_path(ctx, "claude/x")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"reason": "keep it local"}), encoding="utf-8")
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "HOLD"
    assert "keep it local" in verdict.reason


# --------------------------------------------------------------------------
# FIX
# --------------------------------------------------------------------------


def test_commits_in_no_pull_request_must_be_landed(world: FakeWorld) -> None:
    world.branch("claude/x", ahead=2)
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert "agent_land.py" in verdict.next


def test_uncommitted_work_blocks_but_generated_files_do_not(world: FakeWorld) -> None:
    path = world.branch("claude/x")
    world.pr("claude/x", statusCheckRollup=[gate_ci(None, "IN_PROGRESS")])
    world.status[path] = " M app/dist/bundle.js\n?? app/dist/new.css\n"
    assert run_gate(world, ["claude/x"]).verdict == "WAIT"
    world.status[path] = " M app/dist/bundle.js\n M src/feature.py\n"
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert verdict.checks["D1"] is False


def test_red_required_checks_are_named(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr(
        "claude/x",
        statusCheckRollup=[
            {"name": "tests-linux (6)", "status": "COMPLETED", "conclusion": "FAILURE"},
            gate_ci("FAILURE"),
        ],
    )
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert "tests-linux (6)" in verdict.reason
    assert "gh pr checks 7" in verdict.next


def test_a_conflicting_pull_request_must_be_rebased(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", mergeStateStatus="DIRTY")
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert "conflicts" in verdict.reason


def test_a_green_pull_request_without_auto_merge_must_request_it(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", statusCheckRollup=[gate_ci("SUCCESS")])
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert "gh pr merge 7 --auto --squash" in verdict.next


def test_unpushed_local_commits_must_be_pushed(world: FakeWorld) -> None:
    world.branch("claude/x", sha="l" * 40)
    world.pr("claude/x", statusCheckRollup=[gate_ci("SUCCESS")])
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert verdict.checks["D2"] is False


def test_a_parked_ci_run_must_be_approved(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x")
    world.parked = [{"id": 99, "conclusion": "action_required"}]
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert "actions/runs/99/approve" in verdict.next


def test_red_ci_on_main_for_the_merge_commit_is_the_agents_to_fix(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "failure")]
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "FIX"
    assert verdict.checks["D3"] is True and verdict.checks["D4"] is False


# --------------------------------------------------------------------------
# WAIT
# --------------------------------------------------------------------------


def test_running_ci_means_wait_and_names_early_failures(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr(
        "claude/x",
        statusCheckRollup=[
            {"name": "tests-windows (2)", "status": "COMPLETED", "conclusion": "FAILURE"},
            {"name": "tests-linux (1)", "status": "IN_PROGRESS", "conclusion": None},
        ],
    )
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "WAIT"
    assert "tests-windows (2)" in verdict.reason
    assert "--wait" in verdict.next


def test_a_queued_pull_request_waits(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", statusCheckRollup=[gate_ci("SUCCESS")])
    world.queued.add(7)
    assert run_gate(world, ["claude/x"]).verdict == "WAIT"


def test_a_merge_freeze_by_another_pull_request_means_wait(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", statusCheckRollup=[gate_ci("SUCCESS")])
    world.freeze_prs = [{"number": 733, "title": "package move"}]
    world.freeze_events = {
        733: [
            {
                "event": "labeled",
                "label": {"name": merge_freeze.FREEZE_LABEL},
                "created_at": "2999-01-01T00:00:00Z",
            }
        ]
    }
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "WAIT"
    assert "#733" in verdict.reason
    assert "Do not request auto-merge" in verdict.next


def test_an_expired_freeze_no_longer_holds_main() -> None:
    def gh_json(args: list[str]) -> object:
        if args[:2] == ["pr", "list"]:
            return [{"number": 733, "title": "move"}]
        stamp = "2026-10-19T10:00:00Z"
        return [{"event": "labeled", "label": {"name": "merge-freeze"}, "created_at": stamp}]

    now = merge_freeze.parse_time("2026-10-19T13:00:00Z")
    assert merge_freeze.active_freeze(REPO, gh_json, now=now) is None
    early = merge_freeze.parse_time("2026-10-19T11:00:00Z")
    assert merge_freeze.active_freeze(REPO, gh_json, now=early).number == 733
    assert merge_freeze.active_freeze(REPO, gh_json, now=early, exempt=733) is None


def test_merged_but_main_ci_still_running_waits(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, None, "in_progress")]
    assert run_gate(world, ["claude/x"]).verdict == "WAIT"
    world.main_runs = []
    assert run_gate(world, ["claude/x"]).verdict == "WAIT"


# --------------------------------------------------------------------------
# DONE
# --------------------------------------------------------------------------


def test_merged_green_on_main_and_local_main_fast_forwarded_is_done(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "DONE"
    assert verdict.checks == {"D1": True, "D2": True, "D3": True, "D4": True, "D5": True}
    assert ["git", "merge", "--ff-only", "--quiet", "origin/main"] in world.commands


def test_a_cancelled_main_run_is_forgiven_by_a_later_green_run(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    later = "n" * 40
    world.main_runs = [main_run(MERGE_SHA, "cancelled"), main_run(later, "success")]
    world.ancestors.add((MERGE_SHA, later))
    assert run_gate(world, ["claude/x"]).verdict == "DONE"


def test_a_local_main_with_edits_is_left_alone_and_noted(world: FakeWorld) -> None:
    world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    world.ff_works = False
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "DONE"
    assert verdict.checks["D5"] is False
    assert "left untouched" in verdict.notes[0]


def test_the_fast_forward_of_local_main_is_never_killed_on_a_short_timer(
    world: FakeWorld,
) -> None:
    world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    assert run_gate(world, ["claude/x"]).verdict == "DONE"
    merges = [t for cmd, t in world.timeouts if cmd[1:3] == ["merge", "--ff-only"]]
    assert merges == [gate.GIT_WRITE_TIMEOUT_S] and gate.GIT_WRITE_TIMEOUT_S >= 30 * 60


def test_a_local_main_another_git_command_is_updating_is_left_as_it_is(
    world: FakeWorld,
) -> None:
    world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    (world.top / ".git" / "index.lock").write_bytes(b"")
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "DONE" and verdict.checks["D5"] is False
    assert "being updated by another git command" in verdict.notes[0]
    assert not any(cmd[1:2] == ["merge"] for cmd in world.commands)


def test_the_index_lock_of_a_linked_worktree_is_found_through_its_git_file(
    tmp_path: Path,
) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / ".git").write_text("gitdir: ../repo/.git/worktrees/tree\n", encoding="utf-8")
    assert gate.index_lock(tree) == tree / "../repo/.git/worktrees/tree" / "index.lock"
    (tmp_path / "plain" / ".git").mkdir(parents=True)
    assert gate.index_lock(tmp_path / "plain") == tmp_path / "plain" / ".git" / "index.lock"
    assert gate.index_lock(tmp_path / "nothing") is None


def test_the_worst_branch_decides_for_the_session(world: FakeWorld) -> None:
    world.branch("claude/a")
    world.pr("claude/a", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    world.branch("claude/b", ahead=1)
    verdict = run_gate(world, ["claude/a", "claude/b"])
    assert verdict.verdict == "FIX"
    assert verdict.branch == "claude/b"


# --------------------------------------------------------------------------
# Budget, transcript, hook dialects, fail-open
# --------------------------------------------------------------------------


def test_a_fix_that_does_not_move_becomes_stuck(world: FakeWorld) -> None:
    clock = [1000.0]
    ctx = gate.Ctx(cwd=world.top, run=world, now=lambda: clock[0])
    state: dict = {}
    fix = gate.Verdict("FIX", "same red check")
    results = [gate.apply_budget(ctx, fix, state).verdict for _ in range(9)]
    assert results[:8] == ["FIX"] * 8
    assert results[8] == "STUCK"


def test_a_wait_longer_than_the_budget_becomes_stuck(world: FakeWorld) -> None:
    clock = [0.0]
    ctx = gate.Ctx(cwd=world.top, run=world, now=lambda: clock[0])
    state: dict = {}
    assert gate.apply_budget(ctx, gate.Verdict("WAIT", "ci 1"), state).verdict == "WAIT"
    clock[0] = 2 * 3600
    assert gate.apply_budget(ctx, gate.Verdict("WAIT", "ci 2"), state).verdict == "WAIT"
    clock[0] = 3 * 3600 + 1
    assert gate.apply_budget(ctx, gate.Verdict("WAIT", "queue"), state).verdict == "STUCK"
    assert gate.apply_budget(ctx, gate.Verdict("DONE", "ok"), state).verdict == "DONE"
    assert "budget" not in state


def test_branches_come_from_commands_never_from_tool_output() -> None:
    lines = [
        {
            "type": "tool_use",
            "input": {"command": "git worktree add -q -b claude/one ../one origin/main"},
        },
        {"type": "tool_result", "content": "hint: git checkout -b someone-else"},
        {
            "payload": {
                "item": {
                    "type": "CommandExecution",
                    "command": ["pwsh", "-c", "git switch -c codex/two"],
                }
            }
        },
        {
            "type": "tool_use",
            "input": {"command": "git push -u origin HEAD:refs/heads/claude/three"},
        },
        {"type": "tool_use", "input": {"command": "git worktree add -b <agent>/<topic> <path>"}},
    ]
    text = "\n".join(json.dumps(line) for line in lines)
    assert gate.branches_in_transcript(text) == ["claude/one", "codex/two", "claude/three"]


@pytest.mark.parametrize(
    ("cli", "verdict", "expected_code", "blocks"),
    [
        ("claude", "FIX", 0, True),
        ("codex", "WAIT", 0, True),
        ("claude", "DONE", 0, False),
        ("kimi", "FIX", 2, True),
        ("kimi", "NONE", 0, False),
    ],
)
def test_hook_dialects(cli: str, verdict: str, expected_code: int, blocks: bool) -> None:
    out, err, code = gate.hook_output(cli, gate.Verdict(verdict, "why", next="do this"))
    assert code == expected_code
    if cli in ("claude", "codex"):
        decoded = json.loads(out) if out else {}
        assert (decoded.get("decision") == "block") is blocks
        if blocks:
            assert "do this" in decoded["reason"]
    else:
        assert bool(err) is blocks


def test_a_crashing_gate_lets_the_session_stop(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("gh exploded")

    monkeypatch.setattr(gate, "check", boom)
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps({"cwd": "."})))
    assert gate.main(["--hook", "claude", "--wait", "1"]) == 0
    assert "gh exploded" in capsys.readouterr().out


def test_agent_land_requests_no_auto_merge_during_another_prs_freeze() -> None:
    from scripts import agent_land

    commands: list[list[str]] = []
    view = {"number": 7, "isDraft": False, "labels": []}
    label = {"event": "labeled", "label": {"name": "merge-freeze"}}
    answers = {
        ("pr", "view"): view,
        ("repo", "view"): REPO,
        ("pr", "list"): [{"number": 733, "title": "package move"}],
        ("api", f"repos/{REPO}/issues/733/events?per_page=100&page=1"): [
            label | {"created_at": "2999-01-01T00:00:00Z"}
        ],
    }

    def runner(cmd: list[str], **_: object) -> subprocess.CompletedProcess:
        commands.append(cmd)
        answer = answers.get(tuple(cmd[1:3]))
        if answer is None:
            return subprocess.CompletedProcess(cmd, 1, "", "no")
        text = answer if isinstance(answer, str) else json.dumps(answer)
        return subprocess.CompletedProcess(cmd, 0, text, "")

    assert agent_land.queue_when_green("claude/x", runner) is False
    assert all(cmd[:3] != ["gh", "pr", "merge"] for cmd in commands)


def _freeze_answers(numbers: list[int], stamp: str | None) -> merge_freeze.GhJson:
    def gh_json(args: list[str]) -> object:
        if args[:2] == ["pr", "list"]:
            return [{"number": n, "title": f"pr {n}"} for n in numbers]
        if stamp is None:
            return []
        return [{"event": "labeled", "label": {"name": "merge-freeze"}, "created_at": stamp}]

    return gh_json


def test_two_freezing_pull_requests_do_not_lock_each_other_out() -> None:
    gh_json = _freeze_answers([733, 740], "2026-10-19T10:00:00Z")
    now = merge_freeze.parse_time("2026-10-19T10:30:00Z")
    assert merge_freeze.active_freeze(REPO, gh_json, now=now, exempt=733) is None
    assert merge_freeze.active_freeze(REPO, gh_json, now=now, exempt=740) is None
    assert merge_freeze.active_freeze(REPO, gh_json, now=now, exempt=7) is not None


def test_a_freeze_whose_label_time_is_unknown_does_not_hold_main() -> None:
    gh_json = _freeze_answers([733], None)
    assert merge_freeze.active_freeze(REPO, gh_json) is None


def test_label_events_are_read_across_pages() -> None:
    def gh_json(args: list[str]) -> object:
        page = int(args[1].rsplit("page=", 1)[1])
        if page == 1:
            return [{"event": "commented"}] * 100
        return [{"event": "labeled", "label": {"name": "merge-freeze"}, "created_at": "x"}]

    events = merge_freeze.issue_events(REPO, 1, gh_json)
    assert len(events) == 101


def test_untracked_files_are_a_note_not_an_endless_fix(world: FakeWorld) -> None:
    path = world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    world.status[path] = "?? scratch.log\n"
    verdict = run_gate(world, ["claude/x"])
    assert verdict.verdict == "DONE"
    assert any("scratch.log" in note for note in verdict.notes)


def test_a_line_ending_only_change_is_not_unfinished_work(world: FakeWorld) -> None:
    path = world.branch("claude/x")
    world.pr("claude/x", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    world.status[path] = " M .claude/settings.json\n"
    world.eol_only.add(".claude/settings.json")
    assert run_gate(world, ["claude/x"]).verdict == "DONE"


def test_an_empty_new_branch_is_remembered_until_it_lands(world: FakeWorld) -> None:
    world.branch("claude/new", ahead=0)
    ctx = gate.Ctx(cwd=world.top, run=world)
    state: dict = {"branches": ["claude/new"]}
    assert gate.evaluate(ctx, None, state).verdict == "NONE"
    assert state["branches"] == ["claude/new"]
    world.pr("claude/new", state="MERGED", mergeCommit={"oid": MERGE_SHA})
    world.main_runs = [main_run(MERGE_SHA, "success")]
    assert gate.evaluate(ctx, None, state).verdict == "DONE"
    assert state["branches"] == []


def test_a_half_written_transcript_line_is_read_on_the_next_check(
    world: FakeWorld, tmp_path: Path
) -> None:
    transcript = tmp_path / "t.jsonl"
    full = json.dumps({"input": {"command": "git checkout -b claude/one"}})
    transcript.write_text(full + "\n" + '{"input": {"command": "git checkout -b claude/tw', "utf-8")
    ctx = gate.Ctx(cwd=world.top, run=world)
    state: dict = {}
    assert gate.session_branches(ctx, transcript, state) == ["claude/one"]
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write('o"}}\n')
    assert gate.session_branches(ctx, transcript, state) == ["claude/one", "claude/two"]
