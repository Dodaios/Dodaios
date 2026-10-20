"""The IDE's side chat shows an attached picture to the model it talks to.

The picture's description comes from a separate vision provider; when that
one has no quota left, a description-only chat would get a filename. Pinned
here: which attached files count as pictures (inside the chat's folder, a
type every seat accepts), how each kind of seat receives them (Claude Code as
an image block, Codex through ``--image``, an API seat on the user message
when it can see), and that the service hands them over for a plain chat only.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import plain_chat, runner_api, service
from dodaios.agent_chat.native_control import disable_cli_tools
from dodaios.agent_chat.runner_cli import claude_stream_input
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.protocols import BrainDelta, BrainRequest

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00"
    b"\x00\x00\x00IEND\xaeB`\x82"
)


def _drop(folder: Path, name: str, data: bytes = _PNG) -> dict[str, Any]:
    """A file as ``POST /attachments`` would have stored and described it."""
    drops = folder / ".jarvis" / "drops"
    drops.mkdir(parents=True, exist_ok=True)
    (drops / name).write_bytes(data)
    kind = "image" if Path(name).suffix.lower() in {".png", ".jpg", ".svg", ".bmp"} else "text"
    return {
        "name": name,
        "reference": f'".jarvis/drops/{name}"',
        "kind": kind,
        "detail": "",
        "described_by": "none",
        "note": "Could not be described (RateLimitError); it is attached as a file.",
    }


def _as_items(raw: list[dict[str, Any]]) -> list[Any]:
    from dodaios.agent_chat import attachments

    return attachments.to_analysis(raw)


def test_only_pictures_inside_the_chat_folder_count(tmp_path: Path) -> None:
    folder = tmp_path / "chat"
    folder.mkdir()
    outside = tmp_path / "secret.png"
    outside.write_bytes(_PNG)
    raw = [
        _drop(folder, "shot.png"),
        _drop(folder, "notes.txt", b"hello"),
        _drop(folder, "logo.svg", b"<svg/>"),
        # Request data: a reference that climbs out of the folder is refused.
        {"name": "secret.png", "reference": '"../secret.png"', "kind": "image"},
    ]

    found = plain_chat.image_paths(folder, _as_items(raw))

    assert found == [folder / ".jarvis" / "drops" / "shot.png"]


def test_claude_code_gets_the_picture_as_an_image_block() -> None:
    line = plain_chat.claude_message_with_images(
        claude_stream_input("what is wrong here?"), [("image/png", "QUJD")]
    )

    content = json.loads(line)["message"]["content"]
    assert content[0] == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
    }
    assert content[-1] == {"type": "text", "text": "what is wrong here?"}
    assert line.endswith("\n")


def test_each_cli_takes_the_pictures_its_own_way(tmp_path: Path) -> None:
    picture = tmp_path / "shot.png"
    picture.write_bytes(_PNG)

    # A plain chat's Codex turn: the tool switches come after the prompt marker.
    codex = SimpleNamespace(argv=["codex", "exec", "--json", "-"], shape="codex", stdin_text="hi")
    disable_cli_tools(codex, "codex-cli", keep_session=True)
    tail = codex.argv[codex.argv.index("-") :]
    assert plain_chat.attach_images(codex, "codex-cli", [picture])
    # One value per flag, in front of the marker, nothing else moved.
    marker = codex.argv.index("-")
    assert codex.argv[marker - 1] == f"--image={picture}"
    assert codex.argv[marker:] == tail

    claude = SimpleNamespace(argv=["claude"], shape="claude", stdin_text=claude_stream_input("hi"))
    assert plain_chat.attach_images(claude, "claude-cli", [picture])
    blocks = json.loads(claude.stdin_text)["message"]["content"]
    assert [block["type"] for block in blocks] == ["image", "text"]

    other = SimpleNamespace(argv=["grok", "-p", "hi"], shape="text", stdin_text=None)
    assert not plain_chat.attach_images(other, "grok-cli", [picture])
    assert other.argv == ["grok", "-p", "hi"]


class _SeeingBrain:
    """A model that can see, keeping the requests it was sent."""

    supports_vision = True
    seen: list[BrainRequest] = []

    def __init__(self, model: str | None = None) -> None:
        self.model = model

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        _SeeingBrain.seen.append(req)
        await asyncio.sleep(0)
        yield BrainDelta(content="A red error under the login form.")


class _BlindBrain(_SeeingBrain):
    supports_vision = False


async def _until_finished(queue: asyncio.Queue) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        event = await asyncio.wait_for(queue.get(), timeout=5)
        events.append(event)
        if event["kind"] == "turn_finished":
            return events


@pytest.mark.parametrize(("brain_class", "pictures"), [("_SeeingBrain", 1), ("_BlindBrain", 0)])
async def test_an_api_seat_sees_the_picture_when_its_model_can(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, brain_class: str, pictures: int
) -> None:
    _SeeingBrain.seen = []
    monkeypatch.setitem(
        runner_api.BRAIN_BY_PROVIDER,
        "fakeprov",
        ("tests.unit.agent_chat.test_plain_chat_images", brain_class),
    )
    store = AgentChatStore(":memory:")
    try:
        svc = AgentChatService(store, assistant_name=lambda: "Testo")
        session = svc.create_session(provider="fakeprov", cwd=str(tmp_path), surface="side")
        queue = svc.subscribe(session.session_id)

        await svc.send(session.session_id, "what is wrong here?", [_drop(tmp_path, "shot.png")])
        await _until_finished(queue)

        message = _SeeingBrain.seen[0].messages[-1]
        assert len(message.images) == pictures
        assert plain_chat.IMAGES_NOTE in str(message.content)
        if pictures:
            assert message.images[0].mime == "image/png"
    finally:
        store.close()


@pytest.mark.parametrize(("surface", "handed"), [("side", True), ("agent", False)])
async def test_the_service_hands_pictures_to_a_plain_chat_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str, handed: bool
) -> None:
    seen: list[tuple[str, ...]] = []

    async def _run_cli_turn(handle: Any, prompt: str, runner: str, **_kwargs: object) -> str:
        seen.append(handle.images)
        await handle.emit(
            service.make_event(
                "turn_finished",
                {"turn_id": handle.turn_id, "status": "done", "duration_ms": 1, "usage": {}},
            )
        )
        return "vendor-1"

    monkeypatch.setattr(service, "resolve_runner", lambda provider, **_kwargs: "claude-cli")
    monkeypatch.setattr(service, "run_cli_turn", _run_cli_turn)
    store = AgentChatStore(":memory:")
    try:
        svc = AgentChatService(store, assistant_name=lambda: "Testo")
        session = svc.create_session(provider="claude-api", cwd=str(tmp_path), surface=surface)
        queue = svc.subscribe(session.session_id)

        await svc.send(session.session_id, "look", [_drop(tmp_path, "shot.png")])
        await _until_finished(queue)

        expected = (str(tmp_path / ".jarvis" / "drops" / "shot.png"),) if handed else ()
        assert seen == [expected]
    finally:
        store.close()
