"""A brief on its way to a coding thread: checked, assembled, followed and judged.

The same rig as the chat-thread contract: the real chat service and store, the
real orchestrator, a scripted runner in place of the coding CLI.
"""

# ruff: noqa: F811 - ``rig`` is a fixture imported from the chat-thread contract
from __future__ import annotations

import asyncio
import json
from typing import Any

from dodaios.agent_chat.events import make_event
from dodaios.briefs import log as brief_log
from dodaios.briefs import standing
from dodaios.briefs.profiles import CODEX
from dodaios.orchestrator import jobs
from tests.contract.test_workspace_chat_threads import (  # noqa: F401 - fixtures
    Rig,
    _as_from_an_earlier_boot,
    app_chat,
    own_worktrees,
    rig,
)

WEAK = (
    "The upload looks bad, clearly improve it.\n1. Open sync/client.py.\n2. Run `pytest`.\n"
    "3. Then commit."
)
STRONG = (
    "Uploads time out after 10 s on a slow connection and the note is lost. Make an upload "
    "survive a slow connection without losing the note.\n\n"
    "Done when: `python -m pytest tests/sync` is green."
)
SAID = "der upload ist kaputt, mach das robust"  # i18n-allow: what the person dictated


async def _create(rig: Rig, prompt: str, **args: Any) -> dict[str, Any]:
    return await rig.orchestrator.run(
        {"action": "create", "cli": "Codex", "prompt": prompt, "_person_words": SAID, **args}
    )


def _reports(rig: Rig, needle: str) -> list[str]:
    """What came back to the conversation, as far as it mentions ``needle``."""
    texts = [
        f"{getattr(event, 'text', '')}\n{getattr(event, 'report', '') or ''}"
        for event in rig.results()
    ]
    return [text for text in texts if needle in text]


def _ran(command: str, ok: bool = True) -> list[dict[str, Any]]:
    return [
        make_event("tool_call", {"call_id": "c1", "name": "RunCommand",
                                 "input": {"command": command}}),
        make_event("tool_result", {"call_id": "c1", "output": "ok" if ok else "1 failed",
                                   "is_error": not ok}),
    ]


async def test_a_brief_with_faults_goes_back_before_anything_is_created(rig: Rig, briefs_on):
    result = await _create(rig, WEAK)

    assert result["status"] == "needs_revision" and result["success"] is False
    assert rig.threads() == [] and rig.service.prompts == []
    assert {row["code"] for row in result["fix"]} >= {"step_script", "left_open", "no_done"}
    assert "brief_kit" in result and "revised brief is sent as it is" in result["reason"]


async def test_the_revision_is_sent_assembled_and_the_thread_shows_the_brief(rig: Rig, briefs_on):
    await _create(rig, WEAK)
    result = await _create(rig, STRONG)

    assert result["status"] == "created", result
    await rig.settle()
    [thread] = rig.threads()
    [(_, sent)] = rig.service.prompts
    # What the agent reads: the brief, the person's own words, the line its model wants.
    assert sent.startswith("Uploads time out")
    assert f"> {SAID}" in sent
    assert sent.rstrip().endswith(CODEX.closing)
    # What the thread shows: the brief as it was written.
    message = next(
        e for e in rig.service.store.list_events(thread.session_id) if e["kind"] == "user_message"
    )
    assert message["payload"]["typed"] == STRONG
    assert result["brief"]["brief_id"].startswith("brief_")


async def test_no_effort_named_means_the_job_decides_and_a_named_one_stays(rig: Rig, briefs_on):
    await _create(rig, STRONG)
    await _create(rig, STRONG + " Second agent.", effort="high", _dispatch_scope="second")
    await rig.settle()
    efforts = {t.effort for t in rig.threads()}
    assert efforts == {"medium", "high"}
    rows = brief_log.get_log().rows()
    sources = {d["effort_source"] for row in rows for d in row["deliveries"]}
    assert sources == {"job_size", "named"}


async def _create_scripted(rig: Rig, steps: Any) -> tuple[dict[str, Any], str]:
    """Create one agent whose turns run ``steps()``; the receipt and the thread's id.

    The steps are made after the order went out: an event is stamped when it
    is made, and only what happens after the order counts as its work.
    """
    rig.service.hold = asyncio.Event()
    result = await _create(rig, STRONG)
    session_id = result["agents"][0]["terminal_id"].removeprefix("thread:")
    rig.service.steps[session_id] = steps()
    rig.service.hold.set()
    rig.service.hold = None
    return result, session_id


