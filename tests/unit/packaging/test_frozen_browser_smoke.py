"""Failure and isolation guarantees for the native-package acceptance probe."""

import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler

import pytest

from dodaios.core.instance import DEV_PORT_OFFSET
from scripts.ci import check_frozen_browser as probe
from tests.fakes.fake_frozen_browser import FrozenBrowserApp
from tests.fakes.loopback_http import LoopbackHTTPServer


def test_probe_does_not_inherit_account_or_runtime_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-frozen-app")
    monkeypatch.setenv("JARVIS_CONFIG", "existing-user-config")
    monkeypatch.setenv("GROK_AUTH_PATH", "existing-subscription")
    monkeypatch.setenv("PYTHONPATH", "source-checkout")
    env = probe.isolated_env(tmp_path, 50000, "isolated-control-key")
    assert not {"OPENAI_API_KEY", "GROK_AUTH_PATH", "PYTHONPATH"} & env.keys()
    assert env["JARVIS_CONFIG"] == str(tmp_path / "jarvis.toml")
    assert env["JARVIS_CONTROL_API_KEY"] == "isolated-control-key"
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_probe_refuses_http_redirect_instead_of_forwarding_its_key(method):
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/unrelated")
            self.end_headers()

        do_POST = do_GET

        def log_message(self, *_args):
            pass  # Test traffic is intentionally quiet.

    server = LoopbackHTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(probe.ProbeHTTPError) as error:
            probe.request_json(server.server_port, "/api/health", "test-key", method=method)
        assert error.value.code == 302
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _boot_simulated_app(tmp_path, monkeypatch, app):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(probe.subprocess, "Popen", lambda *_args, **_kwargs: app)
    monkeypatch.setattr(probe, "request_json", app.request)
    monkeypatch.setattr(probe, "mcp_request", app.mcp)
    monkeypatch.setattr(probe, "check_macos_permissions", lambda *_args: {})
    monkeypatch.setattr(probe, "capture_frame", app.capture)
    monkeypatch.setattr(probe, "stop_owned_tree", app.stopped.append)
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    return probe.boot(tmp_path / "launcher", profile, tmp_path / "boot", "test-key", timeout=5)


@pytest.mark.parametrize("installed,running", [(False, False), (True, False), (False, True)])
def test_probe_requests_optional_setup_once_and_still_requires_a_frame(
    tmp_path, monkeypatch, installed, running,
):
    app = FrozenBrowserApp(installed=installed, running=running)
    report = _boot_simulated_app(tmp_path, monkeypatch, app)
    posts = [request for request in app.requests if request[0] == "POST"]
    assert posts == (
        [] if installed or running else [("POST", "/api/society/browser/install", "test-key")]
    )
    assert report["browser_install_requested"] is (not installed and not running)
    assert len(app.frames) == 1
    assert app.stopped == [app]
    assert report["width"] == 640


def test_probe_refuses_to_accept_an_ignored_install_request(tmp_path, monkeypatch):
    app = FrozenBrowserApp(refuse=True)
    with pytest.raises(RuntimeError, match="declined the requested browser setup"):
        _boot_simulated_app(tmp_path, monkeypatch, app)
    assert app.frames == []
    assert app.stopped == [app]


def test_failed_stream_cannot_count_as_first_frame(tmp_path, monkeypatch):
    class FailedViewer:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def recv(self, **_kwargs):
            return '{"kind":"error","detail":"private runtime failure"}'

    monkeypatch.setattr(probe, "connect", lambda *_args, **_kwargs: FailedViewer())
    with pytest.raises(RuntimeError, match="failed before its first frame"):
        probe.capture_frame(50000, "test-key", tmp_path / "frame.jpg")
    assert not (tmp_path / "frame.jpg").exists()


def test_first_install_requires_a_fresh_profile(tmp_path, monkeypatch):
    (tmp_path / "profile").mkdir()
    monkeypatch.setattr(
        probe.sys,
        "argv",
        ["probe", "--executable", __file__, "--output", str(tmp_path)],
    )
    with pytest.raises(FileExistsError):
        probe.main()


def _snapshot(microphone: str | None, bundle_id: str | None) -> dict:
    rows = [] if microphone is None else [{"id": "microphone", "status": microphone}]
    return {"permissions": rows, "app_identity": {"bundle_id": bundle_id}}


