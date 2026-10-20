"""WindowsAutostart scheduled-task path — pure script builders + decision logic.

The Windows autostart was upgraded from a throttled ``shell:startup`` ``.lnk`` to
a **per-user logon scheduled task** (Task Scheduler is not subject to the Windows
11 startup-app throttle, so Jarvis starts within seconds of login instead of the
4-8 minutes the .lnk took on a machine with many startup programs).

Registering a task needs a one-time elevation (UAC); reading its state does not.
So:

  * the **script builders** are pure → CI-provable on any OS (here),
  * the **install/uninstall decision logic** is exercised with injected fakes
    (no real Task Scheduler, no real UAC), and
  * the real elevated ``Start-Process -Verb RunAs`` + ``.lnk`` I/O are live-only
    (Windows sign-off).

The ``.lnk`` remains the no-elevation **fallback** when the user declines UAC, so
autostart still works (just possibly delayed) — covered by ``test_windows_scripts``.
"""

from __future__ import annotations

import re

from dodaios.autostart.protocol import LaunchSpec
from dodaios.autostart.windows import (
    TASK_NAME,
    WindowsAutostart,
    _TaskInfo,
    build_query_task_script,
    build_register_task_script,
    build_unregister_task_script,
    parse_task_query,
)
from dodaios.core.branding import (
    LEGACY_WINDOWS_AUTOSTART_TASK_NAMES,
    LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES,
    LEGACY_WINDOWS_SHORTCUT_FILE_NAMES,
    WINDOWS_BRANDED_LAUNCHER_FILE_NAME,
)

_SPEC = LaunchSpec(
    program=r"C:\Python\pythonw.exe",
    args=("-m", "dodaios.ui.web.launcher"),
    working_dir=r"C:\Users\u\Personal Jarvis",
)
_MATCHING_INFO = _TaskInfo(
    execute=_SPEC.program,
    arguments="-m dodaios.ui.web.launcher",
    working_dir=_SPEC.working_dir,
)


# --------------------------------------------------------------------------- #
# Pure script builders                                                         #
# --------------------------------------------------------------------------- #


def test_register_script_has_action_trigger_principal() -> None:
    script = build_register_task_script(TASK_NAME, _SPEC, user_id=r"DOM\u")
    assert "Register-ScheduledTask" in script
    assert "New-ScheduledTaskAction" in script
    assert r"-Execute 'C:\Python\pythonw.exe'" in script
    assert "-m dodaios.ui.web.launcher" in script
    assert r"C:\Users\u\Personal Jarvis" in script
    assert "AtLogOn" in script
    assert TASK_NAME in script


def test_register_script_runs_nonelevated_as_the_login_user() -> None:
    # RunLevel Limited = the launched Jarvis is NOT elevated (mic access, AP-17),
    # and the principal is the *captured* login user (not whoever approves UAC).
    script = build_register_task_script(TASK_NAME, _SPEC, user_id=r"DOM\alice")
    assert "Limited" in script
    assert r"DOM\alice" in script


def test_register_script_bakes_logon_delay() -> None:
    script = build_register_task_script(TASK_NAME, _SPEC, user_id="u", delay_seconds=20)
    assert "PT20S" in script


def test_register_script_pins_normal_priority() -> None:
    # Task Scheduler's default (7) starts the whole tree BelowNormal — on a
    # paging cold boot that meant 15-30 s whole-app freezes (BUG-204 amplifier).
    script = build_register_task_script(TASK_NAME, _SPEC, user_id="u")
    assert "-Priority 5" in script


def test_unregister_script_is_idempotent() -> None:
    script = build_unregister_task_script(TASK_NAME)
    assert "Unregister-ScheduledTask" in script
    assert TASK_NAME in script
    assert "SilentlyContinue" in script  # absent task must not error


def test_query_script_emits_sentinel_lines() -> None:
    script = build_query_task_script(TASK_NAME)
    assert TASK_NAME in script
    assert script.count("Write-Output") >= 3


