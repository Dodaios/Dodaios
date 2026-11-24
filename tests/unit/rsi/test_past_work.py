"""Benchmark tasks from past coding work: the records, the repository, and the join."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from dodaios.rsi.bench.model import Domain, Source
from dodaios.rsi.bench.past_work import __main__ as report
from dodaios.rsi.bench.past_work import tasks as tasks_module
from dodaios.rsi.bench.past_work.history import MergedChange, merged_changes, read_history
from dodaios.rsi.bench.past_work.intake import session_folders, take_in
from dodaios.rsi.bench.past_work.sessions import (
    Opened,
    PastSession,
    Said,
    person_text,
    read_sessions,
)
from dodaios.rsi.bench.past_work.tasks import LeftOut, mine, pieces
from dodaios.rsi.bench.store import BenchStore

REPO = "github.com/acme/app"
PULL = "https://github.com/Acme/App/pull/"
REQUEST = "Please add a parser for the settings file and cover it with tests"


def at(minute: int) -> str:
    return f"2026-11-01T10:{minute:02d}:00.000Z"


def write(path: Path, rows: list[dict[str, Any]], *, compact: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    separators = (",", ":") if compact else None
    path.write_text(
        "\n".join(json.dumps(row, separators=separators) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------------------- #
# claude records
# --------------------------------------------------------------------------- #


def said(text: Any, minute: int, **extra: Any) -> dict[str, Any]:
    return {
        "type": "user",
        "sessionId": "s1",
        "timestamp": at(minute),
        "cwd": "C:\\work\\app",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
        **extra,
    }


def ran(tool_id: str, command: str, minute: int) -> dict[str, Any]:
    return {
        "type": "assistant",
        "timestamp": at(minute),
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}
            ],
        },
    }


def printed(
    tool_id: str, text: str, minute: int, git: dict[str, Any] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {"stdout": text}
    if git is not None:
        result["gitOperation"] = git
    return {
        "type": "user",
        "timestamp": at(minute),
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text}],
        },
        "toolUseResult": result,
    }


def claude_home(tmp_path: Path, rows: list[dict[str, Any]], **kwargs: Any) -> dict[str, Path]:
    home = tmp_path / "claude"
    write(home / "projects" / "C--work-app" / "s1.jsonl", rows, **kwargs)
    return {"claude": home, "codex": tmp_path / "no-codex"}


def test_a_claude_record_gives_the_persons_words_and_the_pull_request_it_opened(tmp_path):
    rows = [
        said(f"{REQUEST}\n<system-reminder>be careful</system-reminder>", 0),
        said("<local-command-caveat>written by the harness</local-command-caveat>", 1, isMeta=True),
        said("what the sub-agent was told to do in its own thread", 2, isSidechain=True),
        printed("t0", "a whole file the agent read, with a pull/ in a path", 3),
        said("[Request interrupted by user]", 4),
        {
            "type": "attachment",
            "timestamp": at(5),
            "attachment": {
                "type": "queued_command",
                "prompt": "Keep the old option names working",
                "origin": {"kind": "human"},
            },
        },
        printed(
            "t1",
            "edited",
            6,
            git={"pr": {"number": 9, "url": PULL + "9", "action": "edited"}},
        ),
        printed(
            "t2",
            PULL + "12",
            7,
            git={"pr": {"number": 12, "url": PULL + "12", "action": "created"}},
        ),
    ]
    sessions = list(read_sessions(claude_home(tmp_path, rows)))

    assert len(sessions) == 1
    session = sessions[0]
    assert (session.agent, session.session_id, session.cwd) == ("claude", "s1", "C:\\work\\app")
    assert [item.text for item in session.said] == [REQUEST, "Keep the old option names working"]
    assert [(item.repo, item.number) for item in session.opened] == [(REPO, 12)]


def test_an_older_claude_record_is_read_from_what_the_command_printed(tmp_path):
    rows = [
        said(REQUEST, 0),
        ran("view", "gh pr view 3", 1),
        printed("view", PULL + "3", 2),
        ran("create", "git push -u origin work && gh pr create --fill", 3),
        printed("create", f"remote: done\n{PULL}14\n", 4),
    ]
    session = next(read_sessions(claude_home(tmp_path, rows)))

    assert [(item.repo, item.number) for item in session.opened] == [(REPO, 14)]


def test_a_record_that_opened_no_pull_request_is_not_read(tmp_path):
    rows = [said(REQUEST, 0), ran("t", "pytest -q", 1), printed("t", "3 passed", 2)]

    assert list(read_sessions(claude_home(tmp_path, rows))) == []


def test_a_record_written_with_spaces_is_still_read(tmp_path):
    rows = [
        said(REQUEST, 0),
        printed("t", PULL + "5", 1, git={"pr": {"url": PULL + "5", "action": "created"}}),
    ]
    session = next(read_sessions(claude_home(tmp_path, rows, compact=False)))

    assert [item.text for item in session.said] == [REQUEST]
    assert [item.number for item in session.opened] == [5]


def test_a_sub_agents_own_record_is_not_read(tmp_path):
    home = tmp_path / "claude"
    rows = [
        said("Build the parser as the lead described", 0),
        printed("t", PULL + "8", 1, git={"pr": {"url": PULL + "8", "action": "created"}}),
    ]
    write(home / "projects" / "C--work-app" / "s1" / "subagents" / "agent-1.jsonl", rows)

    assert list(read_sessions({"claude": home, "codex": tmp_path / "no-codex"})) == []


def test_a_slash_commands_arguments_are_the_persons_words():
    command = "<command-name>/goal</command-name><command-args>fix the login test</command-args>"

    assert person_text(command) == "fix the login test"
    assert (
        person_text("<command-name>/effort</command-name><command-args>high</command-args>") == ""
    )
    assert person_text("<task-notification>done</task-notification>") == ""


# --------------------------------------------------------------------------- #
# codex records
# --------------------------------------------------------------------------- #


def codex_rows(meta: dict[str, Any]) -> list[dict[str, Any]]:
    def item(minute: int, payload: dict[str, Any]) -> dict[str, Any]:
        return {"timestamp": at(minute), "type": "response_item", "payload": payload}

    return [
        {"timestamp": at(0), "type": "session_meta", "payload": {"id": "c1", **meta}},
        item(
            1,
            {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"<environment_context>cwd</environment_context>\n{REQUEST}",
                    }
                ],
            },
        ),
        item(2, {"type": "message", "role": "developer", "content": "the harness briefing"}),
        item(
            3,
            {
                "type": "function_call",
                "call_id": "k1",
                "name": "shell",
                "arguments": json.dumps({"command": ["bash", "-lc", "gh pr create --fill"]}),
            },
        ),
        item(4, {"type": "function_call_output", "call_id": "k1", "output": PULL + "21"}),
    ]


def test_a_codex_record_gives_the_same_shape(tmp_path):
    home = tmp_path / "codex"
    write(home / "sessions" / "2026" / "11" / "01" / "rollout-c1.jsonl", codex_rows({"cwd": "/w"}))
    session = next(read_sessions({"claude": tmp_path / "no-claude", "codex": home}))

    assert (session.agent, session.session_id, session.cwd) == ("codex", "c1", "/w")
    assert [item.text for item in session.said] == [REQUEST]
    assert [(item.repo, item.number) for item in session.opened] == [(REPO, 21)]


def test_a_codex_sub_agent_record_is_not_read(tmp_path):
    home = tmp_path / "codex"
    rows = codex_rows({"cwd": "/w", "thread_source": "subagent"})
    write(home / "sessions" / "2026" / "11" / "01" / "rollout-c1.jsonl", rows)

    assert list(read_sessions({"claude": tmp_path / "no-claude", "codex": home})) == []


# --------------------------------------------------------------------------- #
# the repository's merged pull requests
# --------------------------------------------------------------------------- #


def git(folder: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
    }
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def commit(folder: Path, subject: str, files: dict[str, str]) -> str:
    for name, text in files.items():
        target = folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", subject)
    return git(folder, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    folder = tmp_path / "app"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")
    git(folder, "remote", "add", "origin", "https://github.com/Acme/App.git")
    shas = {"start": commit(folder, "start", {"README.md": "app\n"})}
    shas["parser"] = commit(
        folder,
        "feat: a parser for the settings file (#1)",
        {"src/parser.py": "def parse(): ...\n", "tests/test_parser.py": "def test_parse(): ...\n"},
    )
    shas["docs"] = commit(folder, "docs: how to install (#2)", {"docs/install.md": "steps\n"})
    shas["fix"] = commit(
        folder, "fix: read empty files (#3)", {"src/parser.py": "def parse(): 1\n"}
    )
    shas["revert"] = commit(
        folder, 'Revert "fix: read empty files (#3)" (#4)', {"src/parser.py": "def parse(): ...\n"}
    )
    git(folder, "checkout", "-q", "-b", "feature")
    commit(folder, "work in progress", {"src/cache.py": "CACHE = {}\n"})
    git(folder, "checkout", "-q", "main")
    git(
        folder, "merge", "-q", "--no-ff", "-m", "Merge pull request #5 from acme/feature", "feature"
    )
    return folder, shas


def test_merged_pull_requests_are_read_from_the_default_branch(repository):
    folder, shas = repository
    changes = merged_changes(folder)

    assert sorted(changes) == [1, 2, 3, 4, 5]
    parser = changes[1]
    assert (parser.repo, parser.commit, parser.parent) == (REPO, shas["parser"], shas["start"])
    assert parser.tests == ("tests/test_parser.py",)
    assert parser.sources == ("src/parser.py",)
    assert parser.weights == {"src/parser.py": 1, "tests/test_parser.py": 1}
    # One line replaced is one deleted and one added.
    assert changes[3].weights == {"src/parser.py": 2}
    assert parser.merged_ms > 0
    assert changes[2].tests == () and changes[2].files == ("docs/install.md",)
    # A merge commit counts with what it brought in, against the branch before it.
    assert changes[5].files == ("src/cache.py",) and changes[5].parent == shas["revert"]


def test_paths_are_read_only_for_the_pull_requests_asked_about(repository):
    folder, _ = repository
    history = read_history(folder)

    assert history is not None and history.repo == REPO
    assert history.numbers == {1, 2, 3, 4, 5}
    assert sorted(history.changes([2, 5, 77])) == [2, 5]
    assert history.changes([]) == {} and history.changes([77]) == {}
    assert sorted(merged_changes(folder, only=[1])) == [1]


def test_a_pull_request_that_was_taken_back_is_marked(repository):
    folder, _ = repository
    changes = merged_changes(folder)

    assert changes[3].reverted is True
    assert [number for number, change in changes.items() if change.reverted] == [3]


def test_a_folder_that_is_no_repository_or_is_gone_has_no_merged_changes(tmp_path):
    assert merged_changes(tmp_path) == {}
    assert merged_changes(tmp_path / "deleted") == {}
    assert read_history(tmp_path) is None


# --------------------------------------------------------------------------- #
# which words asked for which pull request
# --------------------------------------------------------------------------- #


def session(*events: tuple[int, str | int], sid: str = "s1") -> PastSession:
    """``(minute, text)`` is something said, ``(minute, number)`` a pull request opened."""
    return PastSession(
        agent="claude",
        session_id=sid,
        cwd="/w",
        said=tuple(Said(m * 60_000, what) for m, what in events if isinstance(what, str)),
        opened=tuple(Opened(m * 60_000, REPO, what) for m, what in events if isinstance(what, int)),
    )


def test_the_first_pull_request_takes_the_first_real_request_and_what_was_added():
    found, left = pieces(
        session((0, "hi there"), (1, REQUEST), (2, "Also keep the old names"), (9, 1))
    )

    assert [(piece.number, piece.request, piece.told_later) for piece in found] == [
        (1, REQUEST, ("Also keep the old names",))
    ]
    assert not left


def test_a_long_conversation_before_the_first_pull_request_is_no_single_request():
    talk = [(minute, f"{REQUEST} and note {minute}") for minute in range(5)]

    found, left = pieces(session(*talk, (9, 1)))

    assert found == []
    assert left == {LeftOut.CONVERSATION: 1}


def test_a_later_pull_request_counts_only_with_exactly_one_thing_said_since():
    second = "Now make the parser report the line of an error"
    found, left = pieces(
        session(
            (0, REQUEST),
            (5, 1),
            (6, second),
            (9, 2),
            (10, "The colour of the button is wrong"),
            (11, "And please add a setting for the timeout too"),
            (15, 3),
            (16, 4),
            (17, "ok go"),
            (18, 5),
        )
    )

    assert [(piece.number, piece.request) for piece in found] == [(1, REQUEST), (2, second)]
    assert left == {LeftOut.AMBIGUOUS: 1, LeftOut.NO_REQUEST: 2}


def test_a_session_that_never_asked_in_words_gives_nothing():
    found, left = pieces(session((0, "ok go"), (3, 1)))

    assert found == []
    assert left == {LeftOut.NO_REQUEST: 1}


# --------------------------------------------------------------------------- #
# the tasks
# --------------------------------------------------------------------------- #


def change(number: int, files: tuple[str, ...], **extra: Any) -> MergedChange:
    return MergedChange(
        repo=REPO,
        number=number,
        commit=f"merge{number}",
        parent=f"before{number}",
        merged_ms=1_000 + number,
        subject=f"change (#{number})",
        files=files,
        **extra,
    )


WITH_TESTS = ("src/parser.py", "tests/test_parser.py")


@pytest.fixture(autouse=True)
def no_real_detector(monkeypatch):
    """The detector is the app's own; here a marker word stands for a credential."""
    monkeypatch.setattr(
        "dodaios.memory.learning.guard.contains_secret", lambda text: "MARKER" in text
    )


