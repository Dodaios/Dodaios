"""Side questions (``/btw``) in a coding thread: answered beside the work, never sent to it."""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import aside, typeahead
from dodaios.agent_chat import service as service_mod
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import _ask_aside, router


def test_parse_reads_the_question_of_a_btw_message():
    assert aside.parse("/btw what changed in the parser?") == "what changed in the parser?"
    assert aside.parse("  /BTW\nwhy two files?") == "why two files?"
    assert aside.parse("/btw") == ""
    assert aside.parse("/btwx no") is None
    assert aside.parse("please /btw no") is None


def test_only_a_claude_code_thread_takes_side_questions():
    thread = SimpleNamespace(surface="agent")
    assert aside.takes(thread, "claude-cli") and aside.takes(thread, "glm-cli")
    assert not aside.takes(thread, "codex-cli")
    assert not aside.takes(SimpleNamespace(surface="jarvis"), "claude-cli")


def test_the_copy_forks_the_conversation_keeps_nothing_and_asks_before_every_tool():
    argv = ["claude", "--print", "--permission-mode", "bypassPermissions", "--resume", "abc"]
    aside._as_copy(argv, has_conversation=True)
    assert argv[argv.index("--permission-mode") + 1] == "default"
    assert "--fork-session" in argv and "--no-session-persistence" in argv
    assert argv[argv.index("--max-turns") + 1] == "1"
    assert argv[argv.index("--resume") + 1] == "abc"

    fresh = ["claude", "--print", "--permission-mode", "default", "--session-id", "new-id"]
    aside._as_copy(fresh, has_conversation=False)
    assert "--session-id" not in fresh and "--fork-session" not in fresh
    assert "--no-session-persistence" in fresh


def test_a_claude_code_thread_lists_btw_first(monkeypatch, tmp_path):
    monkeypatch.setattr(
        typeahead,
        "cli_commands",
        lambda runner, folder: [
            typeahead.Suggestion(value="compact", label="compact", kind="command", group="cli"),
        ],
    )
    rows = typeahead.suggest(runner="claude-cli", cwd=tmp_path, trigger="/", surface="agent")
    assert [row["value"] for row in rows["items"]] == ["btw", "compact"]
    lead = typeahead.suggest(runner="claude-cli", cwd=tmp_path, trigger="/", surface="society")
    assert "btw" not in [row["value"] for row in lead["items"]]


_FAKE_CLI = textwrap.dedent(
    """
    import json, sys
    for line in sys.stdin:
        obj = json.loads(line)
        if obj.get("type") == "user":
            print(json.dumps({"type": "control_request", "request_id": "r1",
                              "request": {"subtype": "can_use_tool", "tool_name": "Bash",
                                          "input": {"command": "rm -rf build"}}}), flush=True)
        if obj.get("type") == "control_response":
            behavior = obj["response"]["response"]["behavior"]
            print(json.dumps({"type": "assistant", "message": {"content": [
                {"type": "text", "text": "The parser now reads tabs."}]}}), flush=True)
            print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                              "result": "The parser now reads tabs. (" + behavior + ")"}),
                  flush=True)
    """
)


def test_the_copy_runs_once_and_every_tool_call_is_refused(tmp_path):
    script = tmp_path / "fake_cli.py"
    script.write_text(_FAKE_CLI, encoding="utf-8")
    plan = SimpleNamespace(
        argv=[sys.executable, str(script)],
        env=None,
        control_init=json.dumps({"type": "control_request", "request": {"subtype": "initialize"}})
        + "\n",
        stdin_text=json.dumps({"type": "user", "message": {"content": "q"}}) + "\n",
    )
    answer, status = asyncio.run(aside._run(plan, tmp_path))
    assert status == "done"
    assert answer == "The parser now reads tabs. (deny)"


def _thread(tmp_path):
    store = AgentChatStore(tmp_path / "chat.db")
    sid = store.create_session(
        provider="claude-api", model="", effort="", surface="agent", cwd=str(tmp_path)
    ).session_id
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = AgentChatService(store)
    return store, sid, app


def _notices(store, sid, kind):
    return [
        e["payload"]
        for e in store.list_events(sid)
        if e["kind"] == "notice" and e["payload"].get("kind") == kind
    ]


def _until(predicate, limit_s: float = 5.0) -> None:
    deadline = time.monotonic() + limit_s
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.01)


def _scripted(monkeypatch, tmp_path, answer: str, status: str) -> list[str]:
    monkeypatch.setattr(service_mod, "session_runner", lambda session: "claude-cli")
    asked: list[str] = []

    async def plan(session, runner, question):
        asked.append(question)
        return SimpleNamespace(), tmp_path

    async def run(_plan, _cwd):
        return answer, status

    monkeypatch.setattr(aside, "_plan", plan)
    monkeypatch.setattr(aside, "_run", run)
    return asked


def test_btw_is_answered_beside_the_thread_and_never_reaches_the_agent(tmp_path, monkeypatch):
    asked = _scripted(monkeypatch, tmp_path, "It reads tabs now.", "done")
    store, sid, app = _thread(tmp_path)
    url = f"/api/agent-chat/sessions/{sid}"
    try:
        with TestClient(app) as client:
            sent = client.post(f"{url}/messages", json={"text": "/btw what changed in the parser?"})
            assert sent.status_code == 202
            aside_id = sent.json()["aside"]
            assert aside_id and sent.json()["turn_id"] == ""
            _until(lambda: bool(_notices(store, sid, aside.ANSWERED)))
            assert asked == ["what changed in the parser?"]
            opened = _notices(store, sid, aside.ASKED)
            assert opened[0]["question"] == "what changed in the parser?"
            closed = _notices(store, sid, aside.ANSWERED)[0]
            assert closed["status"] == "done" and closed["answer"] == "It reads tabs now."
            # No message and no turn: the agent never hears of it.
            assert not [e for e in store.list_events(sid) if e["kind"] == "user_message"]

            assert client.post(f"{url}/messages", json={"text": "/btw"}).status_code == 400

            gone = client.delete(f"{url}/asides/{aside_id}")
            assert gone.status_code == 200
            assert _notices(store, sid, aside.DISMISSED)[0]["aside_id"] == aside_id
    finally:
        store.close()


def test_a_side_question_that_needed_tools_says_so(tmp_path, monkeypatch):
    _scripted(monkeypatch, tmp_path, "", "tools")
    store, sid, app = _thread(tmp_path)
    try:
        with TestClient(app) as client:
            client.post(
                f"/api/agent-chat/sessions/{sid}/messages", json={"text": "/btw run the tests"}
            )
            _until(lambda: bool(_notices(store, sid, aside.ANSWERED)))
            closed = _notices(store, sid, aside.ANSWERED)[0]
            assert closed["status"] == "failed" and "normal message" in closed["error"]
    finally:
        store.close()


def test_other_agents_get_btw_as_a_normal_message(tmp_path, monkeypatch):
    monkeypatch.setattr(service_mod, "session_runner", lambda session: "codex-cli")
    store, sid, _app = _thread(tmp_path)
    try:
        svc = SimpleNamespace(store=store)
        assert asyncio.run(_ask_aside(svc, sid, "/btw hi", has_files=False)) == ""
    finally:
        store.close()
