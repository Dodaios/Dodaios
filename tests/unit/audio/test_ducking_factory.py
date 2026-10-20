"""make_audio_ducker picks the platform backend, NullDucker otherwise."""
from __future__ import annotations

from types import SimpleNamespace

from dodaios.audio.ducking.factory import make_audio_ducker
from dodaios.audio.ducking.macos import MacOSScriptDucker
from dodaios.audio.ducking.null import NullDucker


def test_factory_returns_null_when_pycaw_absent(monkeypatch):
    monkeypatch.setattr("dodaios.audio.ducking.factory.sys.platform", "win32")
    monkeypatch.setattr(
        "dodaios.audio.ducking.factory._pycaw_available", lambda: False
    )
    assert isinstance(make_audio_ducker(), NullDucker)


def test_factory_returns_null_off_windows(monkeypatch):
    monkeypatch.setattr("dodaios.audio.ducking.factory.sys.platform", "linux")
    assert isinstance(make_audio_ducker(), NullDucker)


def test_factory_returns_windows_backend_on_win32_with_pycaw(monkeypatch):
    from dodaios.audio.ducking.windows import WindowsPycawDucker

    monkeypatch.setattr("dodaios.audio.ducking.factory.sys.platform", "win32")
    monkeypatch.setattr(
        "dodaios.audio.ducking.factory._pycaw_available", lambda: True
    )
    assert isinstance(make_audio_ducker(), WindowsPycawDucker)


def test_factory_returns_macos_backend_on_darwin_with_osascript(monkeypatch):
    monkeypatch.setattr("dodaios.audio.ducking.factory.sys.platform", "darwin")
    monkeypatch.setattr(
        "dodaios.audio.ducking.factory._osascript_available", lambda: True
    )
    assert isinstance(make_audio_ducker(), MacOSScriptDucker)


def test_factory_returns_null_on_darwin_without_osascript(monkeypatch):
    monkeypatch.setattr("dodaios.audio.ducking.factory.sys.platform", "darwin")
    monkeypatch.setattr(
        "dodaios.audio.ducking.factory._osascript_available", lambda: False
    )
    assert isinstance(make_audio_ducker(), NullDucker)


def test_factory_threads_cfg_into_the_macos_backend(monkeypatch):
    monkeypatch.setattr("dodaios.audio.ducking.factory.sys.platform", "darwin")
    monkeypatch.setattr(
        "dodaios.audio.ducking.factory._osascript_available", lambda: True
    )
    cfg = SimpleNamespace(
        ducking=SimpleNamespace(duck_volume_percent=20, macos_master_fallback=True)
    )
    d = make_audio_ducker(cfg)
    assert isinstance(d, MacOSScriptDucker)
    assert d._duck == 20
    assert d._master_fallback is True


def test_factory_no_arg_call_still_works(monkeypatch):
    monkeypatch.setattr("dodaios.audio.ducking.factory.sys.platform", "darwin")
    monkeypatch.setattr(
        "dodaios.audio.ducking.factory._osascript_available", lambda: True
    )
    d = make_audio_ducker()  # source-compatible: cfg is optional
    assert isinstance(d, MacOSScriptDucker)
    assert d._duck == 0 and d._master_fallback is False


def test_null_ducker_is_noop():
    d = NullDucker()
    assert d.mute_others(own_pid=123, never=frozenset()) == []
    d.restore([1, 2, 3])  # must not raise