def test_register_script_escapes_apostrophes_in_paths() -> None:
    # An unescaped apostrophe closes the single-quoted PowerShell literal early,
    # so the whole script fails to parse. For a login like O'Brien — or a folder
    # named "Ruben's Jarvis" — task registration, task query and shortcut I/O
    # then all fail and autostart silently never works on that machine.
    spec = LaunchSpec(
        program=r"C:\Users\O'Brien\.venv\Scripts\pythonw.exe",
        args=("-m", "dodaios.ui.web.launcher"),
        working_dir=r"C:\Users\O'Brien\Ruben's Jarvis",
    )
    script = build_register_task_script(TASK_NAME, spec, user_id=r"DOM\O'Brien")
    assert r"-Execute 'C:\Users\O''Brien\.venv\Scripts\pythonw.exe'" in script
    assert r"Ruben''s Jarvis" in script
    assert r"-UserId 'DOM\O''Brien'" in script
    # Every line closes each literal it opens.
    assert all(line.count("'") % 2 == 0 for line in script.splitlines())


def test_query_and_unregister_scripts_escape_apostrophes() -> None:
    weird = "Personal Jarvis' Autostart"
    for script in (
        build_query_task_script(weird),
        build_unregister_task_script(weird),
    ):
        assert "Personal Jarvis'' Autostart" in script
        assert all(line.count("'") % 2 == 0 for line in script.splitlines())


def test_parse_task_query_roundtrips_register_fields() -> None:
    out = parse_task_query(build_fake_query_output())
    assert out is not None
    assert out.execute == r"C:\Python\pythonw.exe"
    assert out.arguments == "-m dodaios.ui.web.launcher"
    assert out.working_dir == r"C:\Users\u\Personal Jarvis"
    assert out.enabled is True


def test_parse_task_query_returns_none_when_absent() -> None:
    assert parse_task_query("") is None


def test_parse_task_query_survives_non_ascii_paths() -> None:
    """A profile whose name is not plain ASCII read back as drift forever.

    PowerShell 5.1 writes a redirected stdout with the OEM code page while
    Python decoded it with the ANSI one, so every accented path came back
    corrupted and never compared equal to the live spec. U+00FC is the sharpest
    case: cp850 encodes it as 0x81, which cp1252 cannot decode at all. The
    read-back is base64-of-UTF-8 now, which no code page can corrupt.
    """
    program = "C:\\Users\\test-\u00fc\u00e9\\pythonw.exe"
    workdir = "C:\\projects\\caf\u00e9-\u00fc"
    out = parse_task_query(
        build_fake_query_output(execute=program, working_dir=workdir)
    )
    assert out is not None
    assert out.execute == program
    assert out.working_dir == workdir


def test_parse_task_query_reports_a_disabled_task() -> None:
    out = parse_task_query(build_fake_query_output(state="Disabled"))
    assert out is not None
    assert out.enabled is False


def test_parse_task_query_treats_a_missing_state_as_enabled() -> None:
    """Only an explicit "Disabled" may switch autostart off — a truncated
    read-back must never raise a false alarm about a task that does fire."""
    out = parse_task_query(build_fake_query_output(state=None))
    assert out is not None
    assert out.enabled is True


def build_fake_query_output(
    *,
    execute: str = r"C:\Python\pythonw.exe",
    arguments: str = "-m dodaios.ui.web.launcher",
    working_dir: str = r"C:\Users\u\Personal Jarvis",
    state: str | None = "Ready",
) -> str:
    import base64

    from dodaios.autostart.windows import _QUERY_SENTINEL

    fields = [execute, arguments, working_dir]
    if state is not None:
        fields.append(state)
    return "\n".join(
        _QUERY_SENTINEL + base64.b64encode(f.encode("utf-8")).decode("ascii")
        for f in fields
    )


# --------------------------------------------------------------------------- #
# Decision logic (injected fakes — no real Task Scheduler / UAC / .lnk)        #
# --------------------------------------------------------------------------- #


_LEGACY_TASK_NAME = LEGACY_WINDOWS_AUTOSTART_TASK_NAMES[0]


