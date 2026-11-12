"""``/api/agent-chat/lead/files``: the files the assistant linked in its conversation."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import lead_files
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router


def _file(folder: Path, name: str, mtime: int, body: str = "x") -> Path:
    path = folder / name
    path.write_text(body, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_a_message_names_its_local_links_and_nothing_else() -> None:
    text = (
        "Done: [report.xlsx](/Users/ada/work/report.xlsx) and "
        "[a name with spaces](</Users/ada/My Files/plan v2.pdf>), "
        "see [the docs](https://example.com/a.pdf), ![chart](/api/outputs/run/files/chart.png) "
        'and [again](/Users/ada/work/report.xlsx "title"). `[code](/not/a/link` stays text.'
    )
    assert lead_files.linked_paths(text) == [
        "/Users/ada/work/report.xlsx",
        "/Users/ada/My Files/plan v2.pdf",
    ]
    assert lead_files.linked_paths("") == []


def test_only_files_that_exist_are_listed_once_and_the_newest_leads(tmp_path: Path) -> None:
    sheet = _file(tmp_path, "Nvidia.xlsx", 2_000)
    clip = _file(tmp_path, "clip.mp4", 3_000)
    script = _file(tmp_path, "run.bat", 4_000)
    (tmp_path / "folder").mkdir()
    gone = tmp_path / "no.pdf"
    messages = [
        (30, f"Here is [the clip]({clip}) and a folder: [folder]({tmp_path / 'folder'})"),
        (20, f"Again [the sheet]({sheet}), a script [run]({script}), gone [x]({gone})"),
        (10, f"The file is ready: [Nvidia.xlsx]({sheet})"),
    ]

    rows = lead_files.handed_over(messages)

    assert [row["name"] for row in rows] == ["clip.mp4", "Nvidia.xlsx"]
    assert rows[1] == {
        "path": str(sheet.resolve()),
        "name": "Nvidia.xlsx",
        "size": 1,
        "mtime": 2_000.0,
        # The newest message that links it.
        "linked_ms": 20,
    }
    assert [row["name"] for row in lead_files.handed_over(messages, limit=1)] == ["clip.mp4"]


def test_a_vanished_file_is_not_replaced_by_one_of_the_same_name(
    tmp_path: Path, monkeypatch
) -> None:
    elsewhere = _file(tmp_path, "report.pdf", 1_000)
    # The opener would find a file of that name in the person's folders.
    monkeypatch.setattr(lead_files, "prepare_chat_open", lambda raw: elsewhere)
    assert lead_files.handed_over([(1, "[report](/gone/away/report.pdf)")]) == []


def test_the_route_reads_the_conversation_and_nothing_before_one_exists(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = AgentChatService(store)
    sheet = _file(tmp_path, "Nvidia.xlsx", 2_000)
    with TestClient(app) as client:
        assert client.get("/api/agent-chat/lead/files").json() == {"files": []}

        lead = store.create_session(
            provider="claude-api", model="m", effort="", cwd=str(tmp_path), surface="jarvis"
        ).session_id
        other = store.create_session(
            provider="claude", model="m", effort="", cwd=str(tmp_path), surface="agent"
        ).session_id
        store.set_lead_session_id(lead)
        store.append_event(lead, make_event("assistant_text", {"text": f"Ready: [sheet]({sheet})"}))
        store.append_event(lead, make_event("user_message", {"text": f"[mine]({sheet})"}))
        clip = _file(tmp_path, "clip.mp4", 3_000)
        store.append_event(other, make_event("assistant_text", {"text": f"[clip]({clip})"}))

        rows = client.get("/api/agent-chat/lead/files").json()["files"]
    # A coding thread's files are its own, not the assistant's.
    assert [row["name"] for row in rows] == ["Nvidia.xlsx"]
    assert rows[0]["path"] == str(sheet.resolve())
