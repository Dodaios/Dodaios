"""The done-when check after a run, and the record of orders with its report."""

from __future__ import annotations

from dodaios.briefs import acceptance, done, report
from dodaios.briefs import log as brief_log


def _events(*runs: tuple[str, bool]) -> list[dict]:
    events: list[dict] = []
    for number, (command, ok) in enumerate(runs):
        call = f"c{number}"
        events.append({
            "ts_ms": 1_000 + number, "kind": "tool_call",
            "payload": {"call_id": call, "name": "Bash", "input": {"command": command}},
        })
        events.append({
            "ts_ms": 1_001 + number, "kind": "tool_result",
            "payload": {"call_id": call, "output": "ok" if ok else "1 failed", "is_error": not ok},
        })
    return events


def test_commands_pair_with_their_results_and_respect_the_turn_start():
    events = _events(("pytest tests/sync", False), ("pytest tests/sync", True))
    ran = acceptance.commands_run(events, since_ms=0)
    assert [(r.command, r.ok) for r in ran] == [
        ("pytest tests/sync", False), ("pytest tests/sync", True),
    ]
    assert acceptance.commands_run(events, since_ms=5_000) == []


def test_a_codex_exit_code_decides_and_a_call_without_a_result_is_left_out():
    events = [
        {"ts_ms": 1, "kind": "tool_call",
         "payload": {"call_id": "a", "name": "RunCommand", "input": {"command": "npm test"}}},
        {"ts_ms": 2, "kind": "tool_result",
         "payload": {"call_id": "a", "output": "boom\n[exit 2]", "is_error": False}},
        {"ts_ms": 3, "kind": "tool_call",
         "payload": {"call_id": "b", "name": "RunCommand", "input": {"command": "npm run build"}}},
    ]
    ran = acceptance.commands_run(events)
    assert [(r.command, r.ok) for r in ran] == [("npm test", False)]


def test_each_point_is_confirmed_contradicted_or_left_open(project):
    criteria = done.criteria_of(
        "x",
        "- `python scripts/done_gate.py` says DONE\n- the timeout test passes\n"
        "- `docs/sync.md` exists\n- `sync/client.py` is in place\n"
        "- the dialog shows the retry count\n- report the cause",
    )
    events = _events(
        ("python scripts/done_gate.py", True), ("python -m pytest tests -q", False)
    )
    results = acceptance.judge(
        criteria, events=events, folder=str(project), report="The cause was a short timeout."
    )
    verdicts = [r.verdict for r in results]
    assert verdicts == [
        acceptance.CONFIRMED, acceptance.CONTRADICTED, acceptance.CONTRADICTED,
        acceptance.CONFIRMED, acceptance.OPEN, acceptance.CONFIRMED,
    ]
    text = acceptance.summary(results)
    assert "3 of 6 confirmed, 2 contradicted, 1 open" in text
    assert "send what is contradicted back to the same agent" in text


def test_a_command_inside_a_longer_line_is_judged_by_what_its_output_says(project):
    criteria = done.criteria_of("x", "`python -m pytest -q` is green")

    def verdict(command: str, output: str, ok: bool = True) -> str:
        events = [
            {"ts_ms": 1, "kind": "tool_call",
             "payload": {"call_id": "a", "name": "Bash", "input": {"command": command}}},
            {"ts_ms": 2, "kind": "tool_result",
             "payload": {"call_id": "a", "output": output, "is_error": not ok}},
        ]
        return acceptance.judge(criteria, events=events, folder=str(project))[0].verdict

    # Piped into tail, the line succeeds whatever pytest did.
    assert verdict("python -m pytest -q 2>&1 | tail -5", "3 passed in 0.1s") == acceptance.CONFIRMED
    assert verdict("python -m pytest -q 2>&1 | tail -5", "1 failed, 2 passed") == (
        acceptance.CONTRADICTED
    )
    assert verdict("python -m pytest -q 2>&1 | tail -1", "") == acceptance.OPEN
    # Another command of the line failed; the tests themselves passed.
    assert verdict(
        "python -m pytest -q 2>&1 | grep passed; ls outbox.json",
        "Exit code 1 6 passed in 0.10s ls: outbox.json: No such file or directory", ok=False,
    ) == acceptance.CONFIRMED
    assert verdict(
        "python -m pytest -q 2>&1 | grep -E 'passed|failed'; ls x", "1 failed, 5 passed", ok=False
    ) == acceptance.CONTRADICTED
    assert verdict("cd app && python -m pytest -q", "", ok=True) == acceptance.CONFIRMED
    assert verdict("python -m pytest -q", "boom", ok=False) == acceptance.CONTRADICTED