def _mk(
    *,
    task_info: _TaskInfo | None = None,
    elevate_ok: bool = True,
    shortcut_present: bool = False,
    shortcut_matches: bool = False,
) -> tuple[WindowsAutostart, list[str]]:
    mgr, calls, _tasks, _probed = _scheduler(
        task_info=task_info,
        elevate_ok=elevate_ok,
        shortcut_present=shortcut_present,
        shortcut_matches=shortcut_matches,
    )
    return mgr, calls


def _scheduler(
    *,
    task_info: _TaskInfo | None = None,
    legacy_task_info: _TaskInfo | None = None,
    elevate_ok: bool = True,
    shortcut_present: bool = False,
    shortcut_matches: bool = False,
) -> tuple[WindowsAutostart, list[str], dict[str, _TaskInfo], list[str]]:
    """A manager over an in-memory Task Scheduler keyed by task name.

    Returns the manager, its side effects in order, the registered tasks by
    name, and every name the manager asked the scheduler about.
    """
    calls: list[str] = []
    tasks: dict[str, _TaskInfo] = {}
    if task_info is not None:
        tasks[TASK_NAME] = task_info
    if legacy_task_info is not None:
        tasks[_LEGACY_TASK_NAME] = legacy_task_info
    probed: list[str] = []
    state = {"shortcut": shortcut_present}

    def task_probe(name: str) -> _TaskInfo | None:
        probed.append(name)
        return tasks.get(name)

    def run_elevated(script: str) -> bool:
        registered = re.findall(r"^  Register-ScheduledTask -TaskName '([^']+)'", script, re.M)
        unregistered = re.findall(
            r"^  Unregister-ScheduledTask -TaskName '([^']+)'", script, re.M
        )
        if registered:
            calls.append("elevate_register")
        elif unregistered:
            calls.append("elevate_unregister")
        calls.extend(f"unregister:{name}" for name in unregistered)
        if elevate_ok:
            for name in registered:
                tasks[name] = _MATCHING_INFO
            for name in unregistered:
                tasks.pop(name, None)
        return elevate_ok

    def sc_present() -> bool:
        return bool(state["shortcut"])

    def sc_matches(spec: LaunchSpec) -> bool:  # noqa: ARG001
        return shortcut_matches

    def write_sc(spec: LaunchSpec) -> None:  # noqa: ARG001
        calls.append("write_shortcut")
        state["shortcut"] = True

    def remove_sc() -> None:
        calls.append("remove_shortcut")
        state["shortcut"] = False

    mgr = WindowsAutostart(
        task_probe=task_probe,
        run_elevated=run_elevated,
        shortcut_present=sc_present,
        shortcut_matches=sc_matches,
        write_shortcut=write_sc,
        remove_shortcut=remove_sc,
    )
    return mgr, calls, tasks, probed


def test_status_reports_scheduled_task_when_present_and_matching() -> None:
    mgr, _ = _mk(task_info=_MATCHING_INFO)
    st = mgr.status(_SPEC)
    assert st.installed is True
    assert st.matches_spec is True
    assert "scheduled task" in st.detail.lower()


def test_status_reports_drift_when_task_points_elsewhere() -> None:
    other = _TaskInfo(
        execute=r"C:\Old\pythonw.exe",
        arguments="-m dodaios.ui.web.launcher",
        working_dir=r"C:\Old",
    )
    mgr, _ = _mk(task_info=other)
    st = mgr.status(_SPEC)
    assert st.installed is True
    assert st.matches_spec is False


def test_status_falls_back_to_shortcut_when_no_task() -> None:
    mgr, _ = _mk(task_info=None, shortcut_present=True, shortcut_matches=True)
    st = mgr.status(_SPEC)
    assert st.installed is True
    assert st.matches_spec is True
    assert "shortcut" in st.detail.lower()


def test_status_not_installed_when_neither_present() -> None:
    mgr, _ = _mk(task_info=None, shortcut_present=False)
    st = mgr.status(_SPEC)
    assert st.installed is False


def test_install_interactive_registers_task_and_drops_shortcut() -> None:
    # User-initiated enable: prompt for UAC, register the task, and remove the
    # throttled fallback shortcut so Jarvis never double-starts.
    mgr, calls = _mk(task_info=None, elevate_ok=True, shortcut_present=True)
    st = mgr.install(_SPEC, interactive=True)
    assert "elevate_register" in calls
    assert "remove_shortcut" in calls
    assert "write_shortcut" not in calls
    assert st.matches_spec is True


