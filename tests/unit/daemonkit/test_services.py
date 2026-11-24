"""The three OS service backends, rendered and driven through fake tools."""

from __future__ import annotations

import plistlib
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

import pytest

from daemonkit.service import NullServiceManager, ServiceSpec, service_manager
from daemonkit.service.launchd import LaunchdAgentManager, render_plist
from daemonkit.service.systemd import SystemdUserManager, quote_exec_arg, render_unit
from daemonkit.service.windows import WindowsTaskManager, render_task_xml

SPEC = ServiceSpec(
    name="srv",
    argv=("/opt/my app/python3", "-m", "daemonkit.supervise", "--", "server", "50%", "$HOME"),
    description="My server",
    working_dir="/srv/app",
    log_path="/var/log/srv.log",
)


class FakeTools:
    """Answers commands from a table; records every call."""

    def __init__(self, answers: dict[tuple[str, ...], tuple[int, str]] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        key = tuple(argv)
        self.calls.append(key)
        code, out = self.answers.get(key, (0, ""))
        return subprocess.CompletedProcess(list(argv), code, out, "")


# -- systemd -------------------------------------------------------------------


def test_exec_arguments_are_quoted_for_systemd() -> None:
    assert quote_exec_arg("plain/path-1.0") == "plain/path-1.0"
    assert quote_exec_arg("with space") == '"with space"'
    assert quote_exec_arg("50%") == "50%%"
    assert quote_exec_arg("$HOME") == '"$$HOME"'
    assert quote_exec_arg('say "hi"') == '"say \\"hi\\""'
    assert quote_exec_arg("") == '""'


def test_unit_file_restarts_a_dead_supervisor_only() -> None:
    unit = render_unit(ServiceSpec(**{**SPEC.__dict__, "env": {"MODE": "server"}}))
    assert 'ExecStart="/opt/my app/python3" -m daemonkit.supervise -- server 50%% "$$HOME"' in unit
    assert "Restart=on-failure" in unit
    assert "WorkingDirectory=/srv/app" in unit
    assert 'Environment="MODE=server"' in unit
    assert "WantedBy=default.target" in unit
    assert "Description=My server" in unit


def _systemd(tmp_path: Path, tools: FakeTools, *, linger: bool = False) -> SystemdUserManager:
    linger_dir = tmp_path / "linger"
    linger_dir.mkdir()
    if linger:
        (linger_dir / "me").touch()
    return SystemdUserManager(
        runner=tools,
        unit_dir=tmp_path / "units",
        linger_dir=linger_dir,
        user="me",
        which=lambda _name: "/usr/bin/systemctl",
    )


def test_systemd_install_enables_and_starts_and_reports(tmp_path: Path) -> None:
    tools = FakeTools(
        {
            ("systemctl", "--user", "is-enabled", "srv.service"): (0, "enabled\n"),
            ("systemctl", "--user", "is-active", "srv.service"): (0, "active\n"),
        }
    )
    manager = _systemd(tmp_path, tools)
    status = manager.install(SPEC)
    assert (tmp_path / "units" / "srv.service").read_text().startswith("# Written by daemonkit")
    assert ("systemctl", "--user", "daemon-reload") in tools.calls
    assert ("systemctl", "--user", "enable", "--now", "srv.service") in tools.calls
    assert not any(call[0] == "loginctl" for call in tools.calls)
    assert status.installed and status.active and status.starts_at == "login"


def test_systemd_boot_start_turns_on_linger(tmp_path: Path) -> None:
    tools = FakeTools({("loginctl", "enable-linger", "me"): (1, "access denied")})
    manager = _systemd(tmp_path, tools)
    status = manager.install(SPEC, start_at="boot", start_now=False)
    assert ("systemctl", "--user", "enable", "srv.service") in tools.calls
    assert ("loginctl", "enable-linger", "me") in tools.calls
    assert "enable-linger" in status.detail and "access denied" in status.detail


def test_systemd_reports_boot_start_when_lingering(tmp_path: Path) -> None:
    tools = FakeTools({("systemctl", "--user", "is-enabled", "srv.service"): (0, "enabled")})
    manager = _systemd(tmp_path, tools, linger=True)
    manager.install(SPEC, start_at="boot")
    assert not any(call[0] == "loginctl" for call in tools.calls)
    assert manager.status(SPEC).starts_at == "boot"


def test_systemd_uninstall_removes_the_unit(tmp_path: Path) -> None:
    tools = FakeTools()
    manager = _systemd(tmp_path, tools)
    manager.install(SPEC)
    status = manager.uninstall(SPEC)
    assert not (tmp_path / "units" / "srv.service").exists()
    assert ("systemctl", "--user", "disable", "--now", "srv.service") in tools.calls
    assert not status.installed


def test_systemd_unavailable_without_a_user_manager(tmp_path: Path) -> None:
    tools = FakeTools(
        {("systemctl", "--user", "show-environment"): (1, "Failed to connect to bus")}
    )
    manager = _systemd(tmp_path, tools)
    status = manager.install(SPEC)
    assert not status.supported and not status.installed
    assert "Failed to connect to bus" in status.detail
    missing = SystemdUserManager(runner=tools, which=lambda _n: None)
    assert missing.available()[0] is False


# -- launchd -------------------------------------------------------------------


def test_plist_keeps_alive_only_after_a_failure() -> None:
    data = plistlib.loads(render_plist(ServiceSpec(**{**SPEC.__dict__, "label": "com.ex.srv"})))
    assert data["Label"] == "com.ex.srv"
    assert data["ProgramArguments"] == list(SPEC.argv)
    assert data["RunAtLoad"] is True
    assert data["KeepAlive"] == {"SuccessfulExit": False}
    assert data["StandardOutPath"] == data["StandardErrorPath"] == "/var/log/srv.log"
    assert data["WorkingDirectory"] == "/srv/app"


def _launchd(tmp_path: Path, tools: FakeTools) -> LaunchdAgentManager:
    return LaunchdAgentManager(
        runner=tools, agents_dir=tmp_path, uid=501, which=lambda _n: "/bin/launchctl"
    )


def test_launchd_install_reloads_and_bootstraps(tmp_path: Path) -> None:
    target = "gui/501/local.daemonkit.srv"
    tools = FakeTools({("launchctl", "print", target): (0, "state = running\n")})
    manager = _launchd(tmp_path, tools)
    status = manager.install(SPEC, start_at="boot")
    plist = tmp_path / "local.daemonkit.srv.plist"
    assert plist.exists()
    assert tools.calls[0] == ("launchctl", "bootout", target)
    assert ("launchctl", "bootstrap", "gui/501", str(plist)) in tools.calls
    assert status.installed and status.active and status.starts_at == "login"
    assert "login only" in status.detail


def test_launchd_start_kickstarts_a_loaded_agent_and_stop_boots_it_out(tmp_path: Path) -> None:
    target = "gui/501/local.daemonkit.srv"
    tools = FakeTools({("launchctl", "print", target): (0, "state = waiting")})
    manager = _launchd(tmp_path, tools)
    assert manager.start(SPEC)
    assert ("launchctl", "kickstart", target) in tools.calls
    assert manager.stop(SPEC)
    assert tools.calls[-1] == ("launchctl", "bootout", target)


def test_launchd_uninstall_deletes_the_plist(tmp_path: Path) -> None:
    tools = FakeTools()
    manager = _launchd(tmp_path, tools)
    manager.install(SPEC, start_now=False)
    assert not any(call[1] == "bootstrap" for call in tools.calls)
    assert not manager.uninstall(SPEC).installed
    assert not list(tmp_path.glob("*.plist"))


# -- Windows -------------------------------------------------------------------

WIN_SPEC = ServiceSpec(
    name="srv",
    argv=(r"C:\Program Files\Py\pythonw.exe", "-m", "daemonkit.supervise", "--", "a b", "c"),
    description="My <server>",
    working_dir=r"C:\work",
    label=r"\Example\Server",
)
NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}