def _verdict_of(project, done_when: str, command: str, output: str = "", ok: bool = True):
    events = [
        {"ts_ms": 1, "kind": "tool_call",
         "payload": {"call_id": "a", "name": "Bash", "input": {"command": command}}},
        {"ts_ms": 2, "kind": "tool_result",
         "payload": {"call_id": "a", "output": output, "is_error": not ok}},
    ]
    criteria = done.criteria_of("x", done_when)
    return acceptance.judge(criteria, events=events, folder=str(project))[0]


def test_a_check_that_is_only_named_in_text_did_not_run(project):
    green = "`python -m pytest -q` is green"
    # A commit message, a file being written and an echo carry the words; none runs them.
    carried = [
        'git commit -q -m "Tests pass with python -m pytest -q"',
        "git commit -q -F - <<'EOF'\nExport the notes\n\npython -m pytest -q is green\nEOF",
        "cat >> notes.md <<EOF\nrun python -m pytest -q before a commit\nEOF",
        "echo 'python -m pytest -q'",
    ]
    for command in carried:
        result = _verdict_of(project, green, command)
        assert result.verdict == acceptance.OPEN, command
        assert "was not run" in result.evidence
    # The same goes for "the tests pass": installing or printing a runner is no test run.
    for command in ("pip install pytest", "cat tests/test_client.py", "which pytest"):
        result = _verdict_of(project, "the timeout test passes", command)
        assert result.verdict == acceptance.OPEN, command


def test_another_program_started_the_same_way_is_not_the_check(project):
    green = "`python -m pytest -q` is green"
    assert _verdict_of(project, green, "python -m pip install -e .").verdict == acceptance.OPEN
    assert _verdict_of(project, green, "python -m http.server").verdict == acceptance.OPEN
    lint = "`ruff check .` is clean"
    assert _verdict_of(project, lint, "ruff format .").verdict == acceptance.OPEN
    assert _verdict_of(project, lint, "ruff check . --fix").verdict == acceptance.CONFIRMED


def test_the_same_check_started_another_way_counts(project):
    green = "`python -m pytest -q` is green"
    for command in (
        "/opt/venv/bin/python3.12 -m pytest -q -x -p no:cacheprovider",
        "uv run pytest -q",
        "PYTHONPATH=. timeout 600 python -m pytest",
        "cd app && poetry run pytest -q",
        "bash -lc 'python -m pytest -q'",
    ):
        assert _verdict_of(project, green, command).verdict == acceptance.CONFIRMED, command
    scoped = "`python -m pytest tests/sync -q` is green"
    assert _verdict_of(project, scoped, "pytest -q tests/sync/").verdict == acceptance.CONFIRMED
    # The whole suite ran, not the named part of it: that is another check.
    assert _verdict_of(project, scoped, "pytest -q tests/other").verdict == acceptance.OPEN
    script = "`npm test` passes"
    assert _verdict_of(project, script, "npm run test").verdict == acceptance.CONFIRMED


def test_the_evidence_names_the_command_itself_and_what_spoke_for_it(project):
    green = "`python -m pytest -q` is green"
    line = (
        "git add sync && git commit -q -F - <<'EOF'\nExport the notes\nEOF\n"
        "git log --oneline | head -2 && python -m pytest -q 2>&1 | tail -1"
    )
    result = _verdict_of(project, green, line, "70961ac Export the notes\n9 passed in 0.07s")
    assert result.verdict == acceptance.CONFIRMED
    assert result.evidence == "ran `python -m pytest -q 2>&1`: its output says '9 passed'"
    # A long output after the summary does not hide it.
    diff = "\n".join(f"+ line {n}" for n in range(400))
    result = _verdict_of(
        project, green, "python -m pytest -q | tail -1; git diff", f"9 passed in 0.1s\n{diff}"
    )
    assert result.verdict == acceptance.CONFIRMED