def test_one_piece_of_work_becomes_a_brief_task_and_a_coding_task():
    mined = mine(
        [session((0, REQUEST), (1, "Keep the old names"), (5, 1))],
        {REPO: {1: change(1, WITH_TESTS)}},
    )

    brief, coding = mined.tasks
    assert (brief.domain, coding.domain) == (Domain.BRIEF, Domain.CODING)
    assert brief.source is Source.MINED and coding.source is Source.MINED
    assert brief.group == coding.group == f"{REPO}#1"
    assert brief.split is coding.split
    assert brief.id != coding.id
    assert dict(brief.payload) == {"repo": REPO, "base": "before1", "request": REQUEST}
    assert dict(brief.check) == {
        "commit": "merge1",
        "files": dict.fromkeys(WITH_TESTS, 1),
        "tests": ["tests/test_parser.py"],
        "told_later": ["Keep the old names"],
    }
    assert coding.payload["told_later"] == ["Keep the old names"]
    assert dict(coding.check) == {"commit": "merge1", "tests": ["tests/test_parser.py"]}
    assert brief.created_ms == 1_001
    assert (mined.sessions, mined.opened, dict(mined.left_out)) == (1, 1, {})


def test_what_a_task_is_given_never_holds_the_answer():
    mined = mine([session((0, REQUEST), (5, 1))], {REPO: {1: change(1, WITH_TESTS)}})

    for task in mined.tasks:
        given = json.dumps(dict(task.payload))
        assert "merge1" not in given
        assert "tests/test_parser.py" not in given