async def test_the_done_when_points_are_checked_when_the_agent_reports(rig: Rig, briefs_on):
    result, _ = await _create_scripted(
        rig, lambda: [[*_ran("python -m pytest tests/sync"), "All done."]]
    )
    await rig.settle()

    job_id = result["deliveries"][0]["job_id"]
    job = jobs.get_ledger().get(job_id)
    assert job.meta["brief"]["criteria"][0]["kind"] == "command"
    [report] = _reports(rig, "All done.")
    assert "Done-when check by Dodaios" in report
    assert "1 of 1 confirmed" in report
    delivery = brief_log.get_log().delivery(job_id)
    assert delivery["outcome"] == "completed"
    assert json.loads(delivery["acceptance"])[0]["verdict"] == "confirmed"


async def test_after_a_restart_the_job_still_checks_its_done_when_points(
    rig: Rig, briefs_on, app_chat
):
    from dodaios.agent_chat.parked_work import _ledger_work

    rig.service.hold = asyncio.Event()
    result = await _create(rig, STRONG)
    session_id = result["agents"][0]["terminal_id"].removeprefix("thread:")
    rig.service.steps[session_id] = [[*_ran("python -m pytest tests/sync"), "All done."]]
    job_id = result["deliveries"][0]["job_id"]
    _as_from_an_earlier_boot(job_id)
    # A restart forgets which turns were followed; only the job's record is left.
    rig.orchestrator.threads._tracked.clear()
    # The turn was carried across the restart and ends now.
    rig.service.hold.set()
    rig.service.hold = None
    await rig.settle()
    assert brief_log.get_log().delivery(job_id)["outcome"] == ""

    work = _ledger_work(f"coding-thread:{job_id}", "Codex")
    assert work is not None
    answer = await work.probe()
    assert answer["status"] == "done", answer
    delivery = brief_log.get_log().delivery(job_id)
    assert delivery["outcome"] == "completed"
    assert json.loads(delivery["acceptance"])[0]["verdict"] == "confirmed"


async def test_a_done_claim_without_the_check_is_reported_as_open(rig: Rig, briefs_on):
    result = await _create(rig, STRONG)
    await rig.settle()
    job_id = result["deliveries"][0]["job_id"]
    acceptance = json.loads(brief_log.get_log().delivery(job_id)["acceptance"])
    assert acceptance[0]["verdict"] == "open" and "was not run" in acceptance[0]["evidence"]
    evidence = await jobs.probe_for(job_id)()
    assert "0 of 1 confirmed, 1 open" in evidence["done_when_check"]


async def test_a_check_that_passed_before_the_last_change_is_open(rig: Rig, briefs_on):
    def steps() -> list[Any]:
        edit = make_event("tool_call", {
            "call_id": "e1", "name": "Edit", "input": {"file_path": "sync/client.py"},
        })
        return [[*_ran("python -m pytest tests/sync"), edit, "All done."]]

    await _create_scripted(rig, steps)
    await rig.settle()

    [report] = _reports(rig, "All done.")
    assert "0 of 1 confirmed, 1 open" in report
    assert "1 file change(s) followed that run and it was not run again" in report


async def test_a_follow_up_without_points_goes_on_with_the_threads_order(rig: Rig, briefs_on):
    """The agent asks in its reply and the answer is a plain follow-up message."""
    result, session_id = await _create_scripted(
        rig, lambda: [["Memory or disk?"], [*_ran("python -m pytest tests/sync"), "Done."]]
    )
    [agent] = result["agents"]
    await rig.settle()
    first_job = result["deliveries"][0]["job_id"]
    asked = await jobs.probe_for(first_job)()
    assert asked["report"] == "Memory or disk?"
    assert "0 of 1 confirmed, 1 open" in asked["done_when_check"]

    # As after a restart of the app: the standing order is read from the record.
    rig.orchestrator.threads._orders.clear()
    sent = await rig.orchestrator.run({
        "action": "send", "terminal_id": agent["terminal_id"],
        "prompt": "On disk. Go ahead as briefed.", "_person_words": SAID,
    })
    assert sent["status"] == "accepted", sent
    await rig.settle()

    done = _reports(rig, "Done-when check by Dodaios")
    assert "1 of 1 confirmed" in done[-1]
    assert "the order this turn continues" in done[-1]
    store = brief_log.get_log()
    followed = store.delivery(sent["job_id"])
    assert followed["outcome"] == "completed"
    assert json.loads(followed["acceptance"])[0]["verdict"] == "confirmed"
    # The turn that asked keeps its own end: the later turn is not its result.
    again = await jobs.probe_for(first_job)()
    assert again["report"] == "Memory or disk?"
    assert json.loads(store.delivery(first_job)["acceptance"])[0]["verdict"] == "open"