def test_permission_check_asks_nothing_off_macos(monkeypatch):
    """Windows and Linux have no permission port to ask."""
    monkeypatch.setattr(probe.sys, "platform", "linux")

    def explode(*_args, **_kwargs):
        raise AssertionError("no request may be made off macOS")

    monkeypatch.setattr(probe, "request_json", explode)

    assert probe.check_macos_permissions(50000, "test-key") == {}


def test_a_frozen_mac_app_that_can_read_its_microphone_passes(monkeypatch):
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    monkeypatch.setattr(
        probe,
        "request_json",
        lambda *_args: _snapshot("not_determined", probe.ACCEPTED_BUNDLE_IDS[-1]),
    )

    assert probe.check_macos_permissions(50000, "test-key") == {
        "microphone_permission": "not_determined",
        "bundle_id": probe.ACCEPTED_BUNDLE_IDS[-1],
    }


@pytest.mark.parametrize("microphone", ["unavailable", None])
def test_a_frozen_mac_app_without_its_microphone_framework_fails(monkeypatch, microphone):
    """The v2.5.0 image: AVFoundation missing, so the row reads 'unavailable' for good."""
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    monkeypatch.setattr(
        probe,
        "request_json",
        lambda *_args: _snapshot(microphone, probe.ACCEPTED_BUNDLE_IDS[0]),
    )

    with pytest.raises(RuntimeError, match="AVFoundation"):
        probe.check_macos_permissions(50000, "test-key")


def test_a_frozen_mac_app_with_a_foreign_bundle_id_fails(monkeypatch):
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    monkeypatch.setattr(
        probe,
        "request_json",
        lambda *_args: _snapshot("denied", "com.example.other"),
    )

    with pytest.raises(RuntimeError, match="com.example.other"):
        probe.check_macos_permissions(50000, "test-key")


def test_a_missing_permission_route_fails_at_once_but_a_starting_app_is_retried(monkeypatch):
    monkeypatch.setattr(probe.sys, "platform", "darwin")

    def respond(code):
        def request(*_args):
            raise probe.ProbeHTTPError(code)

        return request

    monkeypatch.setattr(probe, "request_json", respond(404))
    with pytest.raises(RuntimeError, match="does not serve"):
        probe.check_macos_permissions(50000, "test-key")

    # 503 is "still starting": the boot loop retries it, so it must pass through.
    monkeypatch.setattr(probe, "request_json", respond(503))
    with pytest.raises(probe.ProbeHTTPError) as starting:
        probe.check_macos_permissions(50000, "test-key")
    assert starting.value.code == 503


# A stand-in for the frozen app: `<exe> serve` answers the three requests the
# smoke makes, with the permission status a given build would report.
_FAKE_APP = """#!{python}
import json, os, re, socketserver
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

config = open(os.environ["JARVIS_CONFIG"], encoding="utf-8").read()
port = int(re.search(r"admin_api_port\\s*=\\s*(\\d+)", config).group(1)) + {offset}
mode = "{mode}"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer " + os.environ["JARVIS_CONTROL_API_KEY"]:
            return self.reply(401, {{}})
        if self.path == "/api/health":
            return self.reply(200, {{"ok": True, "instance": "dev"}})
        if self.path == "/api/society/browser/status":
            return self.reply(200, {{"phase": "ready", "installed": True}})
        if self.path == "/api/permissions/status" and mode != "missing-route":
            microphone = "unavailable" if mode == "no-avfoundation" else "not_determined"
            return self.reply(200, {{
                "permissions": [{{"id": "microphone", "status": microphone}}],
                "app_identity": {{"bundle_id": "ai.personaljarvis.desktop"}},
            }})
        return self.reply(404, {{}})

    def do_POST(self):
        # The MCP tools surface a chat's coding CLI calls (issue #1879).
        if self.path != "/api/control/mcp/":
            return self.reply(404, {{}})
        length = int(self.headers.get("Content-Length") or 0)
        sent = json.loads(self.rfile.read(length) or b"{{}}")
        if sent.get("method") == "tools/list":
            names = ["whiteboard", "node", "create_artifact", "recall"]
            return self.reply(200, {{"result": {{"tools": [{{"name": n}} for n in names]}}}})
        name = sent.get("params", {{}}).get("name")
        failed = mode == "tool-fails" and name == "whiteboard"
        text = "board failed" if failed else "done"
        return self.reply(200, {{"result": {{
            "isError": failed, "content": [{{"type": "text", "text": text}}],
        }}}})

    def do_PUT(self):
        # The setup wizard's name save (issue #1734).
        length = int(self.headers.get("Content-Length") or 0)
        sent = json.loads(self.rfile.read(length) or b"{{}}")
        if self.path != "/api/settings/wake-word" or not sent.get("phrase"):
            return self.reply(404, {{}})
        if mode == "name-save-fails":
            return self.reply(500, {{"detail": "Something went wrong inside Dodaios (KeyError)."}})
        return self.reply(200, {{"ok": True, "resolved_engine": "stt_match"}})

    def reply(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        pass


class Server(ThreadingHTTPServer):
    # Bind without the host name lookup (socket.getfqdn), which stalls on the
    # hosted macOS runners; see tests/fakes/loopback_http.py.
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = "127.0.0.1", self.server_address[1]


Server(("127.0.0.1", port), Handler).serve_forever()
"""