def test_a_change_without_tests_gives_only_the_brief_task():
    mined = mine([session((0, REQUEST), (5, 2))], {REPO: {2: change(2, ("docs/install.md",))}})

    assert [task.domain for task in mined.tasks] == [Domain.BRIEF]


def test_the_same_work_gives_the_same_task_ids_every_time():
    def once() -> list[str]:
        mined = mine([session((0, REQUEST), (5, 1))], {REPO: {1: change(1, WITH_TESTS)}})
        return [task.id for task in mined.tasks]

    assert once() == once()


def test_what_cannot_be_a_task_is_counted_with_its_reason():
    mined = mine(
        [
            session((0, REQUEST), (5, 1), sid="a"),
            session((0, REQUEST + " again"), (9, 1), sid="b"),
            session((0, REQUEST), (5, 3), sid="c"),
            session((0, REQUEST), (5, 7), sid="d"),
            session((0, REQUEST + " with MARKER inside"), (5, 6), sid="e"),
            session((0, REQUEST), (5, 8), sid="f"),
        ],
        {
            REPO: {
                1: change(1, WITH_TESTS),
                3: change(3, WITH_TESTS, reverted=True),
                6: change(6, WITH_TESTS),
                8: change(8, ()),
            }
        },
    )

    assert {task.group for task in mined.tasks} == {f"{REPO}#1"}
    assert mined.tasks[0].payload["request"] == REQUEST  # the session that opened it first
    assert dict(mined.left_out) == {
        LeftOut.NOT_MERGED.value: 1,
        LeftOut.REVERTED.value: 1,
        LeftOut.CREDENTIAL.value: 1,
        LeftOut.DUPLICATE.value: 1,
        LeftOut.EMPTY.value: 1,
    }
    assert (mined.sessions, mined.opened) == (6, 6)