async def test_an_order_without_points_still_has_its_end_on_record(
    rig: Rig, briefs_on, monkeypatch
):
    from dataclasses import replace

    from dodaios.briefs import settings as brief_settings

    # With the check only remarking, a brief that names no done-when point goes out.
    monkeypatch.setattr(brief_settings, "_CURRENT", replace(briefs_on, check="note"))
    result = await _create(rig, "Make an upload survive a slow connection.")
    assert result["status"] == "created", result
    await rig.settle()

    job_id = result["deliveries"][0]["job_id"]
    assert not jobs.get_ledger().get(job_id).meta["brief"]["criteria"]
    assert brief_log.get_log().delivery(job_id)["outcome"] == "completed"


async def test_the_lead_answers_an_agents_question_and_the_work_goes_on(rig: Rig, briefs_on):
    from dodaios.agent_chat import turn_prompts

    block = "```jarvis-ask\n" + json.dumps({"questions": [{
        "question": "Keep failed uploads in memory or on disk?",
        "options": [{"label": "On disk", "description": "survives a restart"},
                    {"label": "In memory", "description": "simpler"}],
    }]}) + "\n```"
    specs = turn_prompts.parse_ask_block(block)

    def ask() -> list[Any]:
        # The card a reply ending in such a block opens (``_open_turn_prompts``).
        return [
            "Which store?",
            make_event("question_required", {
                "question_id": "q-1", "asker": "",
                "questions": [spec.to_payload() for spec in specs], "deferred": True,
            }),
        ]

    result, _ = await _create_scripted(
        rig, lambda: [ask(), [*_ran("python -m pytest tests/sync"), "Done."]]
    )
    [agent] = result["agents"]
    await rig.settle()

    seen = await rig.orchestrator.run({"action": "observe", "terminal_id": agent["terminal_id"]})
    assert seen["question"]["asks"][0]["options"] == ["On disk", "In memory"]

    answered = await rig.orchestrator.run(
        {"action": "respond", "terminal_id": agent["terminal_id"], "prompt": "On disk"}
    )
    assert answered["status"] == "answered" and answered["job_id"]
    await rig.settle()
    assert "On disk" in rig.service.prompts[-1][1]
    assert "answered this on the person's behalf" in rig.service.prompts[-1][1]
    assert rig.service.authors[-1]["agent_id"] == "jarvis"
    # The order's done-when points follow the continued work.
    done = _reports(rig, "Done-when check by Dodaios")
    assert done and "1 of 1 confirmed" in done[-1]
    # The delivery followed the work to the job it went on under, and ended there.
    moved = brief_log.get_log().delivery(answered["job_id"])
    assert moved["questions"] == 1 and moved["outcome"] == "completed"
    assert brief_log.get_log().delivery(result["deliveries"][0]["job_id"]) is None


async def test_a_live_question_is_answered_under_the_job_that_asked(rig: Rig, briefs_on):
    """Claude Code asks mid-turn: the same turn goes on, so the job that asked stays."""
    from dodaios.agent_chat.questions import parse_questions

    got: list[Any] = []

    async def ask(handle: Any) -> None:
        specs = parse_questions({"questions": [{
            "question": "Which file format?",
            "options": [{"label": "JSON", "description": "a list"},
                        {"label": "CSV", "description": "rows"}],
        }]})
        got.extend(await rig.service.ask_questions(
            handle.session.session_id, specs, timeout_s=None, rationed=False
        ))

    result, session_id = await _create_scripted(
        rig, lambda: [[ask, *_ran("python -m pytest tests/sync"), "Done."]]
    )
    [agent] = result["agents"]
    first_job = result["deliveries"][0]["job_id"]
    for _ in range(200):
        await asyncio.sleep(0.01)
        if rig.service.pending_questions(session_id):
            break
    seen = await jobs.probe_for(first_job)()
    assert seen["status"] == "needs_input" and seen["question"]["asks"][0]["options"] == [
        "JSON", "CSV",
    ]

    answered = await rig.orchestrator.run(
        {"action": "respond", "terminal_id": agent["terminal_id"], "prompt": "JSON"}
    )
    assert answered["status"] == "answered"
    assert answered["job_id"] == first_job
    await rig.settle()

    # The agent learns who answered, and the card says so too.
    assert got[0].answer == "JSON" and got[0].source == "delegator"
    resolved = [e for e in rig.service.store.list_events(session_id)
                if e["kind"] == "question_resolved"]
    assert resolved[-1]["payload"]["answers"][0]["source"] == "delegator"
    # One report, under the job that asked, with the order's done-when check.
    done = _reports(rig, "Done.")
    assert len(done) == 1 and "1 of 1 confirmed" in done[0]
    delivery = brief_log.get_log().delivery(first_job)
    assert delivery["questions"] == 1 and delivery["outcome"] == "completed"