def test_install_interactive_falls_back_to_shortcut_when_uac_declined() -> None:
    # User clicks "No" on UAC → no task, but autostart must still work → .lnk.
    mgr, calls = _mk(task_info=None, elevate_ok=False, shortcut_present=False)
    mgr.install(_SPEC, interactive=True)
    assert "elevate_register" in calls
    assert "write_shortcut" in calls


def test_install_noninteractive_writes_shortcut_without_prompting() -> None:
    # Boot reconcile must NEVER pop UAC; it ensures the no-elevation fallback.
    mgr, calls = _mk(task_info=None)
    mgr.install(_SPEC, interactive=False)
    assert "elevate_register" not in calls
    assert "write_shortcut" in calls


def test_install_noninteractive_keeps_fallback_when_task_is_stale() -> None:
    # Boot reconcile finds a task pointing at an old install (path drift, BUG-006
    # class). It must NOT elevate (no UAC at boot) — it ensures the shortcut
    # fallback so autostart still works until the user re-enables instant start.
    stale = _TaskInfo(
        execute=r"C:\Old\pythonw.exe",
        arguments="-m dodaios.ui.web.launcher",
        working_dir=r"C:\Old",
    )
    mgr, calls = _mk(task_info=stale)
    mgr.install(_SPEC, interactive=False)
    assert "elevate_register" not in calls
    assert "write_shortcut" in calls


def test_install_noninteractive_is_noop_when_task_already_matches() -> None:
    # Common boot: the task is already there and correct → do nothing at all.
    mgr, calls = _mk(task_info=_MATCHING_INFO)
    mgr.install(_SPEC, interactive=False)
    assert calls == []


def test_uninstall_interactive_removes_task_and_shortcut() -> None:
    mgr, calls = _mk(task_info=_MATCHING_INFO, shortcut_present=True)
    mgr.uninstall(interactive=True)
    assert "remove_shortcut" in calls
    assert "elevate_unregister" in calls


def test_uninstall_noninteractive_never_elevates() -> None:
    mgr, calls = _mk(task_info=_MATCHING_INFO, shortcut_present=True)
    mgr.uninstall(interactive=False)
    assert "remove_shortcut" in calls
    assert "elevate_unregister" not in calls


def test_uninstall_reports_the_task_that_survived_the_silent_path() -> None:
    # Removing the task needs elevation, which the boot reconcile must not
    # prompt for. Reporting "Autostart disabled." anyway was a lie: the logon
    # task kept starting Jarvis every login while Settings showed the toggle
    # off, with nothing to explain the mismatch.
    mgr, _ = _mk(task_info=_MATCHING_INFO, shortcut_present=True)
    st = mgr.uninstall(interactive=False)
    assert st.installed is True
    assert "scheduled task" in st.detail.lower()


def test_uninstall_reports_the_task_that_survived_a_declined_uac() -> None:
    mgr, calls = _mk(
        task_info=_MATCHING_INFO, shortcut_present=True, elevate_ok=False,
    )
    st = mgr.uninstall(interactive=True)
    assert "elevate_unregister" in calls
    assert st.installed is True


def test_uninstall_reports_disabled_once_the_task_is_really_gone() -> None:
    mgr, _ = _mk(task_info=_MATCHING_INFO, shortcut_present=True)
    st = mgr.uninstall(interactive=True)
    assert st.installed is False
    assert st.detail == "Autostart disabled."


def test_install_drops_a_leftover_shortcut_when_the_task_already_matches() -> None:
    # A boot whose task query transiently failed (a failed query reads as "no
    # task") writes the .lnk fallback; nothing removed it once the task became
    # visible again, so Jarvis started TWICE at login — via the task and via
    # the Explorer startup queue.
    mgr, calls = _mk(task_info=_MATCHING_INFO, shortcut_present=True)
    mgr.install(_SPEC, interactive=False)
    assert calls == ["remove_shortcut"]