def test_a_brief_the_assistant_wrote_is_no_input_for_a_brief_task():
    mined = mine(
        [session((0, REQUEST), (5, 1))],
        {REPO: {1: change(1, WITH_TESTS)}},
        composed=lambda text: text == REQUEST,
    )

    (coding,) = mined.tasks
    assert coding.domain is Domain.CODING
    assert coding.payload["composed"] is True


def test_files_the_person_pointed_at_are_listed():
    asked = (
        "@.drops/shot one.png is not it, see @.drops/shot.png and fix the row height, mail a@b.co"
    )
    mined = mine([session((0, asked), (5, 2))], {REPO: {2: change(2, ("ui/row.tsx",))}})

    assert mined.tasks[0].payload["attached"] == [".drops/shot.png"]


def test_logged_briefs_recognises_a_brief_the_app_sent(tmp_path, monkeypatch):
    from dodaios.briefs import log as brief_log
    from dodaios.core import config as core_config

    monkeypatch.setattr(core_config, "DATA_DIR", tmp_path)
    assert tasks_module.logged_briefs() is None

    store = brief_log.BriefLog(tmp_path / brief_log.DB_NAME)
    store._db.execute(
        "INSERT INTO briefs (brief_id, created_ms, brief_text) VALUES ('b1', 1, ?)",
        ("Goal: add a parser.\n\nDone when the tests pass.",),
    )
    store._db.commit()
    store.close()

    composed = tasks_module.logged_briefs()
    assert composed is not None
    assert composed("Goal: add a parser.  Done when the tests pass.\n<effort>high</effort>")
    assert not composed(REQUEST)


