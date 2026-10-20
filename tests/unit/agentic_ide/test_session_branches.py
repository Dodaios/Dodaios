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


# --- the branch a pane works in: created, changed, or simply checked out ---


def wrote(path, *, name="Edit", at=2000.0, identity="write", key="file_path"):
    return [
        {
            "kind": "tool_call",
            "ts_ms": at * 1000,
            "payload": {"call_id": identity, "name": name, "input": {key: str(path)}},
        },
        {
            "kind": "tool_result",
            "ts_ms": at * 1000,
            "payload": {"call_id": identity, "output": "ok", "is_error": False},
        },
    ]


def test_reading_a_folder_is_not_working_in_it(tmp_path):
    events = timed("git -C ../other log --oneline; git -C ../other diff", "abc")

    assert branches.worked_folders(events, str(tmp_path)) == []


def test_git_writes_and_file_tools_place_the_session(tmp_path):
    events = timed("cd ../wt && git commit -m x", "", ended=1010.0) + wrote(
        tmp_path / "pkg" / "a.py", name="Write"
    )

    assert branches.worked_folders(events, str(tmp_path)) == [
        (str((tmp_path / ".." / "wt").resolve()), 1010.0),
        (str(tmp_path / "pkg"), 2000.0),
    ]


def test_failed_write_places_nobody(tmp_path):
    events = timed("git commit -m x", "nothing to commit")
    events[1]["payload"]["is_error"] = True

    assert branches.worked_folders(events, str(tmp_path)) == []


@pytest.fixture
def feature_checkout(repository):
    branches._repositories.clear()
    checkout = repository / "wt"
    _git(repository, "worktree", "add", "-q", "-b", "feature/x", str(checkout))
    return checkout


@pytest.mark.parametrize(
    "tool, key", [("Edit", "file_path"), ("write_file", "file_path"), ("WriteFile", "path")]
)
def test_pane_works_in_the_branch_of_the_checkout_it_changed(
    repository, feature_checkout, monkeypatch, tool, key
):
    events = wrote(feature_checkout / "pkg" / "a.py", name=tool, key=key)

    found = branches.pane_branch(_pane(repository, monkeypatch, events))

    assert (found.branch, found.created_at) == ("feature/x", 0)


def test_a_commit_in_another_checkout_places_the_pane(repository, feature_checkout, monkeypatch):
    events = timed(f'git -C "{feature_checkout}" commit --allow-empty -m x', "[feature/x 1] x")

    assert branches.pane_branch(_pane(repository, monkeypatch, events)).branch == "feature/x"


def test_default_branch_work_does_not_hide_the_feature_branch(
    repository, feature_checkout, monkeypatch
):
    events = wrote(feature_checkout / "a.py", at=2000.0) + timed(
        "git add README.md", "", started=3000.0, ended=3001.0
    )

    assert branches.pane_branch(_pane(repository, monkeypatch, events)).branch == "feature/x"


def test_pane_without_evidence_gets_the_branch_of_its_folder(
    repository, feature_checkout, monkeypatch
):
    reader = timed("git -C wt log --oneline", "abc")

    assert branches.pane_branch(_pane(repository, monkeypatch, reader)).branch == "main"
    in_checkout = branches.PaneBranchRecord("t2", "other", str(feature_checkout))
    assert branches.pane_branch(in_checkout).branch == "feature/x"


def test_newer_created_branch_wins_and_keeps_its_creation_time(
    repository, feature_checkout, monkeypatch
):
    started = time.time()
    _git(repository, "branch", "claude/topic")
    events = wrote(feature_checkout / "a.py", at=started - 500) + timed(
        "git branch claude/topic | tail -1", "", started=started - 1, ended=time.time() + 1
    )

    found = branches.pane_branch(_pane(repository, monkeypatch, events))

    assert found.branch == "claude/topic" and found.created_at > 0


def test_detached_head_has_no_branch(repository):
    _git(repository, "checkout", "-q", "--detach", "HEAD")

    assert branches.pane_branch(branches.PaneBranchRecord("t1", "h", str(repository))) is None


# --- a session that worked on several branches ---


