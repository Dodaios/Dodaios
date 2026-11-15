"""Pictures and voice messages from the owner's Telegram chat.

Before 2026-11-15 the channel read only ``message.text``: a voice message (no
text) and a photo without a caption arrived as empty messages and were
dropped, so the bot never answered a voice message and never saw a photo, and
no picture reached the app's chat.
"""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from dodaios.channels.base import ChannelMedia, ChannelMessage
from dodaios.channels.chat_bridge import ChannelChatBridge
from dodaios.channels.telegram import TelegramChannel
from dodaios.core.bus import EventBus
from dodaios.core.config import TelegramConfig

# The owner's words in the tests are German, as in the bug report.
_BRIEFING = "Erstell mir bitte ein Briefing für die nächsten zwei Wochen."  # i18n-allow
_FREEZE = "Kann er das einfrieren?"  # i18n-allow
_YES_IT_WORKS = "Ja, das geht."  # i18n-allow
_YES = "Ja."  # i18n-allow

# ---------------------------------------------------------------- channel


class _File:
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def download_as_bytearray(self) -> bytearray:
        return bytearray(self.data)


class _Downloadable(SimpleNamespace):
    async def get_file(self) -> _File:
        return _File(self.payload)


def _update(
    *,
    text: str | None = None,
    caption: str | None = None,
    photo: bytes | None = None,
    voice: bytes | None = None,
    album: str | None = None,
    message_id: int = 1,
    language_code: str = "de",
) -> Any:
    user = SimpleNamespace(id=100, username="owner", full_name="Owner", language_code=language_code)
    chat = SimpleNamespace(id=100, type="private")
    message = SimpleNamespace(
        message_id=message_id,
        text=text,
        caption=caption,
        chat=chat,
        from_user=user,
        photo=(
            (
                _Downloadable(payload=b"small", file_size=5),
                _Downloadable(payload=photo, file_size=len(photo)),
            )
            if photo is not None else ()
        ),
        voice=(
            _Downloadable(payload=voice, file_size=len(voice), mime_type="audio/ogg")
            if voice is not None else None
        ),
        document=None,
        audio=None,
        media_group_id=album,
    )
    return SimpleNamespace(message=message)


def _channel() -> TelegramChannel:
    cfg = TelegramConfig(enabled=True, allowed_user_ids=[100])
    ch = TelegramChannel(bus=EventBus(), config=cfg)
    ch._app = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()))  # noqa: SLF001
    return ch


async def _next(ch: TelegramChannel) -> ChannelMessage:
    return await asyncio.wait_for(ch._inbox.get(), timeout=1.0)  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_voice_message_reaches_the_inbox_with_its_audio() -> None:
    ch = _channel()
    await ch._on_telegram_msg(_update(voice=b"OggS-audio"), None)  # noqa: SLF001
    msg = await _next(ch)
    assert msg.kind == "voice"
    assert msg.content == ""
    assert [(m.kind, m.data) for m in msg.media] == [("voice", b"OggS-audio")]
    assert msg.metadata["telegram_language"] == "de"
    assert ch._inflight.get(msg.trace_id) == 100  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_photo_with_a_caption_goes_at_once_with_the_largest_size() -> None:
    ch = _channel()
    await ch._on_telegram_msg(  # noqa: SLF001
        _update(caption="Can he freeze this steak?", photo=b"\xff\xd8big-jpeg"), None
    )
    msg = await _next(ch)
    assert msg.content == "Can he freeze this steak?"
    assert [(m.kind, m.data, m.mime) for m in msg.media] == [
        ("image", b"\xff\xd8big-jpeg", "image/jpeg")
    ]


