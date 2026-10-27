"""A stand-in for the ``openclaw`` CLI, for Gateway supervision tests.

Run as ``python tests/fakes/fake_openclaw.py <args>``. Understands:

* ``--version`` — prints ``OpenClaw 2026.9.8 (fake)``;
* ``gateway run --port N`` — serves ``GET /healthz`` (200) on 127.0.0.1:N
  until killed; exits 1 at once when the port is taken;
* ``doctor --fix ...`` — writes ``doctor.done`` into the working folder.

``FAKE_OPENCLAW_MODE``:

* ``config-once`` — the Gateway exits 78 (``EX_CONFIG``) until doctor ran;
* ``doctor-hang`` — doctor writes its pid to ``doctor.pid`` and sleeps;
* ``schema-stale`` — the Gateway serves ``/healthz`` but logs that its agent
  database "uses schema version 24" (2026.10.8 after an update) until doctor
  ran; doctor counts its runs in ``doctor.runs``;
* ``schema-broken`` — the same, and doctor fails (exit 1) without fixing it;
* ``admission-slow`` — the Gateway logs "has not completed startup inspection
  and preparation" and, ``FAKE_OPENCLAW_ADMISSION_S`` seconds after
  ``/healthz`` answers, that the database recovered.

Every run but ``--version`` appends its argv to ``calls.log`` in the working folder.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server API
        ok = self.path == "/healthz"
        self.send_response(200 if ok else 404)
        self.end_headers()
        self.wfile.write(b"ok" if ok else b"no")

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return


_DB = r"state\agents\main\agent\openclaw-agent.sqlite"
_STALE = (
    f"OpenClaw agent database {_DB} uses schema version 24; stop active agents and run "
    "openclaw doctor --fix to migrate session identities before using it."
)


def _say(line: str) -> None:
    print(line, flush=True)


def main(argv: list[str]) -> int:
    mode = os.environ.get("FAKE_OPENCLAW_MODE", "")
    if argv[:1] == ["--version"]:
        print("OpenClaw 2026.9.8 (fake)")
        return 0
    with Path("calls.log").open("a", encoding="utf-8") as calls:
        calls.write(" ".join(argv) + "\n")
    if argv[:1] == ["doctor"]:
        if mode == "doctor-hang":
            Path("doctor.pid").write_text(str(os.getpid()), encoding="utf-8")
            time.sleep(600)
        runs = Path("doctor.runs")
        count = int(runs.read_text(encoding="utf-8")) if runs.exists() else 0
        runs.write_text(str(count + 1), encoding="utf-8")
        if mode == "schema-broken":
            _say("Doctor could not migrate the agent database: disk is read-only")
            return 1
        _say("Doctor migrated the agent database to schema version 25")
        Path("doctor.done").write_text("1", encoding="utf-8")
        return 0
    if argv[:2] == ["gateway", "run"]:
        if mode == "config-once" and not Path("doctor.done").exists():
            return 78
        port = int(argv[argv.index("--port") + 1])
        try:
            server = HTTPServer(("127.0.0.1", port), _Health)
        except OSError:
            return 1  # EADDRINUSE: the port was taken
        if mode in {"schema-stale", "schema-broken", "admission-slow"}:
            _say(
                "[state/agent-admission] Agent main has not completed startup inspection and "
                "preparation. Inspection and writable admission continue after the Gateway "
                "listener binds."
            )
        if mode in {"schema-stale", "schema-broken"} and not Path("doctor.done").exists():
            _say(
                "2026-10-27T16:22:41.343+01:00 [state/agent-admission] agent database remains "
                f'degraded agentId=main reason="{_STALE}" repairHint="Sessions remain '
                'unavailable."'
            )
        elif mode in {"schema-stale", "admission-slow"}:
            delay = float(os.environ.get("FAKE_OPENCLAW_ADMISSION_S", "0"))

            def recover() -> None:
                time.sleep(delay)
                _say(
                    "2026-10-27T16:54:29.657+01:00 [state/agent-admission] agent database "
                    "recovered after background inspection and preparation"
                )

            threading.Thread(target=recover, daemon=True).start()
        server.serve_forever()
        return 0
    print(f"fake openclaw: unsupported {argv}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
