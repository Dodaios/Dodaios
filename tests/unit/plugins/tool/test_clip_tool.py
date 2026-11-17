"""The ``clip`` tool: every operation on real clip nodes in a temporary store.

The heavy parts (decoding a file, hearing speech, finding pauses, drawing
frames, encoding an MP4) are replaced by small fakes: they have tests of their
own (``tests/unit/nodes/clip``). What is tested here is what the tool does
with their answers: the spec it saves, the times it reports, the pictures it
hands back, and its registration.
"""

from __future__ import annotations

import io
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.nodes.clip import captions, export, media, silence, transcribe
from dodaios.nodes.store import NodeStore
from dodaios.orchestrator import jobs
from dodaios.plugins.tool import clip as clip_tool
from dodaios.plugins.tool.clip import GUIDE, ClipTool

REPO = Path(__file__).resolve().parents[4]
TAKE = "a" * 24
SONG = "b" * 24


@pytest.fixture(autouse=True)
def ledger():
    store = jobs.JobLedger(":memory:")
    jobs.set_ledger(store)
    try:
        yield store
    finally:
        jobs.set_ledger(None)
        store.close()


@pytest.fixture
def cards(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    posted: list[tuple[str, dict]] = []

    async def fake_post(session_id: str, payload: dict) -> bool:
        posted.append((session_id, payload))
        return True

    monkeypatch.setattr(clip_tool, "post_card", fake_post)
    return posted


@pytest.fixture
def imports(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """``import_media`` that files a fake take or song in the clip's library."""
    seen: list[Path] = []

    def fake_import(node_dir: Path, source: Path, name: str | None = None) -> tuple[str, dict]:
        seen.append(source)
        sound = source.suffix == ".mp3"
        media_id = SONG if sound else TAKE
        file = f"{media_id}{source.suffix}"
        folder = media.media_dir(node_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / file).write_bytes(b"x")
        if sound:
            return media_id, {
                "kind": "audio",
                "name": name,
                "file": file,
                "seconds": 60,
                "audio": True,
            }
        entry = {
            "kind": "video",
            "name": name,
            "file": file,
            "seconds": 20,
            "width": 1080,
            "height": 1920,
            "audio": True,
        }
        return media_id, entry

    monkeypatch.setattr(media, "import_media", fake_import)
    return seen


def _ctx(session: str = "lead-1") -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{session}", "output_language": "de"},
        memory_read=None,
    )


def _files(tmp_path: Path) -> list[str]:
    take = tmp_path / "in" / "take.mp4"
    song = tmp_path / "in" / "song.mp3"
    take.parent.mkdir(exist_ok=True)
    take.write_bytes(b"v")
    song.write_bytes(b"a")
    return [str(take), str(song)]


async def _made(tmp_path: Path, **args: Any) -> tuple[ClipTool, NodeStore, str]:
    store = NodeStore(root=tmp_path / "nodes")
    tool = ClipTool(store=store)
    result = await tool.execute(
        {"operation": "create", "title": "Reel", "files": _files(tmp_path), **args}, _ctx()
    )
    assert result.success, result.error
    return tool, store, store.list_nodes()[0].id


# ------------------------------------------------------------------ create, edit, read


async def test_guide_carries_every_action_and_the_doctrine() -> None:
    from dodaios.nodes.clip.ops import ACTIONS

    result = await ClipTool().execute({"operation": "guide"}, _ctx())
    assert result.success and result.output == GUIDE
    assert all(action in GUIDE for action in ACTIONS)
    assert "safe zone" in GUIDE and "Hook" in GUIDE and len(GUIDE) < 6_500


async def test_create_imports_the_files_and_lays_them_out(
    tmp_path: Path, imports: list[Path], cards: list
) -> None:
    _, store, node_id = await _made(tmp_path)
    spec = store.get(node_id).spec
    assert spec["format"] == "tall" and set(spec["media"]) == {TAKE, SONG}
    assert [s["type"] for s in spec["scenes"]] == ["video"]  # the blank card was replaced
    assert spec["scenes"][0]["seconds"] == 20
    music = spec["tracks"][0]["items"][0]
    assert music["media"] == SONG and music["duck"] is True and music["seconds"] == 20
    assert cards and cards[0][1]["node_type"] == "motion"


async def test_edit_runs_actions_and_read_shows_the_ids(tmp_path: Path, imports, cards) -> None:
    tool, store, node_id = await _made(tmp_path)
    result = await tool.execute(
        {
            "operation": "edit",
            "clip": node_id,
            "actions": [
                {"do": "split", "id": "v1", "at": 8},
                {"do": "add_text", "text": "WAIT FOR IT", "start": 0, "seconds": 2, "id": "hook"},
            ],
        },
        _ctx(),
    )
    assert result.success, result.error
    assert "the second half is v2" in result.output and "look" in result.output
    read = await tool.execute({"operation": "read", "clip": "Reel"}, _ctx())
    assert "v1: 0.00-8.00 s" in read.output and "v2: 8.00-20.00 s" in read.output
    assert "hook: 0.00-2.00 s" in read.output


async def test_a_failed_action_changes_nothing(tmp_path: Path, imports, cards) -> None:
    tool, store, node_id = await _made(tmp_path)
    version = store.get(node_id).version
    result = await tool.execute(
        {"operation": "edit", "clip": node_id, "actions": [{"do": "split", "id": "v9", "at": 1}]},
        _ctx(),
    )
    assert not result.success and "Action 1 (split)" in result.error
    assert store.get(node_id).version == version


async def test_import_with_place_and_a_relative_path(tmp_path: Path, imports, cards) -> None:
    store = NodeStore(root=tmp_path / "nodes")
    tool = ClipTool(store=store)
    made = await tool.execute({"operation": "create", "title": "Empty", "format": "wide"}, _ctx())
    assert made.success
    node_id = store.list_nodes()[0].id
    take, _ = _files(tmp_path)
    result = await tool.execute(
        {"operation": "import", "clip": node_id, "files": [take], "place": True}, _ctx()
    )
    assert result.success and f"{TAKE}: take.mp4 (video, 20.00 s, with sound)" in result.output
    assert store.get(node_id).spec["scenes"][0]["media"] == TAKE
    wrong = await tool.execute(
        {"operation": "import", "clip": node_id, "files": ["take.mp4"]}, _ctx()
    )
    assert not wrong.success and "absolute path" in wrong.error


async def test_the_tool_refuses_a_node_that_is_no_clip(tmp_path: Path) -> None:
    store = NodeStore(root=tmp_path)
    store.create(type="docs", title="Notes", spec={"markdown": "x"})
    result = await ClipTool(store=store).execute({"operation": "read", "clip": "Notes"}, _ctx())
    assert not result.success and "not a clip" in result.error


# ------------------------------------------------------------------ hearing


def _words(*pairs: tuple[str, float]) -> list[dict[str, Any]]:
    return [{"w": word, "s": at, "e": at + 0.3} for word, at in pairs]


async def test_transcribe_a_piece_reports_clip_time(
    tmp_path: Path, imports, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, store, node_id = await _made(tmp_path)
    await tool.execute(
        {"operation": "edit", "clip": node_id, "actions": [{"do": "trim", "id": "v1", "start": 2}]},
        _ctx(),
    )
    asked: list[tuple[float, float | None]] = []

    def fake(path: Path, start: float = 0, end: float | None = None, language: str | None = None):
        asked.append((start, end))
        return {"language": "en", "text": "so um hello", "words": _words(("so", 2.5), ("um", 3.0))}

    monkeypatch.setattr(transcribe, "transcribe_file", fake)
    result = await tool.execute({"operation": "transcribe", "clip": node_id, "id": "v1"}, _ctx())
    assert result.success, result.error
    assert asked == [(2.0, 20.0)]
    # The piece now starts at source 2 s at clip time 0: "um" at source 3 s is at 1.00.
    assert "so@0.50 um@1.00" in result.output and "clip time" in result.output


async def test_captions_from_speech_are_saved(
    tmp_path: Path, imports, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, store, node_id = await _made(tmp_path)
    heard = _words(("Three", 0.2), ("things", 0.5), ("nobody", 0.8), ("tells", 1.1), ("you.", 1.4))
    monkeypatch.setattr(captions, "timeline_words", lambda spec, node_dir, language=None: heard)
    result = await tool.execute({"operation": "captions", "clip": node_id, "style": "bold"}, _ctx())
    assert result.success, result.error
    saved = store.get(node_id).spec["captions"]
    assert saved["style"] == "bold" and saved["items"]
    assert " ".join(line["text"] for line in saved["items"]) == "Three things nobody tells you."


async def test_captions_without_speech_say_so(
    tmp_path: Path, imports, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, _, node_id = await _made(tmp_path)
    monkeypatch.setattr(captions, "timeline_words", lambda spec, node_dir, language=None: [])
    result = await tool.execute({"operation": "captions", "clip": node_id}, _ctx())
    assert not result.success and "No speech" in result.error


async def test_silences_report_and_apply(
    tmp_path: Path, imports, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, store, node_id = await _made(tmp_path)
    monkeypatch.setattr(
        silence,
        "find_silences",
        lambda path, start=0, end=None, min_silence=0.5, pad=0.12: [(4.0, 5.0)],
    )
    told = await tool.execute({"operation": "silences", "clip": node_id, "id": "v1"}, _ctx())
    assert told.success and "4.00-5.00" in told.output and "remove_silences" in told.output
    done = await tool.execute(
        {"operation": "silences", "clip": node_id, "id": "v1", "apply": True}, _ctx()
    )
    assert done.success, done.error
    scenes = store.get(node_id).spec["scenes"]
    assert [(s.get("in", 0), s["seconds"]) for s in scenes] == [(0, 4), (5, 15)]


# ------------------------------------------------------------------ look, export


def _jpeg() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (54, 96), (20, 120, 200)).save(buffer, format="JPEG")
    return buffer.getvalue()


async def test_look_hands_back_frames_and_sheets(
    tmp_path: Path, imports, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, _, node_id = await _made(tmp_path)
    monkeypatch.setattr(
        export,
        "still_frames",
        lambda node, node_dir, spec, times, width=720: [_jpeg() for _ in times],
    )
    few = await tool.execute({"operation": "look", "clip": node_id}, _ctx())
    assert few.success and 1 <= len(few.artifacts) <= 4 and "hook" in few.output
    many = await tool.execute(
        {"operation": "look", "clip": node_id, "times": [n * 0.5 for n in range(10)]}, _ctx()
    )
    assert many.success and len(many.artifacts) == 3 and "four to a picture" in many.output
    assert all(a["mime"] == "image/jpeg" for a in many.artifacts)


async def test_export_reports_the_file_or_the_job(
    tmp_path: Path, imports, cards, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool, _, node_id = await _made(tmp_path)
    states = {"j1": {"state": "done", "progress": 1.0, "file": "C:/clips/Reel-1080p-1.mp4"}}
    monkeypatch.setattr(export, "start_export", lambda node, node_dir, spec, preset, fps: "j1")
    monkeypatch.setattr(export, "export_status", lambda job: states.get(job))
    done = await tool.execute({"operation": "export", "clip": node_id}, _ctx())
    assert done.success and "Reel-1080p-1.mp4" in done.output
    states["j2"] = {"state": "running", "progress": 0.4}
    still = await tool.execute({"operation": "export", "clip": node_id, "job": "j2"}, _ctx())
    assert still.success and "40%" in still.output and "j2" in still.output
    states["j3"] = {"state": "failed", "error": "no browser"}
    failed = await tool.execute({"operation": "export", "clip": node_id, "job": "j3"}, _ctx())
    assert not failed.success and "no browser" in failed.error


async def test_revert_puts_the_last_version_back(tmp_path: Path, imports, cards) -> None:
    tool, store, node_id = await _made(tmp_path)
    await tool.execute(
        {"operation": "edit", "clip": node_id, "actions": [{"do": "format", "format": "square"}]},
        _ctx(),
    )
    result = await tool.execute({"operation": "revert", "clip": node_id}, _ctx())
    assert result.success and store.get(node_id).spec["format"] == "tall"


# ------------------------------------------------------------------ registration


def test_the_tool_is_router_reachable_registered_and_never_gated() -> None:
    from dodaios.brain.delegate_tool import DELEGATE_OVERLAPS
    from dodaios.brain.factory import ROUTER_TOOLS
    from dodaios.brain.tool_shortlist import DEFAULT_DIRECT
    from dodaios.society.capabilities import capability_id_for_tool

    assert "clip" in ROUTER_TOOLS
    assert ClipTool.name == "clip" and ClipTool.risk_tier == "monitor"
    assert "clip" in DEFAULT_DIRECT and "clip" not in DELEGATE_OVERLAPS
    assert capability_id_for_tool("clip") == "plugin:clip"


def test_the_entry_point_resolves_to_the_tool() -> None:
    import importlib

    declared = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    target = declared["project"]["entry-points"]["jarvis.tool"]["clip"]
    module, _, attr = target.partition(":")
    assert getattr(importlib.import_module(module), attr) is ClipTool


def test_the_node_tool_sends_videos_here() -> None:
    from dodaios.plugins.tool.node import TYPE_LINES, NodeTool

    assert "clip tool" in TYPE_LINES["motion"] and "clip tool" in NodeTool.description