# --------------------------------------------------------------------------- #
# into the benchmark's store
# --------------------------------------------------------------------------- #


def asked_and_opened(tmp_path: Path, number: int) -> dict[str, Path]:
    pull = PULL + str(number)
    rows = [
        said(REQUEST, 0),
        printed("t", pull, 1, git={"pr": {"url": pull, "action": "created"}}),
    ]
    return claude_home(tmp_path, rows)


def test_the_intake_stores_a_task_once_and_keeps_it_when_its_record_is_gone(tmp_path, repository):
    folder, _ = repository
    homes = asked_and_opened(tmp_path, 1)
    store = BenchStore(tmp_path / "bench.db")

    first = take_in(store, [folder], homes=homes)
    again = take_in(store, [folder], homes=homes)
    # The CLI deletes a record after some weeks; what was stored stays.
    (homes["claude"] / "projects" / "C--work-app" / "s1.jsonl").unlink()
    later = take_in(store, [folder], homes=homes)

    assert (first.new, dict(first.in_use), first.retired) == (2, {"brief": 1, "coding": 1}, 0)
    assert (again.new, again.retired) == (0, 0)
    assert (later.new, dict(later.in_use), later.retired) == (0, {"brief": 1, "coding": 1}, 0)
    (brief,) = store.tasks(Domain.BRIEF)
    assert brief.payload["request"] == REQUEST
    assert brief.check["files"] == {"src/parser.py": 1, "tests/test_parser.py": 1}
    assert brief.split is store.tasks(Domain.CODING)[0].split
    store.close()


def test_the_repositories_are_the_ones_the_sessions_ran_in_each_read_once(tmp_path, repository):
    import dataclasses

    folder, _ = repository
    linked = tmp_path / "linked"
    git(folder, "worktree", "add", "-q", str(linked), "feature")
    plain = tmp_path / "plain"
    plain.mkdir()

    def ran_in(where: Path, *events: tuple[int, str | int]) -> PastSession:
        return dataclasses.replace(session(*events), cwd=str(where))

    sessions = [
        ran_in(linked, (0, REQUEST), (1, 1)),  # a worktree of the same repository
        ran_in(folder, (0, REQUEST), (1, 2)),
        ran_in(plain, (0, REQUEST), (1, 3)),  # no repository
        ran_in(tmp_path / "deleted", (0, REQUEST), (1, 4)),
        ran_in(tmp_path / "elsewhere", (0, REQUEST)),  # opened no pull request
    ]
    found = session_folders(sessions)
    assert len(found) == 1 and found[0] in (folder, linked)


def test_the_intake_finds_the_repository_from_the_record_itself(tmp_path, repository):
    folder, _ = repository
    pull = PULL + "1"
    rows = [
        said(REQUEST, 0, cwd=str(folder)),
        printed("t", pull, 1, git={"pr": {"url": pull, "action": "created"}}),
    ]
    store = BenchStore(tmp_path / "bench.db")
    taken = take_in(store, homes=claude_home(tmp_path, rows))
    assert (taken.new, dict(taken.in_use)) == (2, {"brief": 1, "coding": 1})
    store.close()


