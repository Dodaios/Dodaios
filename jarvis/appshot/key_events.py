"""Event-driven Windows AppShot shortcuts, including short single-key taps.

The shared polling backend is appropriate for held voice chords, but can miss
an entire tap between samples. Reuse the existing listener lifecycle and chord
matcher while keeping Windows character tokens stable across modifier changes.
"""

from __future__ import annotations

import logging
import sys

from jarvis.trigger.backends.pynput import (
    _GENERIC_MODIFIER_ALIASES,
    PynputBackend,
    _combo_is_down,
)

log = logging.getLogger(__name__)

_NUMPAD_TOKENS = {
    0x6A: "multiply_key", 0x6B: "add_key", 0x6D: "subtract_key",
    0x6E: "decimal_key", 0x6F: "divide_key",
}

# Virtual-key codes for modifier tokens pynput leaves in the held set when a
# key-up never arrives. A stuck Ctrl made the next plain letter look like
# Ctrl+letter, so the recording shortcut fired while typing.
_MODIFIER_VK = {
    "ctrl": 0x11, "control": 0x11, "ctrl_l": 0xA2, "ctrl_r": 0xA3,
    "shift": 0x10, "shift_l": 0xA0, "shift_r": 0xA1,
    "alt": 0x12, "alt_l": 0xA4, "alt_r": 0xA5, "alt_gr": 0xA5,
    "cmd": 0x5B, "cmd_l": 0x5B, "cmd_r": 0x5C,
    "win": 0x5B, "window": 0x5B, "super": 0x5B, "meta": 0x5B,
}

_user32 = None


def key_is_down(token: str, vk: int | None = None) -> bool | None:
    """Whether ``token`` is physically down. ``None`` when this host cannot tell."""
    code = vk if isinstance(vk, int) else _MODIFIER_VK.get(token)
    if code is None or sys.platform != "win32":
        return None
    global _user32
    try:
        if _user32 is None:
            import ctypes  # noqa: PLC0415

            _user32 = ctypes.WinDLL("user32", use_last_error=True)
            _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
            _user32.GetAsyncKeyState.restype = ctypes.c_short
        return bool(_user32.GetAsyncKeyState(code) & 0x8000)
    except Exception:  # noqa: BLE001 — a failed read must not wedge the listener
        log.debug("appshot: could not read key state", exc_info=True)
        return None


def _completes(tokens: frozenset[str], pressed: set[str]) -> bool:
    """Whether one of the newly pressed keys belongs to the chord."""
    return any(
        _GENERIC_MODIFIER_ALIASES.get(token, frozenset({token})) & pressed for token in tokens
    )


class AppshotKeyEvents(PynputBackend):
    """One keyboard hook; inherited stop() joins it before any re-registration."""

    def __init__(self) -> None:
        super().__init__()
        # The held set as the last reconcile saw it. Only a key that is new
        # against it can start a chord, so a shorter chord (area ``ctrl+b``)
        # never starts because a longer one (recording ``ctrl+shift+b``) lost
        # a key on the way up.
        self._seen: set[str] = set()
        self._token_vk: dict[str, int] = {}

    @property
    def ready(self) -> bool:
        return self._started and self._listener is not None

    def _remember(self, key: object, token: str) -> None:
        vk = getattr(key, "vk", None)
        if not isinstance(vk, int):
            vk = getattr(getattr(key, "value", None), "vk", None)
        if isinstance(vk, int):
            self._token_vk[token] = vk

    def _drop_stale(self, *, keep: str | None) -> None:
        """Forget keys the OS says are already up, without firing a toggle.

        The key this event is about is left alone: dropping it here would eat
        the press or release edge the caller is about to handle.
        """
        removed = False
        for token in list(self._held):
            if token == keep:
                continue
            if key_is_down(token, self._token_vk.get(token)) is False:
                self._held.discard(token)
                removed = True
        if not removed:
            return
        self._seen &= self._held
        for combo in self._combos:
            if combo["down"] and not _combo_is_down(combo["tokens"], self._held):
                combo["down"] = False

    def _on_press_key(self, key) -> None:
        token = self._token_for(key)
        if token is not None:
            self._remember(key, token)
            self._drop_stale(keep=token)
        super()._on_press_key(key)

    def _on_release_key(self, key) -> None:
        super()._on_release_key(key)
        self._drop_stale(keep=None)

    def stop(self) -> None:
        super().stop()
        self._seen.clear()

    def _reconcile(self) -> None:
        """Start a chord on the press that completes it; end it when a key lifts.

        The shared matcher starts every chord whose keys are down, whatever the
        last event was, so a shorter shortcut started the moment a longer one
        lost a key. Here only a newly pressed key starts a chord, and of the
        chords it completes the longest wins. A key that stays down serves the
        next chord too: Ctrl+X, then Ctrl+Y, without letting go of Ctrl.
        """
        if not self._permission_check():
            self._held.clear()
            self._seen.clear()
            for combo in self._combos:
                combo["down"] = False
            return
        pressed = self._held - self._seen
        self._seen = set(self._held)
        live = [(combo, _combo_is_down(combo["tokens"], self._held)) for combo in self._combos]
        for combo, is_down in live:
            if combo["down"] and not is_down:
                combo["down"] = False
                self._got_event = True
                if combo["on_release"] is not None:
                    combo["on_release"]()
        if not pressed:
            return
        longest = max((len(combo["tokens"]) for combo, is_down in live if is_down), default=0)
        for combo, is_down in live:
            if not is_down:
                continue
            if len(combo["tokens"]) < longest:
                combo["down"] = False  # The longer chord took over: no toggle.
                continue
            if combo["down"] or not _completes(combo["tokens"], pressed):
                continue
            combo["down"] = True
            self._got_event = True
            if combo["on_press"] is not None:
                combo["on_press"]()

    def _token_for(self, key) -> str | None:
        vk = getattr(key, "vk", None)
        if vk is None:
            vk = getattr(getattr(key, "value", None), "vk", None)
        if isinstance(vk, int):
            if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
                # Ctrl+C may report '\x03', and Shift changes a character's
                # case. The virtual letter key remains C on both edges.
                return chr(vk).lower()
            if 0x60 <= vk <= 0x69:
                return f"numpad_{vk - 0x60}"
            if vk in _NUMPAD_TOKENS:
                return _NUMPAD_TOKENS[vk]
        return super()._token_for(key)