def _listed(monkeypatch, tmp_path, created, worked, current="current", gone=()):
    folder = str(tmp_path)
    monkeypatch.setattr(
        branches,
        "_own_branch",
        lambda _: branches.PaneBranch(current, folder, 30) if current else None,
    )
    monkeypatch.setattr(
        branches,
        "_creations_of",
        lambda _: iter(
            [
                branches.CreatedBranch(name, folder, at, confirmed=name not in gone)
                for name, at in created
            ]
        ),
    )
    monkeypatch.setattr(branches, "_worked", lambda _: iter(worked))
    monkeypatch.setattr(branches, "_checked_out", lambda _: branches.PaneBranch("main", folder))
    return branches.pane_branches(branches.PaneBranchRecord("t1", "history", folder))


def test_session_lists_its_other_branches_newest_first(monkeypatch, tmp_path):
    listed = _listed(
        monkeypatch,
        tmp_path,
        created=[("current", 30), ("created-early", 10)],
        worked=[("current", 40), ("created-early", 25), ("only-worked", 20)],
    )

    assert [entry.branch for entry in listed] == ["current", "created-early", "only-worked"]
    # The creation time survives: it tells this branch's pull request from an older one.
    assert listed[1].created_at == 10
    assert listed[2].created_at == 0


def test_branch_list_is_capped(monkeypatch, tmp_path):
    created = [(f"branch-{index}", index) for index in reversed(range(20))]

    listed = _listed(monkeypatch, tmp_path, created=created, worked=[])

    assert len(listed) == branches.MAX_PANE_BRANCHES
    assert [entry.branch for entry in listed[:3]] == ["current", "branch-19", "branch-18"]


def test_deleted_branch_is_listed_as_unproven(monkeypatch, tmp_path):
    listed = _listed(monkeypatch, tmp_path, created=[("deleted", 10)], worked=[], gone={"deleted"})

    assert [(entry.branch, entry.unproven) for entry in listed] == [
        ("current", False),
        ("deleted", True),
    ]


def test_finished_branches_stand_in_front_of_the_checked_out_default(monkeypatch, tmp_path):
    listed = _listed(
        monkeypatch, tmp_path, created=[("deleted", 10)], worked=[], current="", gone={"deleted"}
    )

    assert [entry.branch for entry in listed] == ["deleted"]


def test_session_without_a_branch_of_its_own_gets_the_checked_out_one(monkeypatch, tmp_path):
    listed = _listed(monkeypatch, tmp_path, created=[], worked=[], current="")

    assert [entry.branch for entry in listed] == ["main"]


def test_pull_request_opened_inside_the_creating_call_still_counts(monkeypatch, tmp_path):
    folder = str(tmp_path)
    monkeypatch.setattr(branches, "_own_branch", lambda _: None)
    monkeypatch.setattr(
        branches,
        "_creations_of",
        lambda _: iter([branches.CreatedBranch("one-call", folder, 90, called_at=50)]),
    )
    monkeypatch.setattr(branches, "_worked", lambda _: iter([]))

    (listed,) = branches.pane_branches(branches.PaneBranchRecord("t1", "history", folder))

    assert listed.created_at == 50


def test_heredoc_does_not_hide_the_branch_creation_before_it(tmp_path):
    command = (
        "git switch -c claude/topic origin/main\ncat >> notes.md <<'EOF'\nthe pane's note\nEOF"
    )

    found = branches.created_by_command(command, str(tmp_path))

    assert [entry.branch for entry in found] == ["claude/topic"]


def test_deleted_branch_is_passed_on_unconfirmed_and_a_foreign_one_never(repository, monkeypatch):
    now = time.time()
    _git(repository, "branch", "foreign")
    events = [
        *timed("git switch -c deleted | tail -1", "", started=now - 20, ended=now - 19),
        *timed(
            "git switch -c foreign | tail -1",
            "",
            started=now + 3600,
            ended=now + 3601,
            identity="later",
        ),
    ]
    record = _pane(repository, monkeypatch, events)

    found = [(entry.branch, entry.confirmed) for entry in branches._creations_of(record)]

    assert found == [("deleted", False)]
    assert branches.owned_branch(record) is None


