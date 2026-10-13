"""Ownership requires successful creation in this session's own tool record."""

import json
import subprocess
import time
from dataclasses import replace

import pytest

from jarvis.agentic_ide import agent_transcript
from jarvis.agentic_ide import session_branches as branches


def call(args, identity="call", name="exec_command"):
    return {"kind": "tool_call", "payload": {"call_id": identity, "name": name, "input": args}}


def result(output, identity="call", error=False):
    return {
        "kind": "tool_result",
        "ts_ms": 5000,
        "payload": {"call_id": identity, "output": output, "is_error": error},
    }


@pytest.mark.parametrize(
    "command, expected",
    [
        ("git worktree add -b agent/fix ../fork HEAD", "agent/fix"),
        ("git switch -c feature/one", "feature/one"),
        ("git switch --create feature/one", "feature/one"),
        ("git checkout -b feature/two", "feature/two"),
        ("git branch feature/three", "feature/three"),
        ("git switch main", None),
        ("git checkout existing", None),
        ("git branch -D old", None),
        ("git worktree add ../fork existing", None),
        ("git checkout -B existing", None),
        ("echo 'git switch -c fake'", None),
        ("git status", None),
    ],
)
def test_only_creation_commands_count(command, expected, tmp_path):
    found = branches.created_by_command(command, str(tmp_path))
    assert [entry.branch for entry in found] == ([expected] if expected else [])


def test_success_belongs_to_the_call_not_some_other_session(tmp_path):
    command = call({"cmd": "git switch -c owned"})
    assert (
        branches.created_branches(
            [command, result("fatal: already exists", error=True)], str(tmp_path)
        )
        == []
    )
    assert (
        branches.created_branches(
            [command, result("Switched to a new branch 'owned'", "other")], str(tmp_path)
        )
        == []
    )
    found = branches.created_branches(
        [command, result("Switched to a new branch 'owned'")], str(tmp_path)
    )
    assert found[0].branch == "owned" and found[0].created_at == 5


def test_shell_branch_creation_requires_explicit_success(tmp_path):
    args = {"command": "git branch owned"}
    assert (
        branches.created_branches([call(args, name="Bash"), result("nothing")], str(tmp_path)) == []
    )
    assert (
        branches.created_branches(
            [call(args, name="Bash"), result('{"exit_code":0}')], str(tmp_path)
        )[0].branch
        == "owned"
    )


def test_code_mode_literal_arguments_and_windows_paths(tmp_path):
    cwd = str(tmp_path / "a folder")
    source = (
        'text(await tools.exec_command({cmd: "git worktree add -b codex/fix ../fork HEAD", '
        "workdir: " + json.dumps(cwd) + "}));"
    )
    found = branches.created_branches(
        [
            call({"input": source}, name="exec"),
            result("Preparing worktree (new branch 'codex/fix')"),
        ],
        str(tmp_path),
    )
    assert found[0].folder == cwd and found[0].branch == "codex/fix"
    assert (
        branches.created_branches(
            [
                call({"input": source}, name="read_file"),
                result("Preparing worktree (new branch 'codex/fix')"),
            ],
            str(tmp_path),
        )
        == []
    )


def test_directory_changes_and_git_dash_c(tmp_path):
    found = branches.created_by_command(
        'cd "nested folder"; git -C ../other switch -c owned', str(tmp_path)
    )
    assert found[0].folder == str(tmp_path / "other")


def test_workspace_branch_alone_never_gives_ownership(monkeypatch, tmp_path):
    record = branches.PaneBranchRecord("t1", "history", str(tmp_path))
    assert branches.owned_branch(record) is None
    explicit = replace(record, created_branch="fork/owned")
    assert branches.owned_branch(explicit).branch == "fork/owned"


def test_other_sessions_and_unrelated_repositories_are_isolated(monkeypatch, tmp_path):
    branches._cache.clear()
    monkeypatch.setattr(agent_transcript, "can_read", lambda _: True)

    def read(_agent, session, **_):
        if session == "author":
            return [
                call({"cmd": "git switch -c owned"}),
                result("Switched to a new branch 'owned'"),
            ]
        if session == "unrelated":
            return [
                call({"cmd": "git -C /elsewhere switch -c unrelated"}),
                result("Switched to a new branch 'unrelated'"),
            ]
        return []

    monkeypatch.setattr(agent_transcript, "read_events", read)
    monkeypatch.setattr(
        branches, "_common", lambda folder: "same" if folder == str(tmp_path) else "other"
    )
    record = branches.PaneBranchRecord("t1", "history", str(tmp_path), "codex", "author")
    assert branches.owned_branch(record).branch == "owned"
    assert branches.owned_branch(replace(record, session_id="reader")) is None
    assert branches.owned_branch(replace(record, session_id="unrelated")) is None


