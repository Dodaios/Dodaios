"""The relauncher must NOT fossilize the ``JARVIS__*`` env config layer.

Live case (2026-07-17): every restarted app inherited the ``JARVIS__TTS__*``
values captured when the FIRST tray process started. A voice fix that updated
all pinned layers, including config-soll.json, kept being overridden  # i18n-allow: filename
by the stale inherited copy on
every ``restart-app`` — the replaced TTS voice resurrected after each restart.

``fresh_user_env`` re-reads the persisted ``JARVIS__*`` overrides (Windows:
HKCU Environment) for the NEW launcher; ``main`` passes that environment to
the spawn. On hosts with no persisted user env (POSIX) the inherited env is
already the freshest source and stays untouched.
"""

from __future__ import annotations

from types import SimpleNamespace

from jarvis.ui import relauncher


def test_fresh_env_replaces_stale_jarvis_overrides():
    base = {
        "PATH": r"C:\bin",
        "JARVIS__TTS__VOICE_DE": "Kore",  # fossilized in the dying process
        "JARVIS__TTS__VOICE_EN": "Kore",
    }
    persisted = {
        "JARVIS__TTS__VOICE_DE": "Charon",  # what the user's env says NOW
        "JARVIS__TTS__VOICE_EN": "Charon",
    }
    env = relauncher.fresh_user_env(base, _read_persisted=lambda: persisted)
    assert env["JARVIS__TTS__VOICE_DE"] == "Charon"
    assert env["JARVIS__TTS__VOICE_EN"] == "Charon"
    assert env["PATH"] == r"C:\bin"  # non-JARVIS keys stay inherited


def test_fresh_env_drops_jarvis_keys_deleted_from_the_persisted_env():
    base = {"JARVIS__TTS__SEED": "7", "HOME": "/home/u"}
    env = relauncher.fresh_user_env(base, _read_persisted=dict)
    assert "JARVIS__TTS__SEED" not in env
    assert env["HOME"] == "/home/u"


def test_fresh_env_is_a_no_op_without_a_persisted_source():
    base = {"JARVIS__TTS__VOICE_DE": "Kore", "PATH": "/bin"}
    env = relauncher.fresh_user_env(base, _read_persisted=lambda: None)
    assert env == base  # POSIX / unreadable registry → inherited env unchanged


def test_fresh_env_drops_the_one_process_branding_loop_guard():
    base = {
        "PATH": r"C:\bin",
        "jarvis_branded_launch": "1",
    }

    env = relauncher.fresh_user_env(base, _read_persisted=lambda: None)

    assert env == {"PATH": r"C:\bin"}


def test_fresh_env_key_matching_is_case_insensitive():
    base = {"jarvis__tts__voice_de": "Kore"}
    persisted = {"JARVIS__TTS__VOICE_DE": "Charon"}
    env = relauncher.fresh_user_env(base, _read_persisted=lambda: persisted)
    assert env.get("JARVIS__TTS__VOICE_DE") == "Charon"
    assert "jarvis__tts__voice_de" not in env


def test_main_spawns_the_new_launcher_with_the_fresh_env(monkeypatch):
    fresh = {"JARVIS__TTS__VOICE_DE": "Charon", "PATH": "/bin"}
    monkeypatch.setattr(relauncher, "fresh_user_env", lambda *a, **k: dict(fresh))
    spawned: list[dict] = []

    def fake_spawn(cmd, **kwargs):
        spawned.append({"cmd": cmd, "kwargs": kwargs})
        return SimpleNamespace(pid=999)

    rc = relauncher.main(
        ["4242", "repo"],
        _wait=lambda pid, **_kw: True,
        _spawn=fake_spawn,
        _sleep=lambda _s: None,
        _alive=lambda _p: True,
        _finalize_update=lambda _cwd: True,
        _serving=lambda: False,
    )
    assert rc == 0
    env = spawned[0]["kwargs"]["env"]
    assert env["JARVIS__TTS__VOICE_DE"] == "Charon"
    assert env["PATH"] == "/bin"


def test_fresh_env_carries_an_override_persisted_under_the_new_prefix():
    # This process moved its own DODAIOS__* copy to the JARVIS__ spelling when
    # it started, so the inherited environment holds the old name only. The
    # registry is the fresher source and must reach the new process, where the
    # same move happens again.
    from jarvis.core.env_prefix import adopt_environment

    base = {"JARVIS__TTS__VOICE_DE": "Kore", "JARVIS__TTS__SEED": "7", "PATH": r"C:\bin"}
    persisted = {"DODAIOS__TTS__VOICE_DE": "Charon", "JARVIS__TTS__SEED": "9"}

    env = relauncher.fresh_user_env(base, _read_persisted=lambda: persisted)
    assert env["DODAIOS__TTS__VOICE_DE"] == "Charon"
    assert "JARVIS__TTS__VOICE_DE" not in env  # the stale inherited value is gone

    assert adopt_environment(env) == ()  # what the new process does on import
    assert env == {
        "JARVIS__TTS__VOICE_DE": "Charon",
        "JARVIS__TTS__SEED": "9",
        "PATH": r"C:\bin",
    }


def test_a_persisted_new_prefix_override_wins_over_its_persisted_old_spelling():
    from jarvis.core.env_prefix import adopt_environment

    persisted = {"JARVIS__BRAIN__PRIMARY": "gemini", "DODAIOS__BRAIN__PRIMARY": "openrouter"}

    env = relauncher.fresh_user_env({}, _read_persisted=lambda: persisted)

    assert adopt_environment(env) == ("DODAIOS__BRAIN__PRIMARY",)
    assert env == {"JARVIS__BRAIN__PRIMARY": "openrouter"}


def test_an_override_deleted_from_the_persisted_env_does_not_survive_the_restart():
    # Started with DODAIOS__TTS__SEED=7, which became JARVIS__TTS__SEED; the
    # person has since removed it from the persisted environment.
    from jarvis.core.env_prefix import adopt_environment

    base = {"DODAIOS__TTS__SEED": "7"}
    adopt_environment(base)

    env = relauncher.fresh_user_env(base, _read_persisted=dict)

    assert env == {}


def test_the_registry_reader_matches_both_prefixes():
    # The reader itself only runs on Windows against the real registry; this
    # pins the prefixes it filters on.
    import inspect

    assert relauncher._CONFIG_ENV_PREFIXES == ("DODAIOS__", "JARVIS__")
    reader = inspect.getsource(relauncher._read_windows_user_jarvis_env)
    assert "name.upper().startswith(_CONFIG_ENV_PREFIXES)" in reader