@pytest.mark.asyncio
async def test_a_photo_then_the_question_arrive_as_one_message() -> None:
    ch = _channel()
    await ch._on_telegram_msg(_update(photo=b"\xff\xd8steak", message_id=1), None)  # noqa: SLF001
    assert ch._inbox.empty()  # noqa: SLF001 - the picture waits for its words
    await ch._on_telegram_msg(  # noqa: SLF001
        _update(text="Can my chef freeze this steak?", message_id=2), None
    )
    msg = await _next(ch)
    assert msg.content == "Can my chef freeze this steak?"
    assert [m.data for m in msg.media] == [b"\xff\xd8steak"]
    assert ch._inbox.empty()  # noqa: SLF001
    assert not ch._held  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_photo_and_then_a_voice_message_arrive_together() -> None:
    ch = _channel()
    await ch._on_telegram_msg(_update(photo=b"\xff\xd8steak", message_id=1), None)  # noqa: SLF001
    await ch._on_telegram_msg(_update(voice=b"OggS", message_id=2), None)  # noqa: SLF001
    msg = await _next(ch)
    assert msg.kind == "voice"
    assert [m.kind for m in msg.media] == ["image", "voice"]


@pytest.mark.asyncio
async def test_a_photo_alone_still_goes_when_no_words_follow() -> None:
    ch = _channel()
    ch.picture_wait_s = 0.05
    await ch._on_telegram_msg(_update(photo=b"\xff\xd8steak"), None)  # noqa: SLF001
    msg = await _next(ch)
    assert msg.content == ""
    assert [m.kind for m in msg.media] == ["image"]
    assert ch._inflight.get(msg.trace_id) == 100  # noqa: SLF001


@pytest.mark.asyncio
async def test_the_pictures_of_an_album_are_one_message() -> None:
    ch = _channel()
    ch.album_wait_s = 0.05
    await ch._on_telegram_msg(  # noqa: SLF001
        _update(caption="Which one is fresher?", photo=b"one", album="g1", message_id=1), None
    )
    await ch._on_telegram_msg(  # noqa: SLF001
        _update(photo=b"two", album="g1", message_id=2), None
    )
    msg = await _next(ch)
    assert msg.content == "Which one is fresher?"
    assert [m.data for m in msg.media] == [b"one", b"two"]


@pytest.mark.asyncio
async def test_a_message_with_nothing_readable_is_dropped() -> None:
    ch = _channel()
    await ch._on_telegram_msg(_update(), None)  # noqa: SLF001 - a sticker, say
    assert ch._inbox.empty()  # noqa: SLF001


@pytest.mark.asyncio
async def test_stop_drops_held_pictures() -> None:
    ch = _channel()
    await ch._on_telegram_msg(_update(photo=b"x"), None)  # noqa: SLF001
    ch._started = True  # noqa: SLF001
    ch._app = None  # noqa: SLF001
    await ch.stop()
    assert not ch._held  # noqa: SLF001


@pytest.mark.asyncio
async def test_a_written_reply_keeps_its_digits() -> None:
    ch = _channel()
    await ch._send_text(100, "Bis 26. November musst du zustimmen.", language="en")  # noqa: SLF001
    sent = ch._app.bot.send_message.await_args.kwargs["text"]  # noqa: SLF001
    assert "26. November" in sent
    assert "twenty" not in sent


# ----------------------------------------------------------------- bridge


class _ReplyChannel:
    name = "telegram"

    def __init__(self) -> None:
        self.queue: asyncio.Queue[ChannelMessage] = asyncio.Queue()
        self.sent: list[ChannelMessage] = []
        self.got = asyncio.Event()

    async def send_message(self, msg: ChannelMessage) -> None:
        self.sent.append(msg)
        self.got.set()

    async def messages(self):  # noqa: ANN201
        while True:
            yield await self.queue.get()


class _Manager:
    def __init__(self, channel: _ReplyChannel) -> None:
        self.channel = channel

    def started(self) -> list[str]:
        return ["telegram"]

    def get(self, name: str) -> _ReplyChannel:
        return self.channel


def _owner_msg(content: str, *media: ChannelMedia, language: str = "de") -> ChannelMessage:
    return ChannelMessage(
        session_id=uuid4(),
        kind="voice" if any(m.kind == "voice" for m in media) else "text",
        content=content,
        metadata={"telegram_chat_id": 100, "friend_id": None, "telegram_language": language},
        media=media,
    )