def test_a_leftover_shortcut_beside_a_matching_task_is_not_current() -> None:
    # The boot reconcile only calls install() for an entry that is not current.
    # Reporting task + leftover shortcut as current kept the shortcut forever,
    # and with it a second launch at login from the folder that wrote it.
    mgr, calls = _mk(task_info=_MATCHING_INFO, shortcut_present=True)
    st = mgr.status(_SPEC)
    assert st.installed is True
    assert st.matches_spec is False
    assert "leftover" in st.detail
    assert calls == []


def test_reconcile_removes_a_leftover_shortcut_beside_a_matching_task(monkeypatch) -> None:
    import dodaios.autostart as autostart

    from .conftest import make_caps, make_cfg

    mgr, calls = _mk(task_info=_MATCHING_INFO, shortcut_present=True)
    monkeypatch.setattr(autostart, "make_autostart_manager", lambda caps: mgr)
    monkeypatch.setattr(autostart, "resolve_launch_spec", lambda cfg: _SPEC)
    result = autostart.reconcile_autostart(make_cfg(enabled=True), make_caps())
    assert calls == ["remove_shortcut"]
    assert result.matches_spec is True


def test_truncated_shortcut_readback_is_drift_not_a_match(monkeypatch) -> None:
    # Padding the missing fields with "" made a half-failed COM read compare
    # equal to a spec with no args/working dir — reporting a stale shortcut as
    # current and suppressing the refresh that would have fixed it.
    import base64
    import subprocess
    from pathlib import Path

    from dodaios.autostart import windows as win_mod

    bare = LaunchSpec(program=r"C:\Python\pythonw.exe", args=(), working_dir="")
    encoded = base64.b64encode(bare.program.encode("utf-8")).decode("ascii")
    monkeypatch.setattr(Path, "exists", lambda self: True)
    # Force the PowerShell read-back path: in-process COM is "not possible here".
    monkeypatch.setattr(win_mod, "_read_shortcut_in_process", lambda link: None)
    monkeypatch.setattr(
        win_mod,
        "_run_powershell",
        lambda script: subprocess.CompletedProcess(
            ["powershell"],
            0,
            stdout=win_mod._READBACK_SENTINEL + encoded + "\n",
            stderr="",
        ),
    )
    assert WindowsAutostart()._default_shortcut_matches(bare) is False


# --------------------------------------------------------------------------- #
# A task that exists but is switched OFF (the Windows twin of the audit's      #
# Linux `Hidden=true` finding: status contradicting the real OS state)         #
# --------------------------------------------------------------------------- #

_DISABLED_INFO = _TaskInfo(
    execute=_SPEC.program,
    arguments="-m dodaios.ui.web.launcher",
    working_dir=_SPEC.working_dir,
    enabled=False,
)


def test_status_reports_a_disabled_task_as_not_current() -> None:
    # The action still matches this install, so the old read-back said
    # "Autostart enabled via scheduled task" for a task that never fires.
    mgr, _ = _mk(task_info=_DISABLED_INFO)
    st = mgr.status(_SPEC)
    assert st.installed is True
    assert st.matches_spec is False
    assert "disabled" in st.detail.lower()


def test_install_noninteractive_writes_the_fallback_for_a_disabled_task() -> None:
    # Worst case of the old behaviour: install() saw a matching action, called
    # itself done, and skipped the .lnk — so autostart was dead on BOTH paths.
    mgr, calls = _mk(task_info=_DISABLED_INFO)
    mgr.install(_SPEC, interactive=False)
    assert "write_shortcut" in calls
    assert "elevate_register" not in calls  # the boot reconcile never prompts


def test_install_interactive_reregisters_a_disabled_task() -> None:
    mgr, calls = _mk(task_info=_DISABLED_INFO, elevate_ok=True)
    st = mgr.install(_SPEC, interactive=True)
    assert "elevate_register" in calls
    assert st.matches_spec is True


# --------------------------------------------------------------------------- #
# Elevated launcher: the temp script path must survive a space                 #
# --------------------------------------------------------------------------- #


