#!/usr/bin/env python3
"""Perf capture of the fixed bot-vs-bot replay against the budgets of architecture.md 7.

``run`` launches one rendered game process (D3D12, window off the person's
monitors) that plays ``unreal/Verse/Harness/perf/replay.json``: a seeded duel
seen along a fixed camera path. ``VerseHarness`` starts the CSV profiler after
the warm-up, so shader compiles stay out of the numbers, takes the replay's
screenshot and stops the profiler before it exits. VRAM is sampled through
NVML (``nvidia-smi``), system RAM through the process. The run happens only
in the nightly quiet hours and when nobody used the machine for 5 minutes
(architecture.md 8.2) unless ``--force``.

    python scripts/unreal/perf.py run --profile 1440p
    python scripts/unreal/perf.py compare <a/perf.json> <b/perf.json>   # A10.5: <= 3 %
    python scripts/unreal/perf.py parse <profile.csv>                   # stats of one CSV
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common

PERF_DIR = common.PROJECT_DIR / "Harness" / "perf"
BUDGETS_FILE = PERF_DIR / "budgets.json"
REPLAY_FILE = PERF_DIR / "replay.json"
RUN_TIMEOUT_S = 30 * 60
#: CSV profiler columns, in order of preference.
FRAME_COLUMNS = ("FrameTime",)
GAME_COLUMNS = ("GameThreadTime",)
RENDER_COLUMNS = ("RenderThreadTime",)
GPU_COLUMNS = ("GPUTime", "GPU/Total")
PHYSICS_PREFIXES = ("Physics", "Exclusive/GameThread/Physics", "ChaosPhysics")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- quiet hours ---


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input (Windows); infinity elsewhere."""
    if os.name != "nt":
        return math.inf
    import ctypes

    class LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    info = LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0


def in_window(now: dt.time, start: str, end: str) -> bool:
    lo = dt.time.fromisoformat(start)
    hi = dt.time.fromisoformat(end)
    return lo <= now < hi if lo <= hi else (now >= lo or now < hi)


def quiet_reason(
    quiet: Mapping, now: dt.datetime | None = None, idle: float | None = None
) -> str | None:
    """None when a GPU capture may run now, else why not."""
    now = now or dt.datetime.now()
    if not in_window(now.time(), quiet["start"], quiet["end"]):
        return f"outside the nightly window {quiet['start']}-{quiet['end']}"
    idle = idle_seconds() if idle is None else idle
    if idle < float(quiet["idleMinutes"]) * 60:
        need = quiet["idleMinutes"]
        return f"the person used the machine {idle / 60:.1f} min ago (needs {need} min)"
    return None


# --- CSV and stats ---


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return ordered[lo] if lo == hi else ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _column(rows: Sequence[Mapping[str, str]], names: Sequence[str]) -> list[float]:
    if not rows:
        return []
    for name in names:
        if name in rows[0]:
            return [float(r[name]) for r in rows if _is_number(r.get(name))]
    return []


def _is_number(text: str | None) -> bool:
    try:
        float(text or "")
    except ValueError:
        return False
    return True


def read_csv(path: Path) -> list[dict[str, str]]:
    """Frame rows of an Unreal CSV profile (the trailing metadata rows are dropped)."""
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [r for r in rows if _is_number(r.get("FrameTime"))]


