"""Live composer reuses uploads and targets only the selected active call."""

from types import SimpleNamespace
from urllib.parse import parse_qs, unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.live import runtime
from dodaios.ui.web.live_routes import _composer_attachments, router


def attachment(tmp_path, name="note.txt", kind="text", detail="Attached document contents"):
    folder = tmp_path / ".jarvis" / "drops"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"image" if kind == "image" else b"document")
    return {
        "name": name,
        "reference": f'".jarvis/drops/{name}"',
        "kind": kind,
        "detail": detail,
        "described_by": "extraction",
        "note": "",
    }


def test_live_uploads_keep_images_and_extract_documents_in_one_content_path(tmp_path):
    rows = _composer_attachments(
        str(tmp_path),
        [
            attachment(tmp_path),
            attachment(tmp_path, "shot.png", "image", "Screenshot"),
        ],
    )
    assert len(rows) == 2
    assert "Attached document contents" in rows[0][1][0]["text"]
    assert rows[1][1][1]["type"] == "input_image"
    assert rows[1][1][1]["image_url"].startswith("data:image/png;base64,")
    assert rows[0][3]["name"] == "note.txt" and "url" not in rows[0][3]
    assert rows[1][3]["name"] == "shot.png"
    url = rows[1][3]["url"]
    assert url.startswith("/api/agent-chat/attachments/file?")
    query = parse_qs(url.split("?", 1)[1])
    assert query["reference"] == ['".jarvis/drops/shot.png"']
    # The chat folder is the cwd. macOS keeps that folder under /private/var,
    # so a ban on the word "private" fails there. The absolute image path stays out.
    shown = unquote(url)
    image = tmp_path / ".jarvis" / "drops" / "shot.png"
    assert str(image) not in shown
    assert str(image.resolve()) not in shown


def test_live_image_url_allows_a_chat_folder_named_private(tmp_path):
    """macOS temp lives under /private/var. That folder name is not a leaked file."""
    root = tmp_path / "private" / "var"
    root.mkdir(parents=True)
    rows = _composer_attachments(str(root), [attachment(root, "shot.png", "image", "Screenshot")])
    url = rows[0][3]["url"]
    shown = unquote(url)
    assert "private" in shown
    image = root / ".jarvis" / "drops" / "shot.png"
    assert str(image) not in shown
    assert str(image.resolve()) not in shown


def test_live_upload_never_reads_a_foreign_file(tmp_path):
    row = attachment(tmp_path)
    private = tmp_path / "private.txt"
    private.write_text("private", encoding="utf-8")
    row["reference"] = '"private.txt"'
    with pytest.raises(ValueError, match="existing upload"):
        _composer_attachments(str(tmp_path), [row])


def test_unreadable_file_is_rejected_instead_of_silently_accepted(tmp_path):
    row = attachment(tmp_path, "archive.zip", "other", "")
    with pytest.raises(ValueError, match="No readable text"):
        _composer_attachments(str(tmp_path), [row])


@pytest.mark.parametrize("raw", [[{}], [{"reference": "x"}]])
def test_invalid_upload_metadata_is_rejected(tmp_path, raw):
    with pytest.raises(ValueError, match="attachment"):
        _composer_attachments(str(tmp_path), raw)


def test_route_delivers_on_the_existing_session_loop_and_rejects_stale_ids(tmp_path, monkeypatch):
    delivered = []

    class ExistingSession:
        session_id = "existing-call"
        is_active = True
        composer_available = True

        async def submit_composer(self, **kwargs):
            delivered.append(kwargs)

    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = SimpleNamespace(default_cwd=lambda surface: str(tmp_path))
    session = ExistingSession()
    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(runtime, "_owners", {})
    with TestClient(app) as client:
        client.portal.call(runtime.register, session)
        assert client.get("/api/live/composer").json() == {"session_id": "existing-call"}
        body = {
            "session_id": "existing-call",
            "request_id": "request-one",
            "text": "Read it",
            "attachments": [attachment(tmp_path)],
        }
        response = client.post("/api/live/composer", json=body)
        assert response.status_code == 200, response.text
        assert len(delivered) == 1 and delivered[0]["text"] == "Read it"
        assert delivered[0]["attachments"][0][1][0]["type"] == "input_text"
        assert delivered[0]["display_attachments"][0]["name"] == "note.txt"
        assert delivered[0]["display_attachments"][0]["size_bytes"] == len(b"document")
        assert "url" not in delivered[0]["display_attachments"][0]
        assert runtime.active() == (session,)
        body["session_id"] = "previous-call"
        assert client.post("/api/live/composer", json=body).status_code == 409
        assert len(delivered) == 1
        client.portal.call(runtime.unregister, session.session_id)


@pytest.mark.asyncio
async def test_composer_uses_and_pins_existing_chat_binding_across_view_changes(tmp_path):
    from dodaios.ui.web.live_routes import _composer_cwd

    pinned = []
    target = SimpleNamespace(session_id="bound-chat", surface="jarvis", cwd=str(tmp_path))
    svc = SimpleNamespace(
        voice_session_continued=None,
        voice_chat_id="bound-chat",
        voice_chat_fresh=False,
        voice_call_chat=lambda call: None,
        pin_voice_call=lambda call, chat: pinned.append((call, chat)),
        store=SimpleNamespace(get_session=lambda identifier: target),
        default_cwd=lambda surface: "unused",
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(agent_chat=svc)))
    session = SimpleNamespace(session_id="live-call")
    assert await _composer_cwd(request, session) == str(tmp_path)
    assert pinned == [("live-call", "bound-chat")]
    svc.voice_chat_id = "different-chat"
    target.cwd = "different-folder"
    assert await _composer_cwd(request, session) == str(tmp_path)
    assert len(pinned) == 1