def test_elevated_launcher_quotes_a_temp_path_with_spaces(monkeypatch) -> None:
    """Start-Process joins -ArgumentList with spaces and quotes nothing.

    On an account named "John Doe" the elevated PowerShell received
    ``-File C:\\Users\\John`` and aborted, so the user approved a UAC prompt and
    autostart still fell back to the throttled .lnk — logged as "UAC declined".
    """
    import os
    import subprocess

    from dodaios.autostart import windows as win_mod

    spaced = r"C:\Users\John Doe\AppData\Local\Temp\tmp_autostart.ps1"
    fd = os.open(os.devnull, os.O_WRONLY)
    monkeypatch.setattr(win_mod.tempfile, "mkstemp", lambda suffix="": (fd, spaced))
    monkeypatch.setattr(win_mod.os, "unlink", lambda _path: None)

    seen: list[str] = []

    def _fake_run(argv, **_kwargs):
        seen.append(argv[-1])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(win_mod.subprocess, "run", _fake_run)

    assert win_mod._run_powershell_elevated("exit 0") is True
    assert f"'-File','\"{spaced}\"'" in seen[0]


def test_elevated_launcher_fails_safe_on_a_null_exit_code(monkeypatch) -> None:
    """`exit $null` exits 0 — measured on Windows 11, 2026-08-10.

    Start-Process -Verb RunAs -Wait -PassThru can return a process object whose
    ExitCode is $null, so a registration that never happened was reported as
    success: install() then deleted the .lnk fallback and logged "scheduled
    task registered", leaving autostart dead on both paths.
    """
    import os
    import subprocess

    from dodaios.autostart import windows as win_mod

    fd = os.open(os.devnull, os.O_WRONLY)
    monkeypatch.setattr(win_mod.tempfile, "mkstemp", lambda suffix="": (fd, "x.ps1"))
    monkeypatch.setattr(win_mod.os, "unlink", lambda _path: None)

    seen: list[str] = []

    def _fake_run(argv, **_kwargs):
        seen.append(argv[-1])
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(win_mod.subprocess, "run", _fake_run)
    win_mod._run_powershell_elevated("exit 0")

    launcher = seen[0]
    assert "if ($null -eq $p -or $null -eq $p.ExitCode) { exit 1 }" in launcher
    # The guard must come BEFORE the forwarding exit, or it changes nothing.
    assert launcher.index("$null -eq $p.ExitCode") < launcher.index("exit $p.ExitCode")


# --------------------------------------------------------------------------- #
# Silent paths stay in-process (issue #713: Bitdefender blocked the app for   #
# spawning powershell.exe on its first launch to write the startup shortcut)  #
# --------------------------------------------------------------------------- #


def _no_powershell(script: str):
    raise AssertionError("the silent autostart path must not spawn PowerShell")


def test_boot_reconcile_writes_the_shortcut_without_powershell(monkeypatch, tmp_path) -> None:
    from dodaios.autostart import windows as win_mod

    written: list[tuple[object, LaunchSpec, object]] = []
    monkeypatch.setattr(win_mod, "_run_powershell", _no_powershell)
    monkeypatch.setattr(win_mod, "_tag_shortcut_aumid", lambda link: True)
    monkeypatch.setattr(win_mod, "_startup_dir", lambda: tmp_path)
    monkeypatch.setattr(
        win_mod,
        "_write_shortcut_in_process",
        lambda link, spec, icon: written.append((link, spec, icon)) or True,
    )
    mgr = WindowsAutostart(task_probe=lambda name: None, run_elevated=lambda s: False)
    mgr.install(_SPEC)
    assert len(written) == 1
    assert written[0][1] == _SPEC


def test_shortcut_falls_back_to_powershell_only_when_in_process_is_impossible(
    monkeypatch, tmp_path
) -> None:
    from dodaios.autostart import windows as win_mod

    scripts: list[str] = []
    monkeypatch.setattr(win_mod, "_run_powershell", lambda script: scripts.append(script))
    monkeypatch.setattr(win_mod, "_tag_shortcut_aumid", lambda link: True)
    monkeypatch.setattr(win_mod, "_startup_dir", lambda: tmp_path)
    monkeypatch.setattr(win_mod, "_write_shortcut_in_process", lambda link, spec, icon: False)
    WindowsAutostart()._default_write_shortcut(_SPEC)
    assert len(scripts) == 1
    assert "CreateShortcut" in scripts[0]