def frame_stats(rows: Sequence[Mapping[str, str]]) -> dict:
    frame = _column(rows, FRAME_COLUMNS)
    game = _column(rows, GAME_COLUMNS)
    physics_cols = [c for c in (rows[0] if rows else {}) if c.startswith(PHYSICS_PREFIXES)]
    physics = (
        [sum(float(r[c]) for c in physics_cols if _is_number(r.get(c))) for r in rows]
        if physics_cols
        else []
    )
    mean_ms = sum(frame) / len(frame) if frame else None
    return {
        "frames": len(frame),
        "fpsAvg": round(1000.0 / mean_ms, 3) if mean_ms else None,
        "frameMsAvg": round(mean_ms, 4) if mean_ms else None,
        "frameMsP99": _r(percentile(frame, 0.99)),
        "gameThreadMsAvg": _r(sum(game) / len(game)) if game else None,
        "gameThreadMsP99": _r(percentile(game, 0.99)),
        "renderThreadMsAvg": _r(_mean(_column(rows, RENDER_COLUMNS))),
        "gpuMsAvg": _r(_mean(_column(rows, GPU_COLUMNS))),
        "physicsMsAvg": _r(_mean(physics)),
    }


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def check_budgets(stats: Mapping, memory: Mapping, budgets: Mapping, profile: str) -> list[dict]:
    target = budgets["profiles"][profile]
    rows = [
        ("fpsAvg", stats.get("fpsAvg"), ">=", target["fpsAvgMin"]),
        ("frameMsP99", stats.get("frameMsP99"), "<=", target["p99FrameMsMax"]),
        ("gameThreadMsAvg", stats.get("gameThreadMsAvg"), "<=", budgets["gameThreadMsMax"]),
        ("physicsMsAvg", stats.get("physicsMsAvg"), "<=", budgets["physicsMsMax"]),
        ("vramMbPeak", memory.get("vramMbPeak"), "<=", budgets["vramVisibleMbMax"]),
        ("ramMbPeak", memory.get("ramMbPeak"), "<=", budgets["systemRamVisibleMbMax"]),
    ]
    out = []
    for name, value, op, limit in rows:
        if value is None:
            out.append({"budget": name, "value": None, "limit": limit, "status": "not_measured"})
            continue
        ok = value >= limit if op == ">=" else value <= limit
        out.append(
            {
                "budget": name,
                "value": value,
                "limit": limit,
                "op": op,
                "status": "pass" if ok else "fail",
            }
        )
    return out


def compare(a: Mapping, b: Mapping, max_rel: float = 0.03) -> dict:
    """A10.5: two runs of the same replay differ by at most ``max_rel`` in fps and p99."""
    out = {"pass": True, "metrics": {}}
    for key in ("fpsAvg", "frameMsP99"):
        va, vb = a["stats"].get(key), b["stats"].get(key)
        if not va or not vb:
            out["metrics"][key] = {"a": va, "b": vb, "relDelta": None}
            out["pass"] = False
            continue
        rel = abs(va - vb) / max(va, vb)
        out["metrics"][key] = {"a": va, "b": vb, "relDelta": round(rel, 5)}
        out["pass"] = out["pass"] and rel <= max_rel
    return out


# --- memory sampling ---


def gpu_memory_used_mb(run: Callable[..., common.Completed] = common.run) -> float | None:
    if not shutil.which("nvidia-smi"):
        return None
    result = run(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture=True
    )
    try:
        return float(result.stdout.strip().splitlines()[0])
    except (IndexError, ValueError):
        return None


def process_ram_mb(pid: int) -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.Process(pid).memory_info().rss / (1024 * 1024)
    except psutil.Error:
        return None


class Sampler(threading.Thread):
    def __init__(self, pid: int, period_s: float = 2.0) -> None:
        super().__init__(daemon=True)
        self.pid = pid
        self.period = period_s
        self.baseline = gpu_memory_used_mb()
        self.vram_peak: float | None = None
        self.ram_peak: float | None = None
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.wait(self.period):
            vram = gpu_memory_used_mb()
            if vram is not None and self.baseline is not None:
                self.vram_peak = max(self.vram_peak or 0.0, vram - self.baseline)
            ram = process_ram_mb(self.pid)
            if ram is not None:
                self.ram_peak = max(self.ram_peak or 0.0, ram)


# --- run ---


def command_for(
    engine: Path, project: Path, replay: Path, profile: Mapping, shots_dir: Path, log: Path
) -> list[str]:
    return [
        str(common.editor_cmd(engine)),
        str(project),
        load_json(replay)["map"],
        "-game",
        "-d3d12",
        "-windowed",
        f"-ResX={profile['resX']}",
        f"-ResY={profile['resY']}",
        "-WinX=-20000",
        "-WinY=-20000",
        "-unattended",
        "-nosound",
        "-NoP4",
        "-csvGpuStats",
        f"-VerseCapture={replay}",
        f"-VerseCaptureOut={shots_dir}",
        "-VersePerf",
        "-ExecCmds=r.VSync 0,t.MaxFPS 0,r.Streaming.PoolSize 3072",
        f"-abslog={log}",
    ]


