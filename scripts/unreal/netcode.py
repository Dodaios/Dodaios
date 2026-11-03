#!/usr/bin/env python3
"""Netcode test: a dedicated server plus two lagged clients (architecture.md 3, 8.3; RK2-RK4).

The editor runs as dedicated server (binary installs cannot build Server
targets) and two ``-game -nullrhi`` clients join it with packet lag 60 ms,
variance 10 ms and 1 % loss. A client autopilot in ``VerseHarness`` moves each
client pawn with seeded input. After the run (2 minutes by default) the logs
are parsed for movement corrections (``p.NetShowCorrections``), the
``[VerseCounter]`` lines (reconcile counters of the combat prediction) and
crashes, and the gates of ``unreal/Verse/Harness/netcode/netcode.json`` apply.

    python scripts/unreal/netcode.py                 # PR / merge-queue smoke, Iris on
    python scripts/unreal/netcode.py --iris both     # nightly: Iris on and off
    python scripts/unreal/netcode.py --parse <run>   # gates from the logs of a finished run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common

CONFIG_FILE = common.PROJECT_DIR / "Harness" / "netcode" / "netcode.json"
CLIENT_CORRECTION = re.compile(r"\*\*\* Client: Error for")
SERVER_CORRECTION = re.compile(r"\*\*\* Server: Error for")
JOIN = re.compile(r"Join succeeded")
COUNTER = re.compile(r"\[VerseCounter\]\s+([A-Za-z0-9_.]+)=(-?\d+(?:\.\d+)?)")
READY = "[VerseNet] server ready"
LOG_FAILURES = (
    re.compile(r"Fatal error"),
    re.compile(r"Ensure condition failed"),
    re.compile(r"Unhandled Exception"),
    re.compile(r"=== Critical error: ==="),
)
STARTUP_TIMEOUT_S = 300


def load_config(path: Path = CONFIG_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def emulation_cmds(net: dict) -> str:
    return ",".join(
        [
            f"Net PktLag={net['PktLag']}",
            f"Net PktLagVariance={net['PktLagVariance']}",
            f"Net PktLoss={net['PktLoss']}",
            "p.NetShowCorrections 1",
        ]
    )


def server_command(
    engine: Path, project: Path, cfg: dict, log: Path, duration: int, iris: bool
) -> list[str]:
    return [
        str(common.editor_cmd(engine)),
        str(project),
        f"{cfg['map']}?listen",
        "-server",
        "-nullrhi",
        "-nosound",
        "-unattended",
        "-NoP4",
        f"-port={cfg['port']}",
        f"-VerseNetDuration={duration}",
        f"-UseIrisReplication={1 if iris else 0}",
        "-ExecCmds=p.NetShowCorrections 1",
        f"-abslog={log}",
    ]


def client_command(
    engine: Path, project: Path, cfg: dict, log: Path, duration: int, iris: bool, seed: int
) -> list[str]:
    return [
        str(common.editor_cmd(engine)),
        str(project),
        f"127.0.0.1:{cfg['port']}",
        "-game",
        "-nullrhi",
        "-nosound",
        "-unattended",
        "-NoP4",
        "-windowed",
        f"-VerseNetAutopilot={seed}",
        f"-VerseNetDuration={duration + 15}",
        f"-UseIrisReplication={1 if iris else 0}",
        f"-ExecCmds={emulation_cmds(cfg['netEmulation'])}",
        f"-abslog={log}",
    ]


def parse_log(text: str) -> dict:
    counters: dict[str, float] = {}
    for name, value in COUNTER.findall(text):
        counters[name] = counters.get(name, 0.0) + float(value)
    return {
        "clientCorrections": len(CLIENT_CORRECTION.findall(text)),
        "serverCorrections": len(SERVER_CORRECTION.findall(text)),
        "joins": len(JOIN.findall(text)),
        "counters": counters,
        "failures": [p.pattern for p in LOG_FAILURES if p.search(text)],
    }


def evaluate(server: dict, clients: Sequence[dict], duration_s: float, gates: dict) -> dict:
    minutes = max(duration_s / 60.0, 1e-9)
    corrections = sum(c["clientCorrections"] for c in clients)
    per_client_minute = corrections / max(len(clients), 1) / minutes
    reconcile_failures = sum(
        c["counters"].get("reconcileFailures", 0.0) for c in [server, *clients]
    )
    failures = [f for part in [server, *clients] for f in part["failures"]]
    checks = [
        (
            f"clients joined {server['joins']} >= {gates['clientsConnectedMin']}",
            server["joins"] >= gates["clientsConnectedMin"],
        ),
        (
            f"corrections per client minute {per_client_minute:.2f} "
            f"<= {gates['correctionsPerClientMinuteMax']}",
            per_client_minute <= gates["correctionsPerClientMinuteMax"],
        ),
        (
            f"reconcile failures {reconcile_failures:.0f} <= {gates['reconcileFailuresMax']}",
            reconcile_failures <= gates["reconcileFailuresMax"],
        ),
        (f"no fatal, ensure or crash ({len(failures)} found)", not failures),
    ]
    return {
        "pass": all(ok for _, ok in checks),
        "checks": [{"check": text, "ok": ok} for text, ok in checks],
        "correctionsPerClientMinute": round(per_client_minute, 3),
        "serverCorrections": server["serverCorrections"],
        "reconcile": {
            k: v
            for part in [server, *clients]
            for k, v in part["counters"].items()
            if "econcile" in k
        },
    }


def parse_run(run_dir: Path, cfg: dict, duration: float) -> dict:
    out = {}
    for variant in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        server = parse_log(_read(variant / "server.log"))
        clients = [parse_log(_read(p)) for p in sorted(variant.glob("client*.log"))]
        out[variant.name] = evaluate(server, clients, duration, cfg["gates"])
    return out


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _wait_ready(
    log: Path, proc: subprocess.Popen, timeout_s: float, sleep: Callable[[float], None] = time.sleep
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        if READY in _read(log):
            return True
        sleep(2.0)
    return False


def run_variant(
    variant_dir: Path,
    cfg: dict,
    duration: int,
    iris: bool,
    engine: Path,
    project: Path,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> None:
    variant_dir.mkdir(parents=True, exist_ok=True)
    server_log = variant_dir / "server.log"
    procs = [
        popen(
            server_command(engine, project, cfg, server_log, duration, iris),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    ]
    try:
        if not _wait_ready(server_log, procs[0], STARTUP_TIMEOUT_S):
            common.log("netcode: the server did not report ready; parsing what it logged")
            return
        for k in range(int(cfg["clients"])):
            log = variant_dir / f"client{k}.log"
            procs.append(
                popen(
                    client_command(engine, project, cfg, log, duration, iris, 1000 + k),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        limit = duration + STARTUP_TIMEOUT_S
        for proc in procs:
            try:
                proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--duration", type=int, help="Seconds of play (default from netcode.json).")
    parser.add_argument("--iris", choices=("on", "off", "both"), default="on")
    parser.add_argument("--parse", type=Path, help="Evaluate a finished run folder; no run.")
    parser.add_argument("--map", help="Map override (default: netcode.json, the hangar).")
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.map:
        cfg["map"] = args.map
    duration = args.duration or int(cfg["durationS"])
    if args.parse:
        run_dir = args.parse.resolve()
    else:
        from scripts.unreal import with_lock

        run_dir = (
            args.worktree
            / "unreal"
            / "Verse"
            / "Saved"
            / "Harness"
            / "netcode"
            / common.run_stamp()
        ).resolve()
        variants = {"on": [True], "off": [False], "both": [True, False]}[args.iris]
        engine, project = common.engine_root(), common.project_file(args.worktree.resolve())
        with with_lock.MachineLock("netcode", f"netcode.py --iris {args.iris}"):
            for iris in variants:
                run_variant(
                    run_dir / f"iris-{'on' if iris else 'off'}",
                    cfg,
                    duration,
                    iris,
                    engine,
                    project,
                )
    result = parse_run(run_dir, cfg, duration)
    report = {
        "schema": "verse.netcode_report/1",
        "run": run_dir.name,
        "durationS": duration,
        "variants": result,
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    ok = bool(result) and all(v["pass"] for v in result.values())
    for name, verdict in result.items():
        for check in verdict["checks"]:
            print(f"{name}: {'OK  ' if check['ok'] else 'FAIL'} {check['check']}")
    print(f"netcode: {'OK' if ok else 'FAIL'} ({run_dir / 'report.json'})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