async def _run(monkeypatch, msg: ChannelMessage, *, transcript: Any = "", asked=None):
    from dodaios.agent_chat import lead
    from dodaios.speech import voice_note

    async def fake_transcribe(data: bytes, **_kw: Any) -> str:
        if isinstance(transcript, BaseException):
            raise transcript
        return transcript

    async def fake_answer(svc, text, *, source, report=None, on_card=None, pictures=(), **_kw):
        asked.append((text, list(pictures)))
        return _YES_IT_WORKS

    monkeypatch.setattr(voice_note, "transcribe_voice_note", fake_transcribe)
    monkeypatch.setattr(lead, "answer_in_lead", fake_answer)
    monkeypatch.setattr(lead, "lead_session", lambda *_a, **_k: None)
    channel = _ReplyChannel()
    bridge = ChannelChatBridge(
        bus=EventBus(), manager=_Manager(channel), get_chat_service=lambda: object(),  # type: ignore[arg-type]
        phone_allows=lambda _kind: True,
    )
    bridge.start()
    await channel.queue.put(msg)
    await asyncio.wait_for(channel.got.wait(), timeout=2.0)
    await bridge.stop()
    return channel


@pytest.mark.asyncio
async def test_a_voice_message_is_read_and_answered_like_typed_words(monkeypatch) -> None:
    asked: list[Any] = []
    channel = await _run(
        monkeypatch,
        _owner_msg("", ChannelMedia(kind="voice", name="voice.ogg", data=b"OggS")),
        transcript=_BRIEFING,
        asked=asked,
    )
    assert asked == [(_BRIEFING, [])]
    assert channel.sent[0].content == _YES_IT_WORKS


@pytest.mark.asyncio
async def test_a_photo_travels_to_the_lead_conversation(monkeypatch) -> None:
    asked: list[Any] = []
    await _run(
        monkeypatch,
        _owner_msg(
            _FREEZE,
            ChannelMedia(
                kind="image", name="telegram-photo-1.jpg", data=b"\xff\xd8", mime="image/jpeg"
            ),
        ),
        asked=asked,
    )
    assert asked == [(_FREEZE, [("telegram-photo-1.jpg", b"\xff\xd8")])]


@pytest.mark.asyncio
async def test_a_photo_without_words_still_reaches_the_lead(monkeypatch) -> None:
    asked: list[Any] = []
    await _run(
        monkeypatch,
        _owner_msg("", ChannelMedia(kind="image", name="p.jpg", data=b"\xff\xd8")),
        asked=asked,
    )
    assert asked == [("", [("p.jpg", b"\xff\xd8")])]


@pytest.mark.asyncio
async def test_without_speech_recognition_the_owner_is_told_in_their_language(monkeypatch) -> None:
    from dodaios.speech.voice_note import VoiceNoteUnavailable

    asked: list[Any] = []
    channel = await _run(
        monkeypatch,
        _owner_msg("", ChannelMedia(kind="voice", name="voice.ogg", data=b"OggS")),
        transcript=VoiceNoteUnavailable("off"),
        asked=asked,
    )
    assert asked == []
    assert "Spracherkennung" in channel.sent[0].content  # i18n-allow


@pytest.mark.asyncio
async def test_an_unreadable_voice_message_gets_one_honest_line(monkeypatch) -> None:
    asked: list[Any] = []
    channel = await _run(
        monkeypatch,
        _owner_msg("", ChannelMedia(kind="voice", name="voice.ogg", data=b"OggS"), language="en"),
        transcript="",
        asked=asked,
    )
    assert asked == []
    assert "couldn't understand that voice message" in channel.sent[0].content


# ------------------------------------------------------------- voice note


def _ogg_opus(seconds: float = 1.0) -> bytes:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    buf = io.BytesIO()
    try:
        with av.open(buf, "w", format="ogg") as out:
            stream = out.add_stream("libopus", rate=48_000)
            stream.layout = "mono"
            rate = 48_000
            t = np.arange(int(seconds * rate)) / rate
            samples = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(1, -1)
            step = 960
            for start in range(0, samples.shape[1], step):
                chunk = np.ascontiguousarray(samples[:, start:start + step])
                frame = av.AudioFrame.from_ndarray(chunk, format="flt", layout="mono")
                frame.sample_rate = rate
                frame.pts = start
                for packet in stream.encode(frame):
                    out.mux(packet)
            for packet in stream.encode(None):
                out.mux(packet)
    except (av.error.FFmpegError, ValueError) as exc:  # pragma: no cover - a build without libopus
        pytest.skip(f"no Opus encoder: {exc}")
    return buf.getvalue()