def test_task_xml_is_a_logon_task_that_restarts_and_never_times_out() -> None:
    xml = render_task_xml(WIN_SPEC, user_id="PC\\me")
    root = ET.fromstring(xml.encode("utf-16"))  # noqa: S314 - our own generated XML
    assert root.findtext("t:Triggers/t:LogonTrigger/t:UserId", namespaces=NS) == "PC\\me"
    principal = root.find("t:Principals/t:Principal", NS)
    assert principal is not None
    assert principal.findtext("t:LogonType", namespaces=NS) == "InteractiveToken"
    assert principal.findtext("t:RunLevel", namespaces=NS) == "LeastPrivilege"
    settings = root.find("t:Settings", NS)
    assert settings is not None
    assert settings.findtext("t:ExecutionTimeLimit", namespaces=NS) == "PT0S"
    assert settings.findtext("t:DisallowStartIfOnBatteries", namespaces=NS) == "false"
    assert settings.findtext("t:RestartOnFailure/t:Count", namespaces=NS) == "999"
    exec_ = root.find("t:Actions/t:Exec", NS)
    assert exec_ is not None
    assert exec_.findtext("t:Command", namespaces=NS) == WIN_SPEC.argv[0]
    assert exec_.findtext("t:Arguments", namespaces=NS) == '-m daemonkit.supervise -- "a b" c'
    assert exec_.findtext("t:WorkingDirectory", namespaces=NS) == r"C:\work"
    assert root.findtext("t:RegistrationInfo/t:Description", namespaces=NS) == "My <server>"