def test_codex_item_ids_do_not_break_call_result_matching(monkeypatch, tmp_path):
    path = tmp_path / "record.jsonl"
    rows = [
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "id": "ctc_item",
                "call_id": "shared",
                "name": "exec_command",
                "input": json.dumps({"cmd": "git switch -c owned"}),
            },
        },
        {
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "id": "ctco_item",
                "call_id": "shared",
                "output": "Switched to a new branch 'owned'",
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    monkeypatch.setattr(agent_transcript, "_codex_file", lambda *_: path)
    events = agent_transcript.read_events("codex", "session")
    paired = [
        event["payload"]["call_id"]
        for event in events
        if event["kind"] in {"tool_call", "tool_result"}
    ]
    assert paired == ["shared", "shared"]
    assert branches.created_branches(events, str(tmp_path))[0].branch == "owned"


# --- the repository as second witness: every coding CLI, not one output format ---


def timed(command, output, *, name="Bash", started=1000.0, ended=1010.0, identity="call"):
    return [
        {
            "kind": "tool_call",
            "ts_ms": started * 1000,
            "payload": {"call_id": identity, "name": name, "input": {"command": command}},
        },
        {
            "kind": "tool_result",
            "ts_ms": ended * 1000,
            "payload": {"call_id": identity, "output": output, "is_error": False},
        },
    ]


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.invalid", "-c", "user.name=T", *args],
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repository(tmp_path, monkeypatch):
    branches._cache.clear()
    branches._creations.clear()
    monkeypatch.setattr(agent_transcript, "can_read", lambda _: True)
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "commit", "-q", "--allow-empty", "--no-verify", "-m", "chore: seed")
    return tmp_path


def _pane(repo, monkeypatch, events, agent="claude"):
    monkeypatch.setattr(agent_transcript, "read_events", lambda *_, **__: events)
    return branches.PaneBranchRecord("t1", "history", str(repo), agent, "session")


def test_result_that_does_not_name_the_branch_stays_unconfirmed(tmp_path):
    events = timed("git worktree add -b claude/topic ../wt origin/main | tail -1", "HEAD is now")

    assert branches.created_branches(events, str(tmp_path)) == []
    (found,) = branches.created_branches(events, str(tmp_path), unconfirmed=True)
    assert (found.branch, found.confirmed) == ("claude/topic", False)
    assert (found.called_at, found.created_at) == (1000.0, 1010.0)


@pytest.mark.parametrize("tool", ["Bash", "PowerShell", "shell", "run_shell_command"])
def test_every_shell_tool_is_read(tool, tmp_path):
    events = timed("git switch -c owned", "Switched to a new branch 'owned'", name=tool)

    assert [entry.branch for entry in branches.created_branches(events, str(tmp_path))] == ["owned"]


def test_repository_record_confirms_a_filtered_result(repository, monkeypatch):
    started = time.time()
    _git(repository, "branch", "claude/topic")
    events = timed(
        "git worktree add -b claude/topic ../wt main 2>&1 | tail -1",
        "HEAD is now at 1234567 chore: seed",
        started=started - 1,
        ended=time.time() + 1,
    )

    owned = branches.owned_branch(_pane(repository, monkeypatch, events))

    assert owned is not None and owned.branch == "claude/topic"
    assert owned.folder == str(repository)


def test_repository_record_confirms_a_path_this_module_cannot_follow(repository, monkeypatch):
    started = time.time()
    _git(repository, "branch", "owned")
    events = timed(
        'cd "/c/somewhere/else" && git switch -c owned',
        "Switched to a new branch 'owned'",
        started=started - 1,
        ended=time.time() + 1,
    )

    assert branches.owned_branch(_pane(repository, monkeypatch, events)).branch == "owned"


def test_branch_that_existed_before_the_call_is_not_owned(repository, monkeypatch):
    _git(repository, "branch", "claude/topic")
    later = time.time() + 3600
    events = timed(
        "git worktree add -b claude/topic ../wt main | tail -1",
        "nothing useful",
        started=later,
        ended=later + 5,
    )

    assert branches.owned_branch(_pane(repository, monkeypatch, events)) is None


def test_creation_in_another_repository_is_not_owned(repository, monkeypatch):
    now = time.time()
    events = timed("git -C ../elsewhere switch -c owned | tail -1", "", started=now - 1, ended=now)

    assert branches.owned_branch(_pane(repository, monkeypatch, events)) is None


def test_call_without_a_clock_is_never_confirmed_by_the_repository(repository, monkeypatch):
    _git(repository, "branch", "owned")
    events = [call({"command": "git switch -c owned | tail -1"}, name="Bash"), result("")]
    events[1]["ts_ms"] = time.time() * 1000

    assert branches.owned_branch(_pane(repository, monkeypatch, events)) is None