def test_a_night_stores_the_tasks_and_says_so(tmp_path, repository, real_past_work, monkeypatch):
    from dodaios.core import config as core_config
    from dodaios.rsi import night as nights

    monkeypatch.setattr(core_config, "DATA_DIR", tmp_path)  # no brief log of this machine
    folder, _ = repository
    pull = PULL + "1"
    rows = [
        said(REQUEST, 0, cwd=str(folder)),
        printed("t", pull, 1, git={"pr": {"url": pull, "action": "created"}}),
    ]
    homes = claude_home(tmp_path, rows)
    store = BenchStore(tmp_path / "bench.db")
    try:
        made = nights._past_work(store, homes)
        assert made == {"past_work": 2, "past_work_retired": 0}
        report = nights.NightReport(ts_ms=1, app="1.0", made=made)
        assert not report.idle
        assert "Stored 2 tasks from your past coding work." in report.lines()
        assert nights._past_work(store, homes) == {"past_work": 0, "past_work_retired": 0}
        assert nights.NightReport(ts_ms=1, app="1.0", made={"past_work": 0}).idle
    finally:
        store.close()


def test_records_that_cannot_be_read_cost_no_night(tmp_path, real_past_work, monkeypatch):
    from dodaios.rsi import night as nights
    from dodaios.rsi.bench import past_work

    def broken(*_args, **_kwargs):
        raise OSError("the records are on a drive that is gone")

    monkeypatch.setattr(past_work, "take_in", broken)
    monkeypatch.setattr(past_work, "logged_briefs", lambda: None)
    store = BenchStore(tmp_path / "bench.db")
    try:
        assert nights._past_work(store, {}) == {}
    finally:
        store.close()


def test_the_intake_retires_a_task_whose_pull_request_was_taken_back(tmp_path, repository):
    folder, _ = repository
    homes = asked_and_opened(tmp_path, 1)
    store = BenchStore(tmp_path / "bench.db")
    take_in(store, [folder], homes=homes)
    commit(
        folder,
        'Revert "feat: a parser for the settings file (#1)" (#9)',
        {"src/parser.py": "taken back\n"},
    )

    taken = take_in(store, [folder], homes=homes)

    assert (taken.new, taken.retired, dict(taken.in_use)) == (0, 2, {"brief": 0, "coding": 0})
    assert dict(taken.left_out) == {LeftOut.REVERTED.value: 1}
    store.close()


def test_the_intake_leaves_the_tasks_of_a_repository_it_did_not_read(tmp_path, repository):
    folder, _ = repository
    homes = asked_and_opened(tmp_path, 1)
    store = BenchStore(tmp_path / "bench.db")
    take_in(store, [folder], homes=homes)

    taken = take_in(store, [tmp_path / "deleted"], homes=homes)

    assert (taken.retired, dict(taken.in_use)) == (0, {"brief": 1, "coding": 1})
    store.close()


def test_the_command_stores_into_the_data_folder(tmp_path, repository, monkeypatch, capsys):
    from dodaios.core import config as core_config

    folder, _ = repository
    homes = asked_and_opened(tmp_path, 1)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(homes["claude"]))
    monkeypatch.setenv("CODEX_HOME", str(homes["codex"]))
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(core_config, "DATA_DIR", data)

    assert report.main(["--repo", str(folder), "--store"]) == 0

    assert "stored 2 new tasks" in capsys.readouterr().out
    store = BenchStore(data / "bench.db")
    assert store.counts().keys() == {"brief", "coding"}
    store.close()


# --------------------------------------------------------------------------- #
# the report
# --------------------------------------------------------------------------- #


def test_the_report_counts_and_prints_no_request():
    mined = mine(
        [session((0, REQUEST), (5, 1), sid="a"), session((0, "ok go"), (5, 2), sid="b")],
        {REPO: {1: change(1, WITH_TESTS)}},
    )
    summary = report.summary(mined)
    text = report.render(summary)

    assert summary["pieces_of_work"] == 1
    assert sum(summary["tasks"]["brief"].values()) == 1
    assert sum(summary["tasks"]["coding"].values()) == 1
    assert summary["left_out"] == {LeftOut.NO_REQUEST.value: 1}
    assert "parser" not in text and "opened without the person asking" in text