def test_a_record_that_has_not_grown_is_not_read_again(tmp_path, monkeypatch):
    branches._cache.clear()
    monkeypatch.setattr(agent_transcript, "can_read", lambda _: True)
    reads = []
    stamps = [(100, 1)]

    def read(*_, **__):
        reads.append(1)
        return [call({"cmd": "git switch -c owned"}), result("Switched to a new branch 'owned'")]

    monkeypatch.setattr(agent_transcript, "read_events", read)
    monkeypatch.setattr(agent_transcript, "stamp", lambda *_, **__: stamps[-1])
    record = branches.PaneBranchRecord("t1", "history", str(tmp_path), "claude", "session")

    def later():
        # Past the short window in which nothing is asked at all.
        for entry in branches._cache.values():
            entry.read_at -= 60

    assert [found.branch for found in branches._evidence(record)[0]] == ["owned"]
    later()
    assert [found.branch for found in branches._evidence(record)[0]] == ["owned"]
    assert len(reads) == 1
    stamps.append((180, 2))
    later()
    branches._evidence(record)
    assert len(reads) == 2


def test_a_record_whose_growth_cannot_be_seen_is_read_again(tmp_path, monkeypatch):
    branches._cache.clear()
    monkeypatch.setattr(agent_transcript, "can_read", lambda _: True)
    reads = []
    monkeypatch.setattr(agent_transcript, "read_events", lambda *_, **__: reads.append(1) or [])
    monkeypatch.setattr(agent_transcript, "stamp", lambda *_, **__: None)
    record = branches.PaneBranchRecord("t1", "history", str(tmp_path), "grok", "session")

    branches._evidence(record)
    branches._evidence(record)
    assert len(reads) == 1
    for entry in branches._cache.values():
        entry.read_at -= 60
    branches._evidence(record)
    assert len(reads) == 2


def test_a_record_that_could_not_be_read_is_not_kept_as_empty(tmp_path, monkeypatch):
    branches._cache.clear()
    monkeypatch.setattr(agent_transcript, "can_read", lambda _: True)
    answers = [None, [call({"cmd": "git switch -c owned"}), result("new branch 'owned'")]]
    monkeypatch.setattr(agent_transcript, "read_events", lambda *_, **__: answers.pop(0))
    monkeypatch.setattr(agent_transcript, "stamp", lambda *_, **__: (100, 1))
    record = branches.PaneBranchRecord("t1", "history", str(tmp_path), "claude", "session")

    assert branches._evidence(record) == ([], [])
    for entry in branches._cache.values():
        entry.read_at -= 60
    # The record itself did not change; the failed read is still not its answer.
    assert [found.branch for found in branches._evidence(record)[0]] == ["owned"]


def test_stamp_follows_the_record_file(tmp_path, monkeypatch):
    path = tmp_path / "session.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(agent_transcript, "_codex_file", lambda *_: path)
    monkeypatch.setattr(agent_transcript, "_claude_file", lambda *_: None)

    first = agent_transcript.stamp("codex", "session")
    assert first is not None and first[0] == path.stat().st_size
    path.write_text("{}\n{}\n", encoding="utf-8")
    assert agent_transcript.stamp("codex", "session") != first
    assert agent_transcript.stamp("claude", "session") is None
    assert agent_transcript.stamp("codex", "") is None
    assert agent_transcript.stamp("unknown-cli", "session") is None


def test_repository_of_a_folder_is_asked_of_git_once(tmp_path, monkeypatch):
    branches._commons.clear()
    asked = []

    def out(args, cwd):
        asked.append(args)
        return ".git\n"

    monkeypatch.setattr(branches.git_overview, "_out", out)
    assert branches._common(str(tmp_path)) == branches._common(str(tmp_path)) != ""
    assert len(asked) == 1


def test_a_folder_git_gave_no_answer_for_is_asked_again(tmp_path, monkeypatch):
    branches._commons.clear()
    answers = [None, ".git\n"]
    monkeypatch.setattr(branches.git_overview, "_out", lambda args, cwd: answers.pop(0))

    assert branches._common(str(tmp_path)) == ""
    assert branches._common(str(tmp_path)) != ""