def test_an_ogg_opus_voice_note_decodes_to_16khz_mono_pcm() -> None:
    from dodaios.speech.voice_note import decode_to_pcm16k

    pcm = decode_to_pcm16k(_ogg_opus(1.0))
    seconds = len(pcm) / 2 / 16_000
    assert 0.9 < seconds < 1.1


def test_a_long_note_is_cut() -> None:
    from dodaios.speech.voice_note import decode_to_pcm16k

    pcm = decode_to_pcm16k(_ogg_opus(2.0), max_seconds=1)
    assert len(pcm) == 16_000 * 2


def test_garbage_is_a_voice_note_error() -> None:
    from dodaios.speech.voice_note import VoiceNoteError, decode_to_pcm16k

    with pytest.raises(VoiceNoteError):
        decode_to_pcm16k(b"not audio at all")


@pytest.mark.asyncio
async def test_transcribe_reads_the_note_with_the_recognizer() -> None:
    from dodaios.speech.voice_note import transcribe_voice_note

    heard: list[int] = []

    class _Stt:
        async def transcribe_pcm(self, pcm: bytes, language: str | None = None) -> Any:
            heard.append(len(pcm))
            return SimpleNamespace(text="  Hallo Welt  ")  # i18n-allow

    assert await transcribe_voice_note(_ogg_opus(1.0), stt=_Stt()) == "Hallo Welt"  # i18n-allow
    assert heard and heard[0] > 16_000


@pytest.mark.asyncio
async def test_transcribe_without_a_recognizer_is_unavailable(monkeypatch) -> None:
    from dodaios.speech import voice_note

    monkeypatch.setattr(voice_note, "_recognizer", lambda: None)
    with pytest.raises(voice_note.VoiceNoteUnavailable):
        await voice_note.transcribe_voice_note(b"OggS")


# ------------------------------------------------------------ lead attach


@pytest.mark.asyncio
async def test_answer_in_lead_attaches_the_pictures_to_the_message(tmp_path, monkeypatch) -> None:
    from dodaios.agent_chat import lead
    from dodaios.agentic_ide import drop_analysis

    async def fake_analyze(items, **_kw):
        return [
            drop_analysis.DropAnalysis(name=item.name, kind="image", reference=ref)
            for item, ref in items
        ]

    monkeypatch.setattr(drop_analysis, "analyze", fake_analyze)
    session = SimpleNamespace(session_id="lead-1", cwd=str(tmp_path))
    monkeypatch.setattr(lead, "lead_session", lambda *_a, **_k: session)
    sent: list[Any] = []

    async def fake_send(svc, sid, text, attachments=None, **_kw):
        sent.append((sid, text, attachments))
        said = {"turn_id": "t1", "text": _YES}
        await svc.events.put({"kind": "assistant_text", "payload": said})
        done = {"turn_id": "t1", "status": "done"}
        await svc.events.put({"kind": "turn_finished", "payload": done})
        return "t1", ""

    monkeypatch.setattr("dodaios.agent_chat.send_queue.send_or_queue", fake_send)

    class _Svc:
        events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def subscribe(self, _sid: str) -> asyncio.Queue[dict[str, Any]]:
            return self.events

        def unsubscribe(self, _sid: str, _q: Any) -> None: ...

    answer = await lead.answer_in_lead(
        _Svc(), "", source="telegram", timeout_s=5,
        pictures=[("telegram-photo-1.jpg", b"\xff\xd8\xff\xe0steak")],
    )
    assert answer == _YES
    (sid, text, attachments), = sent
    assert sid == "lead-1" and text == ""
    assert [a["name"] for a in attachments] == ["telegram-photo-1.jpg"]
    stored = list((tmp_path / ".jarvis" / "drops").glob("*telegram-photo-1.jpg"))
    assert stored and stored[0].read_bytes() == b"\xff\xd8\xff\xe0steak"
