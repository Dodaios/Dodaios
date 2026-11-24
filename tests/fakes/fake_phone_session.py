"""A scripted realtime voice session for the phone-call bridge (``dodaios.telephony.call``).

It has the surface a :class:`~dodaios.telephony.call.PhoneCall` uses on every
realtime session class: ``handle_control`` / ``handle_audio_frame`` / ``end`` /
``speak_line`` / ``failed``, and it talks back through the same
``send_binary`` / ``send_json`` callbacks a real session gets. A test plays
the provider's side with :meth:`answer` and :meth:`emit`.

No network, provider, key or audio device is involved.
"""

from __future__ import annotations

from typing import Any


class FakePhoneSession:
    """One realtime session as the phone bridge sees it; every input is recorded."""

    def __init__(
        self,
        *,
        send_binary: Any,
        send_json: Any,
        call_brief: str = "",
        output_sample_rate: int = 24_000,
        start_error: BaseException | None = None,
        lines_accepted_after: int = 0,
    ) -> None:
        self._send_binary = send_binary
        self._send_json = send_json
        self.call_brief = call_brief
        self.output_sample_rate = output_sample_rate
        self.start_error = start_error
        # How many speak_line offers are refused (model busy) before one is taken.
        self.lines_accepted_after = lines_accepted_after
        self.controls: list[dict[str, Any]] = []
        self.audio_in: list[bytes] = []
        self.line_offers: list[tuple[str, str]] = []
        self.spoken: list[tuple[str, str]] = []
        self.ended_with: str | None = None
        self.failed = False
        self.failure_detail = ""

    async def handle_control(self, message: dict[str, Any]) -> None:
        self.controls.append(message)
        if message.get("type") != "audio_start":
            return
        if self.start_error is not None:
            raise self.start_error
        await self._send_json(
            {
                "type": "audio_ready",
                "input_sample_rate": 16_000,
                "output_sample_rate": self.output_sample_rate,
            }
        )

    async def handle_audio_frame(self, pcm: bytes) -> None:
        self.audio_in.append(pcm)

    async def speak_line(self, text: str, *, kind: str = "announcement") -> bool:
        self.line_offers.append((kind, text))
        if len(self.line_offers) <= self.lines_accepted_after:
            return False
        self.spoken.append((kind, text))
        return True

    async def end(self, *, reason: str = "") -> None:
        if self.ended_with is not None:
            return
        self.ended_with = reason
        await self._send_json({"type": "audio_closed"})

    # -- the provider's side -------------------------------------------------

    async def answer(self, pcm: bytes) -> None:
        """The model speaks: PCM16 at ``output_sample_rate`` reaches the bridge."""
        await self._send_binary(pcm)

    async def emit(self, message: dict[str, Any]) -> None:
        """A status message the session sends its surface."""
        await self._send_json(message)


__all__ = ["FakePhoneSession"]