async def test_a_thread_in_a_worktree_of_its_own_reads_the_brief_there(
    rig: Rig, briefs_on, own_worktrees
):
    project = rig.workspace.folder
    brief = (
        f"`VALUE` in {project}/app.py is 1 and must be 2, because the export reads it. "
        "Set it to 2.\n\nDone when: `python -m pytest -q` is green."
    )
    result = await _create(rig, brief)
    assert result["status"] == "created", [f["code"] for f in result.get("fix", [])]
    [agent] = result["agents"]
    thread = rig.service.store.get_session(agent["terminal_id"].removeprefix("thread:"))
    assert thread.cwd != project
    [text] = [sent for sid, sent in rig.service.prompts if sid == thread.session_id]
    # What the agent reads names the worktree, and still carries the person's words.
    assert f"{thread.cwd}/app.py" in text and f"{project}/app.py" not in text
    assert "You work in a git worktree of your own" in text
    assert SAID in text
    # The thread shows the writer's brief, localized the same way.
    message = next(e for e in rig.service.store.list_events(thread.session_id)
                   if e["kind"] == "user_message")["payload"]
    shown = message.get("display_text") or message.get("typed") or ""
    assert f"{thread.cwd}/app.py" in shown and SAID not in shown


async def test_respond_refuses_when_there_is_nothing_the_lead_may_answer(rig: Rig, briefs_on):
    result = await _create(rig, STRONG)
    await rig.settle()
    [agent] = result["agents"]
    refused = await rig.orchestrator.run(
        {"action": "respond", "terminal_id": agent["terminal_id"], "prompt": "yes"}
    )
    assert refused["status"] == "not_accepted" and "no open question" in refused["reason"]


async def test_a_thread_the_person_opened_gets_the_rules_with_the_first_order(
    rig: Rig, briefs_on
):
    from dodaios.agentic_ide.chat_threads import chat_provider

    row = chat_provider("codex")
    session = rig.service.create_session(
        provider=row.id, cwd=rig.workspace.folder, surface="agent"
    )
    await rig.service.send(session.session_id, "hello, are you there?")
    await rig.settle()
    target = "thread:" + session.session_id

    first = await rig.orchestrator.run(
        {"action": "send", "terminal_id": target, "prompt": STRONG, "_person_words": SAID}
    )
    assert first["status"] == "accepted", first
    await rig.settle()
    assert standing.MARK in rig.service.prompts[-1][1]

    # A follow-up is not held to a first order's rules and carries no second copy.
    again = await rig.orchestrator.run(
        {"action": "send", "terminal_id": target, "prompt": "Thanks. Now also land it."}
    )
    assert again["status"] == "accepted", again
    await rig.settle()
    assert standing.MARK not in rig.service.prompts[-1][1]


async def test_the_kit_is_read_without_sending_anything(rig: Rig, briefs_on):
    got = await rig.orchestrator.run(
        {"action": "brief_kit", "cli": "Codex", "prompt": "the upload breaks",
         "_person_words": SAID}
    )
    assert got["status"] == "prepared" and got["nothing_sent"] is True
    assert "Codex" in got["brief_kit"]["recipient"]["recipient"]
    assert rig.threads() == []


async def test_the_kit_is_read_in_a_request_that_asks_for_a_new_agent(rig: Rig, briefs_on):
    # A request for a NEW agent refuses every action on existing panes; reading
    # the kit for that new agent is none of them.
    got = await rig.orchestrator.run(
        {"action": "brief_kit", "cli": "Codex", "prompt": "the upload breaks",
         "_person_words": SAID, "_requires_new": True, "_dispatch_scope": "turn-9"}
    )
    assert got["status"] == "prepared", got


async def test_switched_off_a_brief_goes_out_exactly_as_written(rig: Rig):
    result = await _create(rig, WEAK)
    assert result["status"] == "created"
    await rig.settle()
    assert rig.service.prompts[0][1] == WEAK
    assert "brief" not in result