def _boot_fake_app(tmp_path, monkeypatch, *, platform, mode):
    app = tmp_path / "fake-app"
    app.write_text(
        _FAKE_APP.format(python=sys.executable, offset=DEV_PORT_OFFSET, mode=mode),
        encoding="utf-8",
    )
    app.chmod(app.stat().st_mode | stat.S_IXUSR)
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(probe.sys, "platform", platform)
    monkeypatch.setattr(probe, "capture_frame", lambda *_args, **_kwargs: {})
    return probe.boot(app, profile, tmp_path / "first-install", "test-key", timeout=60)


posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="the stand-in app is a POSIX shebang script"
)


@posix_only
def test_a_mac_boot_records_the_permission_check(tmp_path, monkeypatch):
    report = _boot_fake_app(tmp_path, monkeypatch, platform="darwin", mode="ok")

    assert report["permissions"] == {
        "microphone_permission": "not_determined",
        "bundle_id": "ai.personaljarvis.desktop",
    }
    assert "healthy_seconds" in report
    assert report["setup_name_save"] == "stt_match"


@posix_only
def test_a_boot_whose_setup_name_save_fails_names_the_answer(tmp_path, monkeypatch):
    # Issue #1734: the setup wizard's first step answered HTTP 500.
    with pytest.raises(RuntimeError, match=r"setup name failed: HTTP 500 .*KeyError"):
        _boot_fake_app(tmp_path, monkeypatch, platform="linux", mode="name-save-fails")


@posix_only
def test_a_mac_boot_without_the_microphone_framework_fails_instead_of_passing(
    tmp_path, monkeypatch
):
    with pytest.raises(RuntimeError, match="AVFoundation"):
        _boot_fake_app(tmp_path, monkeypatch, platform="darwin", mode="no-avfoundation")


@posix_only
def test_a_mac_boot_without_the_permission_route_fails_instead_of_waiting(tmp_path, monkeypatch):
    with pytest.raises(RuntimeError, match="does not serve"):
        _boot_fake_app(tmp_path, monkeypatch, platform="darwin", mode="missing-route")


@posix_only
def test_a_boot_calls_the_tools_a_chat_draws_and_writes_with(tmp_path, monkeypatch):
    report = _boot_fake_app(tmp_path, monkeypatch, platform="linux", mode="ok")

    assert report["mcp_tools"] == 4
    assert report["whiteboard_ok"] and report["node_ok"]


@posix_only
def test_a_boot_whose_whiteboard_fails_names_the_tool(tmp_path, monkeypatch):
    # Issue #1879: drawing on the whiteboard failed in the installer build.
    with pytest.raises(RuntimeError, match="whiteboard tool failed: board failed"):
        _boot_fake_app(tmp_path, monkeypatch, platform="linux", mode="tool-fails")


def test_the_tool_check_waits_for_the_catalog(monkeypatch):
    listed = iter([[], [{"name": "recall"}]])
    calls: list[str] = []

    def mcp(port, key, method, params, **_kwargs):
        if method == "tools/list":
            tools = next(listed, [{"name": name} for name in probe.CHAT_TOOLS])
            return {"tools": tools}
        calls.append(params["name"])
        return {"isError": False, "content": []}

    monkeypatch.setattr(probe, "mcp_request", mcp)
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    report = probe.check_chat_tools(50000, "test-key")
    assert calls == ["whiteboard", "node"]
    assert report["mcp_tools"] == 3