def test_what_a_line_exit_status_says_about_one_command_of_it(project):
    green = "`python -m pytest -q` is green"
    # Everything after it hangs on it: the line succeeding means it succeeded.
    assert _verdict_of(
        project, green, "python -m pytest -q && git commit -q -m done", ""
    ).verdict == acceptance.CONFIRMED
    # The line failed, perhaps at the step before it: nothing is known about the check.
    reached = _verdict_of(project, green, "cd missing && python -m pytest -q", "", ok=False)
    assert reached.verdict == acceptance.OPEN
    assert "possibly before it reached" in reached.evidence
    # A failure is the last word on it, a pass after a failure is too.
    assert _verdict_of(
        project, green, "python -m pytest -q; echo done", "1 failed, 8 passed in 0.2s\ndone"
    ).verdict == acceptance.CONTRADICTED
    before_and_after = "git stash -q; python -m pytest -q; git stash pop -q; python -m pytest -q"
    assert _verdict_of(
        project, green, before_and_after, "1 failed, 8 passed in 0.2s\n9 passed in 0.2s", ok=True
    ).verdict == acceptance.CONFIRMED
    # No failure is not a failure, and a printed file is not a test run.
    assert _verdict_of(
        project, "`cargo test` passes", "cargo test 2>&1 | tail -2",
        "test result: ok. 5 passed; 0 failed; 0 ignored",
    ).verdict == acceptance.CONFIRMED
    assert _verdict_of(
        project, green, "python -m pytest -q | tail -1; cat notes.txt",
        "9 passed in 0.1s\nnote: the build FAILED once in March",
    ).verdict == acceptance.CONFIRMED


def _turn(*steps: tuple[str, dict, str]) -> list[dict]:
    """Events of a turn from ``(tool, input, output)`` steps, in order."""
    events: list[dict] = []
    for number, (tool, given, output) in enumerate(steps):
        events.append({"ts_ms": 10 + number, "kind": "tool_call",
                       "payload": {"call_id": f"c{number}", "name": tool, "input": given}})
        events.append({"ts_ms": 10 + number, "kind": "tool_result",
                       "payload": {"call_id": f"c{number}", "output": output, "is_error": False}})
    return events


def test_a_pass_counts_only_for_the_state_the_work_ended_in(project):
    criteria = done.criteria_of("x", "`python -m pytest -q` is green")
    test_run = ("Bash", {"command": "python -m pytest -q"}, "9 passed in 0.1s")

    def judged(*steps: tuple[str, dict, str]) -> acceptance.Result:
        return acceptance.judge(criteria, events=_turn(*steps), folder=str(project))[0]

    edit = ("Edit", {"file_path": "sync/client.py"}, "updated")
    assert judged(edit, test_run).verdict == acceptance.CONFIRMED
    stale = judged(test_run, edit)
    assert stale.verdict == acceptance.OPEN
    assert "1 file change(s) followed that run" in stale.evidence
    # Run again after the change, it counts again.
    assert judged(test_run, edit, test_run).verdict == acceptance.CONFIRMED
    # A shell line that writes a file is a change too; notes and scratch files are not.
    for command in ("cat >> sync/client.py <<'EOF'\nx = 1\nEOF", "sed -i '' s/a/b/ sync/client.py",
                    "git checkout -- sync/client.py"):
        assert judged(test_run, ("Bash", {"command": command}, "")).verdict == acceptance.OPEN
    for harmless in (
        ("Edit", {"file_path": "docs/notes.md"}, "updated"),
        ("Bash", {"command": "git diff > /tmp/change.diff; git commit -q -m done"}, ""),
        ("Bash", {"command": "ls sync 2>/dev/null"}, ""),
    ):
        assert judged(test_run, harmless).verdict == acceptance.CONFIRMED, harmless


def test_a_point_is_about_the_report_only_when_it_asks_for_one():
    kinds = {
        "report the cause": done.KIND_REPORT,
        "The answer names the commit that introduced it": done.KIND_REPORT,
        "Report which tests fail and why": done.KIND_REPORT,
        "A list of every finding with its file and line": done.KIND_REPORT,
        "The agent asked the lead for the file format first and used the answer":
            done.KIND_OTHER,
        "The export answers with JSON": done.KIND_OTHER,
        "The new tests pass": done.KIND_TEST,
    }
    for text, kind in kinds.items():
        assert done.criteria_of("x", text)[0].kind == kind, text


def test_a_compound_done_is_split_into_its_points():
    points = done.criteria_of(
        "x", "A new test whose send times out twice passes, and `python -m pytest -q` is green."
    )
    assert [p.kind for p in points] == ["test", "command"]


