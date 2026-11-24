"""In-process E2E probe for the telephony call bridge.

Drives a synthetic Twilio call through ``PhoneCall`` (the same class the media
socket handler uses) against a fake realtime session that answers every caller
frame, and prints what reached the session, what went back to Twilio and how
the call ended. No real Twilio account, no public tunnel, no microphone, no
provider key.

Usage:
    python scripts/probe_telephony_e2e.py
"""

from __future__ import annotations

import asyncio
import base64
import math
import struct
import sys
from pathlib import Path
from typing import Any

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001, S110 - console encoding is best-effort
    pass

# Make `tests` importable for the fake session when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dodaios.telephony.audio import TWILIO_SAMPLE_RATE, pcm16_to_ulaw  # noqa: E402
from dodaios.telephony.call import PhoneCall  # noqa: E402


def _tone(rate: int, ms: int, amp: int = 8000, freq: int = 300) -> bytes:
    n = rate * ms // 1000
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
    )


async def _probe() -> int:
    from tests.fakes.fake_phone_session import FakePhoneSession

    sent: list[dict[str, Any]] = []
    sessions: list[FakePhoneSession] = []

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def hang_up() -> None:
        print("call: hung up by the bridge")

    def build(*, send_binary: Any, send_json: Any, call_brief: str) -> FakePhoneSession:
        session = FakePhoneSession(
            send_binary=send_binary, send_json=send_json, call_brief=call_brief
        )
        sessions.append(session)
        return session

    call = PhoneCall(
        call_sid="CAPROBE",
        stream_sid="MZPROBE",
        send=send,
        hang_up=hang_up,
        build_session=build,
        language_code="en-US",
        greeting="Hello, this is the probe.",
        max_call_seconds=0,
    )
    if not await call.start():
        print("FAIL: no session could be built")
        return 1
    for _ in range(10):
        await asyncio.sleep(0)
    session = sessions[0]
    for _ in range(10):
        payload = base64.b64encode(pcm16_to_ulaw(_tone(TWILIO_SAMPLE_RATE, 20))).decode()
        await call.handle_media(payload)
    await session.answer(_tone(24_000, 400))
    await call.end(reason="probe_done")

    media = [m for m in sent if m.get("event") == "media"]
    ulaw_bytes = sum(len(base64.b64decode(m["media"]["payload"])) for m in media)
    print(f"opening line : {session.spoken}")
    print(f"frames in    : {len(session.audio_in)} (8 kHz PCM16)")
    print(f"media out    : {len(media)} chunk(s), {ulaw_bytes} mu-law bytes")
    print(f"call         : status={call.status} reason={call.end_reason}")
    ok = bool(session.audio_in) and ulaw_bytes > 0 and session.ended_with is not None
    print("OK" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    return asyncio.run(_probe())


if __name__ == "__main__":
    raise SystemExit(main())