def test_task_probe_uses_com_and_skips_powershell(monkeypatch) -> None:
    from dodaios.autostart import windows as win_mod

    monkeypatch.setattr(win_mod, "_run_powershell", _no_powershell)
    monkeypatch.setattr(win_mod, "_query_task_in_process", lambda name: _MATCHING_INFO)
    assert WindowsAutostart()._default_task_probe(TASK_NAME) == _MATCHING_INFO


def test_task_probe_com_failure_reads_as_absent_not_powershell(monkeypatch) -> None:
    from dodaios.autostart import windows as win_mod

    def boom(name: str):
        raise OSError("Task Scheduler unavailable")

    monkeypatch.setattr(win_mod, "_run_powershell", _no_powershell)
    monkeypatch.setattr(win_mod, "_query_task_in_process", boom)
    assert WindowsAutostart()._default_task_probe(TASK_NAME) is None


def test_task_probe_without_pywin32_falls_back_to_powershell(monkeypatch) -> None:
    import subprocess

    from dodaios.autostart import windows as win_mod

    monkeypatch.setattr(win_mod, "_win32com", lambda: None)
    monkeypatch.setattr(
        win_mod,
        "_run_powershell",
        lambda script: subprocess.CompletedProcess(["powershell"], 0, stdout="", stderr=""),
    )
    assert WindowsAutostart()._default_task_probe(TASK_NAME) is None


# --------------------------------------------------------------------------- #
# The task under the product's earlier name                                    #
# --------------------------------------------------------------------------- #


def test_a_matching_task_under_the_earlier_name_counts_as_current() -> None:
    mgr, calls, tasks, probed = _scheduler(legacy_task_info=_MATCHING_INFO)

    st = mgr.status(_SPEC)
    mgr.install(_SPEC, interactive=False)

    assert st.installed is True and st.matches_spec is True
    assert st.entry_path == f"Task Scheduler\\{_LEGACY_TASK_NAME}"
    # The silent boot reconcile never elevates and writes no second entry.
    assert calls == []
    assert set(tasks) == {_LEGACY_TASK_NAME}
    assert probed[:2] == [TASK_NAME, _LEGACY_TASK_NAME]


def test_the_earlier_name_is_not_asked_for_once_the_task_moved() -> None:
    mgr, _calls, _tasks, probed = _scheduler(
        task_info=_MATCHING_INFO, legacy_task_info=_MATCHING_INFO
    )

    mgr.status(_SPEC)

    assert probed == [TASK_NAME]


def test_an_earlier_task_starting_the_earlier_launcher_and_package_still_matches(
    tmp_path,
) -> None:
    # An earlier release registered {app}\PersonalJarvis.exe -m jarvis...; the
    # install ships that file beside DodaiosApp.exe and the old module path
    # resolves to the same module, so the task starts this install unchanged.
    app = tmp_path / "Programs" / "Dodaios"
    app.mkdir(parents=True)
    legacy_exe = app / LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES[0]
    legacy_exe.write_bytes(b"MZ")
    spec = LaunchSpec(
        program=str(app / WINDOWS_BRANDED_LAUNCHER_FILE_NAME),
        args=("-m", "dodaios.ui.web.launcher"),
        working_dir=str(app),
    )
    old = _TaskInfo(
        execute=str(legacy_exe),
        arguments="-m jarvis.ui.web.launcher",
        working_dir=str(app),
    )
    mgr, calls, _tasks, _probed = _scheduler(legacy_task_info=old)

    assert mgr.status(spec).matches_spec is True
    mgr.install(spec, interactive=False)
    assert calls == []