def test_a_command_that_never_ran_is_open_not_confirmed(project):
    criteria = done.criteria_of("x", "`python scripts/done_gate.py` says DONE")
    results = acceptance.judge(criteria, events=[], folder=str(project), report="All done.")
    assert results[0].verdict == acceptance.OPEN
    assert "was not run" in results[0].evidence


def test_landed_without_a_pull_request_or_commit_stays_open(project):
    criteria = done.criteria_of("x", "the fix is merged with CI green")
    results = acceptance.judge(criteria, events=[], folder=str(project), report="Merged.")
    assert results[0].verdict == acceptance.OPEN


def test_no_points_no_summary():
    assert acceptance.summary([]) == ""
    assert acceptance.judge([], events=[]) == []


def test_the_record_keeps_an_order_its_deliveries_and_their_ends(briefs_on):
    store = brief_log.get_log()
    store.note_attempt(
        "brief_1", writer="lead", folder="/p", kind="implement", person_words="fix es",
        draft="weak", findings=[{"code": "no_done", "severity": "revise", "message": "m"}],
        sent_back=True,
    )
    store.note_attempt("brief_1", writer="lead", draft="strong", kind="implement")
    store.note_delivery("brief_1", "job_a", thread_id="t1", cli="claude", family="claude",
                        effort="high", effort_source="job_size", job_size="usual", sent_chars=90)
    store.note_question("job_a")
    store.note_outcome("job_a", "completed", [
        {"point": "tests pass", "verdict": "confirmed", "evidence": "ran pytest"},
    ])
    row = store.brief("brief_1")
    assert (row["first_draft"], row["brief_text"], row["sent_back"]) == ("weak", "strong", 1)
    assert store.delivery("job_a")["questions"] == 1
    assert store.orders_to_thread("t1") == 1

    numbers = report.build(store.rows())
    assert numbers["orders"] == 1 and numbers["sent_back_once"] == 1
    assert numbers["found_in_first_draft"] == {"no_done": 1}
    assert numbers["done_when"] == {"all": 1}
    assert numbers["done_when_by_first_draft"]["revised"] == {"all": 1}
    text = report.render(numbers, days=30)
    assert "sent back once:          1 of 1 (100 %)" in text


def test_an_answered_question_moves_the_delivery_to_the_job_the_work_goes_on_under(briefs_on):
    store = brief_log.get_log()
    store.note_attempt("brief_3", writer="lead", draft="d")
    store.note_delivery("brief_3", "job_asked", thread_id="t9")
    store.note_question("job_asked", continued_as="job_goes_on")
    assert store.delivery("job_asked") is None
    moved = store.delivery("job_goes_on")
    assert moved["questions"] == 1 and moved["brief_id"] == "brief_3"
    store.note_outcome("job_goes_on", "completed", [])
    assert store.rows()[0]["deliveries"][0]["outcome"] == "completed"


def test_the_report_runs_on_an_empty_record(briefs_on, capsys):
    assert report.main(["--since-days", "7"]) == 0
    assert "No order is on record" in capsys.readouterr().out


def test_done_when_points_join_a_jobs_verdict(briefs_on):
    from dodaios.core.delegate_verify import Check, Verification

    store = brief_log.get_log()
    store.note_attempt("brief_2", writer="lead", draft="d")
    store.note_delivery("brief_2", "job_b")
    assert acceptance.with_done_when("job_b") is None
    store.note_outcome("job_b", "completed", [
        {"point": "tests pass", "verdict": "confirmed", "evidence": "ran pytest"},
        {"point": "merged", "verdict": "open", "evidence": "no pull request"},
    ])
    judged = acceptance.with_done_when("job_b")
    assert judged.verdict == "unverified" and len(judged.checks) == 2
    store.note_outcome("job_b", "completed", [
        {"point": "tests pass", "verdict": "contradicted", "evidence": "pytest failed"},
    ])
    earlier = Verification("job_b", "coding", "unverified", "s", [Check("turn", True, "done")])
    judged = acceptance.with_done_when("job_b", earlier)
    assert judged.verdict == "failed" and [c.name for c in judged.checks][0] == "turn"
    store.note_outcome("job_b", "completed", [
        {"point": "tests pass", "verdict": "confirmed", "evidence": "ran pytest"},
    ])
    assert acceptance.with_done_when("job_b", earlier).verdict == "verified"