def newest_csv(project_dir: Path, since: float) -> Path | None:
    folder = project_dir / "Saved" / "Profiling" / "CSV"
    found = (
        [p for p in folder.glob("*.csv") if p.stat().st_mtime >= since] if folder.exists() else []
    )
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def run_once(out_dir: Path, profile_name: str, budgets: Mapping, worktree: Path) -> dict:
    from scripts.unreal import with_lock

    engine, project = common.engine_root(), common.project_file(worktree)
    profile = budgets["profiles"][profile_name]
    out_dir.mkdir(parents=True, exist_ok=True)
    log = out_dir / "perf.log"
    command = command_for(engine, project, REPLAY_FILE, profile, out_dir, log)
    with with_lock.MachineLock("perf", " ".join(command[:3])):
        started = time.time()
        proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        sampler = Sampler(proc.pid)
        sampler.start()
        try:
            code = proc.wait(timeout=RUN_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = proc.wait()
        sampler.stop.set()
        sampler.join(timeout=5)
    csv_path = newest_csv(project.parent, started)
    stats = frame_stats(read_csv(csv_path)) if csv_path else {}
    memory = {"vramMbPeak": _r(sampler.vram_peak), "ramMbPeak": _r(sampler.ram_peak)}
    budget_rows = check_budgets(stats, memory, budgets, profile_name)
    report = {
        "schema": "verse.perf/1",
        "profile": profile_name,
        "returncode": code,
        "csv": str(csv_path) if csv_path else None,
        "stats": stats,
        "memory": memory,
        "budgets": budget_rows,
        "screenshots": sorted(str(p) for p in out_dir.glob("*.png")),
        "pass": code == 0 and bool(stats) and all(r["status"] != "fail" for r in budget_rows),
    }
    (out_dir / "perf.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--profile", default="1440p")
    run_p.add_argument("--runs", type=int, default=1, help="2 also checks run-to-run stability.")
    run_p.add_argument("--force", action="store_true", help="Ignore the quiet hours.")
    run_p.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    cmp_p = sub.add_parser("compare")
    cmp_p.add_argument("a", type=Path)
    cmp_p.add_argument("b", type=Path)
    parse_p = sub.add_parser("parse")
    parse_p.add_argument("csv", type=Path)
    args = parser.parse_args(argv)
    budgets = load_json(BUDGETS_FILE)

    if args.cmd == "parse":
        print(json.dumps(frame_stats(read_csv(args.csv)), indent=2))
        return 0
    if args.cmd == "compare":
        result = compare(load_json(args.a), load_json(args.b), budgets["stabilityMaxRelDelta"])
        print(json.dumps(result, indent=2))
        return 0 if result["pass"] else 1
    reason = None if args.force else quiet_reason(budgets["quietHours"])
    if reason:
        print(f"perf: skipped, {reason}")
        return 0
    base = (
        args.worktree / "unreal" / "Verse" / "Saved" / "Harness" / "perf" / common.run_stamp()
    ).resolve()
    reports = [
        run_once(base / f"run{k}", args.profile, budgets, args.worktree.resolve())
        for k in range(args.runs)
    ]
    ok = all(r["pass"] for r in reports)
    if len(reports) >= 2:
        stability = compare(reports[0], reports[1], budgets["stabilityMaxRelDelta"])
        (base / "stability.json").write_text(json.dumps(stability, indent=2), encoding="utf-8")
        ok = ok and stability["pass"]
    for k, r in enumerate(reports):
        for row in r["budgets"]:
            print(
                f"run{k} {row['status']:12s} {row['budget']} {row['value']} (limit {row['limit']})"
            )
    print(f"perf: {'OK' if ok else 'FAIL'} ({base})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