def test_task_xml_refuses_environment() -> None:
    with pytest.raises(ValueError, match="--env"):
        render_task_xml(ServiceSpec(**{**WIN_SPEC.__dict__, "env": {"A": "1"}}), user_id="me")


class FakeRunKey:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_windows_install_registers_a_task_and_runs_it(tmp_path: Path) -> None:
    created: list[str] = []

    class Tools(FakeTools):
        def __call__(self, argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
            if argv[1] == "/Create":
                xml_path = Path(argv[argv.index("/XML") + 1])
                created.append(xml_path.read_text(encoding="utf-16"))
            return super().__call__(argv)

    tools = Tools()
    run_key = FakeRunKey()
    run_key.set("srv", "old")
    manager = WindowsTaskManager(runner=tools, registry=run_key, user_id="PC\\me")
    status = manager.install(WIN_SPEC)
    assert created and "<LogonTrigger>" in created[0]
    assert ("schtasks", "/Run", "/TN", r"\Example\Server") in tools.calls
    assert run_key.values == {}  # the task replaces an earlier Run value
    assert status.mechanism == "windows-task" and status.installed


def test_windows_falls_back_to_the_run_key_when_the_task_is_refused() -> None:
    name = r"\Example\Server"
    tools = FakeTools(
        {
            ("schtasks", "/Query", "/TN", name): (1, "not found"),
        }
    )

    def refuse(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if argv[1] == "/Create":
            return subprocess.CompletedProcess(list(argv), 1, "", "ERROR: Access is denied.")
        return tools(argv)

    run_key = FakeRunKey()
    spawned: list[list[str]] = []
    manager = WindowsTaskManager(
        runner=refuse,
        registry=run_key,
        user_id="me",
        spawn=lambda argv, **_kw: spawned.append(argv) or 1,
    )
    status = manager.install(WIN_SPEC)
    assert run_key.values["srv"] == subprocess.list2cmdline(list(WIN_SPEC.argv))
    assert spawned == [list(WIN_SPEC.argv)]
    assert status.mechanism == "windows-run-key" and status.installed
    assert "Access is denied" in status.detail
    assert not manager.stop(WIN_SPEC)
    assert not manager.uninstall(WIN_SPEC).installed
    assert run_key.values == {}


# -- selection -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "kind"),
    [
        ("linux", SystemdUserManager),
        ("darwin", LaunchdAgentManager),
        ("win32", WindowsTaskManager),
        ("freebsd14", NullServiceManager),
    ],
)
def test_service_manager_per_platform(platform: str, kind: type) -> None:
    assert isinstance(service_manager(platform), kind)


def test_spec_rejects_line_breaks_and_empty_commands() -> None:
    with pytest.raises(ValueError):
        ServiceSpec(name="srv", argv=())
    with pytest.raises(ValueError):
        ServiceSpec(name="srv", argv=("a\nb",))