def test_an_earlier_launcher_name_that_is_gone_is_drift(tmp_path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    spec = LaunchSpec(
        program=str(app / WINDOWS_BRANDED_LAUNCHER_FILE_NAME),
        args=("-m", "dodaios.ui.web.launcher"),
        working_dir=str(app),
    )
    old = _TaskInfo(
        execute=str(app / LEGACY_WINDOWS_BRANDED_LAUNCHER_FILE_NAMES[0]),
        arguments="-m dodaios.ui.web.launcher",
        working_dir=str(app),
    )
    mgr, _calls, _tasks, _probed = _scheduler(legacy_task_info=old)

    assert mgr.status(spec).matches_spec is False


def test_an_unrelated_executable_in_the_same_folder_is_drift(tmp_path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "other.exe").write_bytes(b"MZ")
    spec = LaunchSpec(
        program=str(app / WINDOWS_BRANDED_LAUNCHER_FILE_NAME),
        args=("-m", "dodaios.ui.web.launcher"),
        working_dir=str(app),
    )
    other = _TaskInfo(
        execute=str(app / "other.exe"),
        arguments="-m dodaios.ui.web.launcher",
        working_dir=str(app),
    )
    mgr, _calls, _tasks, _probed = _scheduler(legacy_task_info=other)

    assert mgr.status(spec).matches_spec is False


def test_an_interactive_enable_moves_the_task_to_the_current_name_in_one_step() -> None:
    mgr, calls, tasks, _probed = _scheduler(legacy_task_info=_MATCHING_INFO)

    st = mgr.install(_SPEC, interactive=True)

    # One elevation registers the current name and removes the earlier one.
    assert calls.count("elevate_register") == 1
    assert f"unregister:{_LEGACY_TASK_NAME}" in calls
    assert "write_shortcut" not in calls
    assert set(tasks) == {TASK_NAME}
    assert st.matches_spec is True
    assert st.entry_path == f"Task Scheduler\\{TASK_NAME}"


def test_a_declined_rename_keeps_the_earlier_task_and_writes_no_second_entry() -> None:
    mgr, calls, tasks, _probed = _scheduler(
        legacy_task_info=_MATCHING_INFO, elevate_ok=False
    )

    st = mgr.install(_SPEC, interactive=True)

    assert "elevate_register" in calls
    assert "write_shortcut" not in calls
    assert set(tasks) == {_LEGACY_TASK_NAME}
    assert st.matches_spec is True


def test_the_register_script_removes_the_earlier_name_only_after_registering() -> None:
    script = build_register_task_script(
        TASK_NAME, _SPEC, user_id="u", replaced_task_names=(_LEGACY_TASK_NAME,)
    )

    register = script.index(f"Register-ScheduledTask -TaskName '{TASK_NAME}'")
    unregister = script.index(f"Unregister-ScheduledTask -TaskName '{_LEGACY_TASK_NAME}'")
    assert register < unregister
    # Both inside the one try block: a failed registration skips the removal.
    assert unregister < script.index("} catch { exit 1 }")


def test_an_interactive_uninstall_removes_every_name_in_one_elevation() -> None:
    mgr, calls, tasks, _probed = _scheduler(
        task_info=_MATCHING_INFO, legacy_task_info=_MATCHING_INFO
    )

    st = mgr.uninstall(interactive=True)

    assert calls.count("elevate_unregister") == 1
    assert {f"unregister:{TASK_NAME}", f"unregister:{_LEGACY_TASK_NAME}"} <= set(calls)
    assert tasks == {}
    assert st.installed is False


def test_a_silent_uninstall_reports_a_surviving_task_under_the_earlier_name() -> None:
    mgr, calls, _tasks, _probed = _scheduler(legacy_task_info=_MATCHING_INFO)

    st = mgr.uninstall(interactive=False)

    assert "elevate_unregister" not in calls
    assert st.installed is True
    assert st.entry_path == f"Task Scheduler\\{_LEGACY_TASK_NAME}"


def test_a_startup_shortcut_under_the_earlier_name_counts_and_is_retired(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    from dodaios.autostart import windows as win_mod

    startup = win_mod._startup_dir()
    startup.mkdir(parents=True)
    old = startup / LEGACY_WINDOWS_SHORTCUT_FILE_NAMES[0]
    old.write_bytes(b"lnk")
    mgr = WindowsAutostart(task_probe=lambda _name: None)

    # It starts the app at login just the same: present, and beside a task a
    # second start, so it is retired like every earlier startup entry.
    assert mgr._default_shortcut_present() is True
    mgr._default_remove_shortcut()
    assert not old.exists()
    assert mgr._default_shortcut_present() is False