def test_a_catalog_that_never_offers_the_tools_fails(monkeypatch):
    monkeypatch.setattr(probe, "mcp_request", lambda *_args, **_kwargs: {"tools": []})
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    with pytest.raises(RuntimeError, match="lacks whiteboard, node, create_artifact"):
        probe.check_chat_tools(50000, "test-key", wait_s=0)


# A stand-in for the frozen app as the vault guard hook (issue #1879).
_HOOK_APP = """#!{python}
import json, sys
if sys.argv[1:] != ["--vault-guard-hook"]:
    sys.exit(2)  # what an app without the flag answers: a usage error, exit 2
call = json.loads(sys.stdin.read() or "{{}}")
command = str(call.get("tool_input", {{}}).get("command") or "")
sys.exit(2 if "keyring get" in command else 0)
"""

# The 5.6.0 shape: the hook names a .py file the build does not ship, and the
# app answers every call with its usage error.
_BROKEN_HOOK_APP = """#!{python}
import sys
sys.exit(2)
"""


@posix_only
@pytest.mark.parametrize(("script", "passes"), [(_HOOK_APP, True), (_BROKEN_HOOK_APP, False)])
def test_the_vault_guard_hook_must_let_file_calls_through(tmp_path, script, passes):
    app = tmp_path / "hook-app"
    app.write_text(script.format(python=sys.executable), encoding="utf-8")
    app.chmod(app.stat().st_mode | stat.S_IXUSR)
    if passes:
        report = probe.check_vault_guard_hook(app)
        assert set(report) == {
            "vault_guard_read_seconds",
            "vault_guard_image_seconds",
            "vault_guard_shell_seconds",
            "vault_guard_vault_seconds",
        }
    else:
        with pytest.raises(RuntimeError, match="answered 2 for a read call"):
            probe.check_vault_guard_hook(app)


@posix_only
def test_a_boot_off_macos_never_asks_for_permissions(tmp_path, monkeypatch):
    report = _boot_fake_app(tmp_path, monkeypatch, platform="linux", mode="no-avfoundation")

    assert report["permissions"] == {}


class _BareStart:
    pid = 4100

    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.kwargs = kwargs

    def poll(self):
        return None


def _bare_start(monkeypatch, copies):
    """Run the bare-start check against a scripted list of copy sets."""
    started: list[_BareStart] = []

    def popen(argv, **kwargs):
        started.append(_BareStart(argv, **kwargs))
        return started[-1]

    sets = iter(copies)
    monkeypatch.setattr(probe.subprocess, "Popen", popen)
    monkeypatch.setattr(probe, "_bare_copies", lambda exe, since: next(sets, copies[-1]))
    monkeypatch.setattr(probe, "stop_owned_tree", lambda process: None)
    monkeypatch.setattr(probe.time, "sleep", lambda _s: None)
    return started


def test_a_bare_start_that_boots_passes(tmp_path, monkeypatch):
    started = _bare_start(monkeypatch, [{4100: 1.0}])
    report = probe.check_bare_start_settles(tmp_path / "exe", tmp_path / "profile", watch_s=0.05)
    assert report["bare_copies"] == 1
    (child,) = started
    # Started the way the tray and a restart start it: bare, on NUL streams.
    assert child.argv == [str(tmp_path / "exe")]
    assert child.kwargs["stdin"] is probe.subprocess.DEVNULL
    assert child.kwargs["stdout"] is probe.subprocess.DEVNULL


def test_a_bare_start_that_starts_copies_of_itself_fails(tmp_path, monkeypatch):
    killed: list[int] = []

    class _Copy:
        def __init__(self, pid):
            self.pid = pid

        def kill(self):
            killed.append(self.pid)

    _bare_start(monkeypatch, [{4100: 1.0}, {4100: 1.0, 4101: 3.0}])
    monkeypatch.setattr(probe.psutil, "Process", _Copy)
    with pytest.raises(RuntimeError, match="#1880"):
        probe.check_bare_start_settles(tmp_path / "exe", tmp_path / "profile", watch_s=5)
    assert killed == [4101]
