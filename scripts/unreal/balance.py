#!/usr/bin/env python3
"""Headless bot-vs-bot balance runs and their gates (docs/verse/unreal/contracts/bot.md 10, 11).

The driver plans pairings for the named sets, writes one ``verse.scenario/1``
file per job, runs up to ``--jobs`` headless editors as dedicated servers under
the machine lock (bot.md 11.1, orchestration.md 4), reads the ``verse.bout/1``
lines the ``UVerseBalanceGauntletController`` writes, and turns them into the
``verse.balance/1`` report with the gates BG1-BG12, F1-F7, L1 and BR1.

    python scripts/unreal/balance.py --set ladder --bouts 200 --seed 7 --jobs 4
    python scripts/unreal/balance.py --set ladder --set tricks --tricks spray,camper \\
        --gates BG1,BG2,BG4,BG11 --bouts 40            # the merge-queue subset
    python scripts/unreal/balance.py --set all --patch tiers_patch.json
    python scripts/unreal/balance.py --from-bouts <dir>  # gates from recorded bouts, no run
    python scripts/unreal/balance.py --plan --set all    # print the plan only
    python scripts/unreal/balance.py --speed             # measure x real time, write the bout table

Seeds: every pairing gets ``sha256(run seed, pairing id)``, every match of it
``sha256(pairing seed, match)``. A unit (one match of one pairing) is the
smallest piece of work, so the result is the same for any ``--jobs``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.unreal import _common as common
from scripts.unreal import check_bot_isolation

HARNESS_DIR = common.PROJECT_DIR / "Harness"
SETS_FILE = HARNESS_DIR / "balance" / "sets.json"
BOUT_TABLE_FILE = HARNESS_DIR / "balance" / "bout_table.json"
PERSON_MODELS_FILE = common.PROJECT_DIR / "Data" / "bot" / "person_models.json"
L1_FIELDS_FILE = HARNESS_DIR / "fairness" / "match_memory_fields.json"
SCHEMA_DIR = HARNESS_DIR / "schema"

SET_NAMES = ("ladder", "humans", "tricks", "elite", "cross", "learning", "adaptive", "fairness")
GATE_IDS = (
    "BG1",
    "BG2",
    "BG3",
    "BG4",
    "BG5",
    "BG6",
    "BG7",
    "BG8",
    "BG9",
    "BG10",
    "BG11",
    "BG12",
    "F1",
    "F2",
    "F3",
    "F4",
    "F5",
    "F6",
    "F7",
    "L1",
    "BR1",
)
Z95 = 1.959963984540054
HALF_WIDTH = 0.06
RANGE_BINS = ((0, 5), (5, 10), (10, 20), (20, 35), (35, math.inf))
PROCESS_TIMEOUT_S = 80 * 60
DEFAULT_KILLS_PER_BOUT = 22.0
F5_MIN_WINDOWS = 2000
F5_FACING_DEG = 15.0
F5_MAX_EXCESS = 0.05


# --- statistics ---


def wilson(successes: int, trials: int, z: float = Z95) -> tuple[float, float] | None:
    """Wilson score 95 % interval of a proportion; None without trials."""
    if trials <= 0:
        return None
    p = successes / trials
    denom = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denom
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def trials_for_half_width(p: float, half_width: float = HALF_WIDTH, z: float = Z95) -> int:
    """Trials so the normal 95 % interval at proportion ``p`` is at most +-half_width."""
    p = min(max(p, 0.0), 1.0)
    return max(1, math.ceil(z * z * p * (1 - p) / (half_width * half_width)))


def _ratio(num: float, den: float) -> float | None:
    return None if den <= 0 else num / den


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def stable_seed(*parts: object) -> int:
    text = "\x1f".join(str(p) for p in parts)
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:4], "big")


# --- configuration ---


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(sets_file: Path = SETS_FILE, models_file: Path = PERSON_MODELS_FILE) -> dict:
    cfg = load_json(sets_file)
    models = load_json(models_file)
    cfg["models"] = sorted(models["models"])
    cfg["tricks"] = list(models["tricks"])
    return cfg


def slot_label(slot: Mapping) -> str:
    if slot["kind"] == "bot":
        label = slot["tier"]
        return label if slot.get("learning", True) else f"{label}-nolearn"
    base = slot.get("model") or slot.get("tier")
    trick = slot.get("trick")
    if trick and slot.get("model"):
        return f"{base}+{trick}"
    return trick or base


def _bot(tier: str, learning: bool = True) -> dict:
    slot = {"kind": "bot", "tier": tier}
    if not learning:
        slot["learning"] = False
    return slot


def _model(model: str | None = None, trick: str | None = None, tier: str | None = None) -> dict:
    slot: dict = {"kind": "model"}
    if model:
        slot["model"] = model
    if tier:
        slot["tier"] = tier
    if trick:
        slot["trick"] = trick
    return slot


@dataclass
class Pairing:
    id: str
    set: str
    a: dict
    b: dict
    matches: int | None = None
    bouts_per_match: int | None = None
    match_time_limit_s: float | None = None
    scenario: str | None = None
    same_process: bool = False

    def to_json(self) -> dict:
        return {"id": self.id, "set": self.set, "a": self.a, "b": self.b}


def _pair(set_name: str, a: dict, b: dict, suffix: str = "", **kw) -> Pairing:
    return Pairing(f"{slot_label(a)}_vs_{slot_label(b)}{suffix}", set_name, a, b, **kw)


def build_pairings(
    sets: Iterable[str], cfg: Mapping, tricks: Sequence[str] | None = None
) -> list[Pairing]:
    """Pairings of the named sets in a fixed order, no duplicates (A is the side under test)."""
    names = list(SET_NAMES) if "all" in sets else [s for s in SET_NAMES if s in sets]
    trick_ids = [t for t in cfg["tricks"] if not tricks or t in tricks]
    tiers = cfg["tiers"]
    out: list[Pairing] = []
    for name in names:
        if name == "ladder":
            out += [
                _pair(name, _bot("hard"), _bot("normal")),
                _pair(name, _bot("elite"), _bot("hard")),
                _pair(name, _bot("elite"), _bot("normal")),
            ]
            out += [_pair(name, _bot(t), _bot(t)) for t in tiers]
        elif name == "humans":
            out += [
                _pair(name, _model("skilled"), _bot("elite")),
                _pair(name, _model("skilled"), _bot("normal")),
                _pair(name, _model("average"), _bot("normal")),
            ]
        elif name == "tricks":
            out += [_pair(name, _model(tier="hard", trick=t), _bot("hard")) for t in trick_ids]
        elif name == "elite":
            out.append(_pair(name, _model("skilled"), _bot("elite")))
            out += [_pair(name, _model("skilled", trick=t), _bot("elite")) for t in trick_ids]
        elif name == "cross":
            sides = [_bot(t) for t in tiers] + [_model(m) for m in cfg["models"]]
            out += [
                _pair(name, a, b) for a in sides for b in sides if slot_label(a) != slot_label(b)
            ]
        elif name == "learning":
            learn = cfg["learning"]
            for opp in learn["opponents"]:
                out.append(_pair(name, _bot(learn["bot"]), _model(tier="hard", trick=opp)))
                out.append(
                    _pair(name, _bot(learn["bot"], learning=False), _model(tier="hard", trick=opp))
                )
            reset = cfg["reset"]
            out.append(
                _pair(
                    name,
                    _bot(reset["bot"]),
                    _model(tier="hard", trick=reset["opponent"]),
                    ".reset",
                    matches=2,
                    same_process=True,
                )
            )
        elif name == "adaptive":
            out += [_pair(name, _bot("adaptive"), _model(m)) for m in cfg["adaptive"]["opponents"]]
        elif name == "fairness":
            out.append(
                _pair(
                    name,
                    _bot("hard"),
                    _model(tier="hard", trick="repeek"),
                    ".l1",
                    matches=1,
                    bouts_per_match=3,
                    same_process=True,
                )
            )
            for scen in sorted(cfg.get("scenarios", {})):
                script = load_json(HARNESS_DIR / "balance" / cfg["scenarios"][scen])
                out.append(
                    Pairing(
                        scen,
                        name,
                        script["a"],
                        script["b"],
                        matches=1,
                        bouts_per_match=1,
                        match_time_limit_s=float(script["durationS"]),
                        scenario=scen,
                    )
                )
    seen: set[str] = set()
    unique = []
    for p in out:
        if p.id not in seen:
            seen.add(p.id)
            unique.append(p)
    return unique


# --- planning ---


@dataclass
class Unit:
    pairing: Pairing
    match: int
    seed: int
    bouts: int

    def to_json(self, cfg: Mapping, patch: Mapping | None) -> dict:
        unit = {
            "pairing": self.pairing.id,
            "set": self.pairing.set,
            "match": self.match,
            "seed": self.seed,
            "bouts": self.bouts,
            "a": self.pairing.a,
            "b": self.pairing.b,
            "killsToWin": int(cfg.get("killsToWin", 15)),
            "matchTimeLimitS": float(
                self.pairing.match_time_limit_s or cfg.get("matchTimeLimitS", 600)
            ),
        }
        if self.pairing.scenario:
            unit["scenario"] = self.pairing.scenario
        if patch:
            unit["tierPatch"] = dict(patch)
        return unit


def plan_units(
    pairings: Sequence[Pairing], bouts: int, run_seed: int, bouts_per_match: int
) -> list[Unit]:
    units: list[Unit] = []
    for p in pairings:
        per_match = p.bouts_per_match or bouts_per_match
        matches = p.matches or max(1, math.ceil(bouts / per_match))
        pseed = stable_seed(run_seed, p.id)
        left = bouts if p.matches is None and p.bouts_per_match is None else per_match * matches
        for m in range(matches):
            n = per_match if p.matches or p.bouts_per_match else min(per_match, left)
            left -= n
            if n > 0:
                units.append(Unit(p, m, stable_seed(pseed, m), n))
    return units


def shard_units(units: Sequence[Unit], jobs: int) -> list[list[Unit]]:
    """Units over ``jobs`` processes by bout count, keeping same-process pairings together."""
    jobs = max(1, min(jobs, common.MAX_HEADLESS_JOBS))
    groups: list[list[Unit]] = []
    index: dict[str, int] = {}
    for u in units:
        if u.pairing.same_process:
            if u.pairing.id not in index:
                index[u.pairing.id] = len(groups)
                groups.append([])
            groups[index[u.pairing.id]].append(u)
        else:
            groups.append([u])
    shards: list[list[Unit]] = [[] for _ in range(jobs)]
    load = [0] * jobs
    for group in sorted(groups, key=lambda g: -sum(u.bouts for u in g)):
        k = min(range(jobs), key=lambda i: (load[i], i))
        shards[k].extend(group)
        load[k] += sum(u.bouts for u in group)
    for shard in shards:
        shard.sort(key=lambda u: (u.pairing.id, u.match))
    return [s for s in shards if s]


def scenario_document(
    run: str,
    job: int,
    units: Sequence[Unit],
    cfg: Mapping,
    out_dir: Path,
    patch: Mapping | None,
    trace_bearing: bool,
) -> dict:
    return {
        "schema": "verse.scenario/1",
        "run": run,
        "job": job,
        "map": cfg["map"],
        "output": str(out_dir),
        "maxWallS": PROCESS_TIMEOUT_S - 60,
        "trace": {"bearing": trace_bearing, "fireAudit": True},
        "units": [u.to_json(cfg, patch) for u in units],
    }


def command_for(
    engine: Path, project: Path, map_path: str, scenario: Path, log_path: Path
) -> list[str]:
    """The dedicated-server command of bot.md 11.1."""
    return [
        str(common.editor_cmd(engine)),
        str(project),
        map_path,
        "-server",
        "-nullrhi",
        "-nosound",
        "-unattended",
        "-benchmark",
        "-fps=60",
        f"-VerseHarness={scenario}",
        "-NoP4",
        "-nosplash",
        "-stdout",
        "-FullStdOutLogOutput",
        f"-abslog={log_path}",
    ]


# --- reading results ---


def read_bouts(root: Path) -> list[dict]:
    bouts: list[dict] = []
    for path in sorted(root.rglob("bouts.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                bouts.append(json.loads(line))
    return bouts


FIRE_AUDIT_TAG = "[VerseFireAudit]"


def parse_fire_audit(text: str) -> dict[tuple[str, int, int, str], dict[str, int]]:
    """Counts per (pairing, match, bout, side) and mode from ``[VerseFireAudit]`` log lines.

    Line format (written by VerseBot for each bot shot, bot.md frozen interface):
    ``[VerseFireAudit] pairing=<id> match=<m> bout=<n> side=<A|B> mode=<mode> ...`` with mode
    one of Visible, Suppression, Prefire, WallShot.
    """
    counts: dict[tuple[str, int, int, str], dict[str, int]] = {}
    for line in text.splitlines():
        at = line.find(FIRE_AUDIT_TAG)
        if at < 0:
            continue
        fields = dict(
            part.split("=", 1) for part in line[at + len(FIRE_AUDIT_TAG) :].split() if "=" in part
        )
        try:
            key = (fields["pairing"], int(fields["match"]), int(fields["bout"]), fields["side"])
        except (KeyError, ValueError):
            continue
        mode = fields.get("mode", "Unclassified")
        bucket = counts.setdefault(key, {})
        bucket[mode] = bucket.get(mode, 0) + 1
    return counts


def merge_fire_audit(
    bouts: list[dict], audit: Mapping[tuple[str, int, int, str], Mapping[str, int]]
) -> None:
    for bout in bouts:
        for side in ("A", "B"):
            key = (bout["pairing"], bout["match"], bout["bout"], side)
            if key in audit:
                stats = bout[side.lower()]
                merged = dict(stats.get("fireAudit") or {})
                for mode, n in audit[key].items():
                    merged[mode] = merged.get(mode, 0) + n
                stats["fireAudit"] = merged


# --- aggregation ---

AUDIT_MODES = ("Visible", "Suppression", "Prefire", "WallShot")


def _is_bot(slot: Mapping) -> bool:
    return slot.get("kind") == "bot"


def aggregate(
    pairings: Sequence[Pairing],
    bouts: Sequence[dict],
    reset_window_s: float = 300.0,
    kill_window: Sequence[int] = (30, 60),
) -> list[dict]:
    by_pairing: dict[str, list[dict]] = {}
    for b in bouts:
        by_pairing.setdefault(b["pairing"], []).append(b)
    out = []
    for p in pairings:
        rows = sorted(by_pairing.get(p.id, []), key=lambda b: (b["match"], b["bout"]))
        out.append(_pairing_metrics(p, rows, reset_window_s, kill_window))
    return out


def _side_sum(rows: Sequence[dict], side: str, key: str) -> int:
    return sum(int(r[side].get(key) or 0) for r in rows)


def _pairing_metrics(
    p: Pairing, rows: Sequence[dict], reset_window_s: float, kill_window: Sequence[int]
) -> dict:
    n = len(rows)
    wins_a = sum(1 for r in rows if r["winner"] == "A")
    kills = [
        dict(k, match=r["match"], mt=float(r.get("matchTimeStartS", 0.0)) + float(k["t"]))
        for r in rows
        for k in r.get("kills", [])
    ]
    kills_a = sum(1 for k in kills if k["killer"] == "A")
    kills_b = len(kills) - kills_a
    side0 = [r for r in rows if r["winner"] in ("A", "B")]
    side0_wins = sum(1 for r in side0 if (r["winner"] == "A") == (int(r["spawnSideA"]) == 0))
    metrics: dict = {
        "id": p.id,
        "set": p.set,
        "a": p.a,
        "b": p.b,
        "bouts": n,
        "kills": len(kills),
        "boutWinRateA": _ratio(wins_a, n),
        "boutWinRateA95": _interval(wilson(wins_a, n)),
        "killShareA": _ratio(kills_a, len(kills)),
        "killShareA95": _interval(wilson(kills_a, len(kills))),
        "spawnSide0WinRate": _ratio(side0_wins, len(side0)),
        "spawnSide0": [side0_wins, len(side0)],
        "matchTimeS": round(sum(float(r["durationS"]) for r in rows), 3),
    }
    per_side = {"a": kills_a, "b": kills_b}
    deaths = {"a": _side_sum(rows, "a", "deaths"), "b": _side_sum(rows, "b", "deaths")}
    lives = {s: deaths[s] + n for s in ("a", "b")}
    kills_of = {
        "a": [k for k in kills if k["killer"] == "A"],
        "b": [k for k in kills if k["killer"] == "B"],
    }
    metrics["kd"] = {s: _round(_ratio(per_side[s], max(deaths[s], 1))) for s in ("a", "b")}
    metrics["ttkS"] = {
        s: _round(_median([float(k["ttkS"]) for k in kills_of[s] if "ttkS" in k]))
        for s in ("a", "b")
    }
    contact = {
        s: [float(t) for r in rows for t in r[s].get("timeToContactS", [])] for s in ("a", "b")
    }
    metrics["timeToContactS"] = {s: _round(_median(contact[s])) for s in ("a", "b")}
    metrics["timeToContactSamples"] = contact["a"] + contact["b"]
    metrics["accuracy"] = {
        s: _round(_ratio(_side_sum(rows, s, "hits"), _side_sum(rows, s, "shots")))
        for s in ("a", "b")
    }
    for name, pred in (
        ("headshotShare", lambda k: k.get("headshot")),
        ("wallKillShare", lambda k: k.get("wall")),
        ("finisherShare", lambda k: k.get("cause") == "finisher"),
        ("knifeShare", lambda k: k.get("cause") == "melee"),
    ):
        metrics[name] = {
            s: _round(_ratio(sum(1 for k in kills_of[s] if pred(k)), len(kills_of[s])))
            for s in ("a", "b")
        }
    for key in ("bulwarkUses", "breachUses", "reloadsInFight"):
        metrics[key] = {s: _round(_ratio(_side_sum(rows, s, key), lives[s])) for s in ("a", "b")}
    hist = {f"{lo}-{hi}" if hi != math.inf else f"{lo}+": 0 for lo, hi in RANGE_BINS}
    for k in kills:
        if "rangeM" in k:
            r = float(k["rangeM"])
            for (lo, hi), name in zip(RANGE_BINS, hist, strict=True):
                if lo <= r < hi:
                    hist[name] += 1
                    break
    metrics["engagementRangeHist"] = hist
    metrics["spawnKills"] = sum(1 for k in kills if k.get("spawnKill"))
    audit: dict = {}
    for s, slot in (("a", p.a), ("b", p.b)):
        if not _is_bot(slot):
            continue
        modes = {m: 0 for m in AUDIT_MODES}
        shots = _side_sum(rows, s, "shots")
        for r in rows:
            for mode, count in (r[s].get("fireAudit") or {}).items():
                if mode in modes:
                    modes[mode] += int(count)
        modes["Unclassified"] = max(0, shots - sum(modes.values()))
        modes["shots"] = shots
        audit[s] = modes
    metrics["fireAudit"] = audit
    metrics["learningDelta"] = _round(_learning_delta(rows, kills))
    metrics["adaptiveTrace"] = [float(v) for r in rows for v in r.get("adaptiveTrace", [])]
    metrics["killWindowB"] = _kill_window_share(kills, kill_window)
    metrics["resetWindow"] = _reset_window(kills, reset_window_s)
    bot_ms = [r[s].get("botMsP99") for r in rows for s in ("a", "b")]
    bot_ms = [float(v) for v in bot_ms if v is not None]
    metrics["botMsP99"] = max(bot_ms) if bot_ms else None
    metrics["stuckEvents"] = _side_sum(rows, "a", "stuckEvents") + _side_sum(
        rows, "b", "stuckEvents"
    )
    nav = [r[s].get("navFailures") for r in rows for s in ("a", "b")]
    metrics["navFailures"] = (
        sum(int(v) for v in nav if v is not None) if any(v is not None for v in nav) else None
    )
    metrics["shots"] = _side_sum(rows, "a", "shots") + _side_sum(rows, "b", "shots")
    metrics["f7Violations"] = (
        sum(int(r["f7Violations"]) for r in rows)
        if p.scenario and rows and all("f7Violations" in r for r in rows)
        else None
    )
    metrics["bearingWindows"] = [w for r in rows for w in r.get("bearingWindows", [])]
    if p.scenario:
        metrics["scenario"] = p.scenario
        storm = [r["storm"] for r in rows if r.get("storm")]
        if storm:
            metrics["storm"] = storm[-1]
    return metrics


def _interval(ci: tuple[float, float] | None) -> list[float] | None:
    return None if ci is None else [round(ci[0], 6), round(ci[1], 6)]


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(value, digits)


def _learning_delta(rows: Sequence[dict], kills: Sequence[dict]) -> float | None:
    """A's kill share in the second half of each match minus the first half (pooled)."""
    halves = {0: [0, 0], 1: [0, 0]}
    lengths: dict[int, float] = {}
    for r in rows:
        end = float(r.get("matchTimeStartS", 0.0)) + float(r["durationS"])
        lengths[r["match"]] = max(lengths.get(r["match"], 0.0), end)
    for k in kills:
        half = 1 if k["mt"] >= lengths.get(k["match"], 0.0) / 2 else 0
        halves[half][0] += 1 if k["killer"] == "A" else 0
        halves[half][1] += 1
    first, second = (_ratio(*halves[0]), _ratio(*halves[1]))
    if first is None or second is None:
        return None
    return second - first


def _kill_window_share(kills: Sequence[dict], window: Sequence[int]) -> list[int]:
    """[B kills, all kills] over kills ``window[0]+1 .. window[1]`` of each match (BG10)."""
    lo, hi = window
    b = total = 0
    per_match: dict[int, list[dict]] = {}
    for k in kills:
        per_match.setdefault(k["match"], []).append(k)
    for seq in per_match.values():
        seq.sort(key=lambda k: k["mt"])
        for k in seq[lo:hi]:
            total += 1
            b += 1 if k["killer"] == "B" else 0
    return [b, total]


def _reset_window(kills: Sequence[dict], window_s: float) -> dict[str, list[int]]:
    """Per match: [A kills, all kills] in the first ``window_s`` of match time (BG9)."""
    out: dict[str, list[int]] = {}
    for k in kills:
        if k["mt"] < window_s:
            cell = out.setdefault(str(k["match"]), [0, 0])
            cell[0] += 1 if k["killer"] == "A" else 0
            cell[1] += 1
    return out


# --- fairness helpers ---


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def f5_statistic(
    windows: Sequence[Sequence[float]], facing_deg: float = F5_FACING_DEG
) -> float | None:
    """Rate of facing within ``facing_deg`` of the true bearing minus the rate against the decoy."""
    if not windows:
        return None
    true_hits = sum(1 for f, t, _d in windows if _angle_diff(f, t) <= facing_deg)
    decoy_hits = sum(1 for f, _t, d in windows if _angle_diff(f, d) <= facing_deg)
    return (true_hits - decoy_hits) / len(windows)


def l1_scan(
    roots: Iterable[Path], fields: Sequence[str], since: float, bridge_frames: Iterable[str] = ()
) -> list[str]:
    """Files under ``roots`` written since ``since`` or bridge frames that hold match memory."""
    hits: list[str] = []
    needles = [f.encode("utf-8") for f in fields]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            try:
                if not path.is_file() or path.stat().st_mtime < since:
                    continue
                if path.suffix.lower() in (".log", ".jsonl") and path.parent.name in (
                    "Logs",
                    "balance",
                ):
                    # Process logs and the harness' own bout records name fields by design.
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            for needle, name in zip(needles, fields, strict=True):
                if needle in data:
                    hits.append(f"{path}: holds match-memory field {name}")
    for number, frame in enumerate(bridge_frames, 1):
        for name in fields:
            if name in frame:
                hits.append(f"bridge frame {number}: carries match-memory field {name}")
    return hits


# --- gates ---


@dataclass
class Gate:
    id: str
    status: str
    detail: str
    values: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"id": self.id, "status": self.status, "detail": self.detail, "values": self.values}


def _no_combat(m: Mapping | None) -> bool:
    return m is not None and m["bouts"] > 0 and m["kills"] == 0 and m.get("shots", 0) == 0


def _need(metrics: Mapping[str, dict], gate: str, ids: Sequence[str]) -> Gate | None:
    """A not_run or fail gate when a pairing it needs is missing, unplayed or killless."""
    missing = [i for i in ids if i not in metrics or metrics[i]["bouts"] == 0]
    if missing:
        return Gate(gate, "not_run", "pairings not played: " + ", ".join(missing))
    idle = [i for i in ids if _no_combat(metrics[i])]
    if idle:
        return Gate(
            gate, "not_run", "no shots fired (null brain until WP08 lands): " + ", ".join(idle)
        )
    killless = [i for i in ids if metrics[i]["kills"] == 0]
    if killless:
        return Gate(gate, "fail", "no kills in: " + ", ".join(killless))
    return None


def _verdict(gate: str, checks: Sequence[tuple[str, bool]], values: dict) -> Gate:
    failed = [text for text, ok in checks if not ok]
    if failed:
        return Gate(gate, "fail", "; ".join(failed), values)
    return Gate(gate, "pass", "; ".join(text for text, _ in checks), values)


def _fmt(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def gate_ladder(metrics: Mapping[str, dict], gate: str, pid: str) -> Gate:
    blocked = _need(metrics, gate, [pid])
    if blocked:
        return blocked
    m = metrics[pid]
    wr, lo = m["boutWinRateA"], m["killShareA95"][0]
    return _verdict(
        gate,
        [
            (f"{pid} boutWinRateA {_fmt(wr)} >= 0.75", wr >= 0.75),
            (f"{pid} killShareA lower {_fmt(lo)} >= 0.56", lo >= 0.56),
        ],
        {"boutWinRateA": wr, "killShareLower": lo},
    )


def gate_bg3(metrics: Mapping[str, dict], tiers: Sequence[str]) -> Gate:
    blocked = _need(metrics, "BG3", ["elite_vs_normal"])
    if blocked:
        return blocked
    m = metrics["elite_vs_normal"]
    checks = [
        (
            f"elite_vs_normal boutWinRateA {_fmt(m['boutWinRateA'])} >= 0.90",
            m["boutWinRateA"] >= 0.90,
        ),
        (f"elite_vs_normal killShareA {_fmt(m['killShareA'])} <= 0.85", m["killShareA"] <= 0.85),
    ]
    side0 = [0, 0]
    for t in tiers:
        pid = f"{t}_vs_{t}"
        mm = metrics.get(pid)
        if not mm or mm["bouts"] == 0 or mm["kills"] == 0:
            checks.append((f"mirror {pid} not played", False))
            continue
        ks = mm["killShareA"]
        checks.append(
            (f"mirror {pid} killShareA {_fmt(ks)} in 0.5 +- 0.06", abs(ks - 0.5) <= HALF_WIDTH)
        )
        side0[0] += mm["spawnSide0"][0]
        side0[1] += mm["spawnSide0"][1]
    rate = _ratio(*side0)
    checks.append(
        (
            f"spawn side 0 win rate {_fmt(rate)} in 0.5 +- 0.06",
            rate is not None and abs(rate - 0.5) <= HALF_WIDTH,
        )
    )
    return _verdict("BG3", checks, {"spawnSide0WinRate": rate})


def gate_bg4(metrics: Mapping[str, dict], tricks: Sequence[str]) -> Gate:
    ids = [f"{t}_vs_hard" for t in tricks if f"{t}_vs_hard" in metrics]
    if not ids:
        return Gate("BG4", "not_run", "no trick pairings played")
    blocked = _need(metrics, "BG4", ids)
    if blocked:
        return blocked
    checks = []
    for pid in ids:
        m = metrics[pid]
        checks.append(
            (f"{pid} boutWinRateA {_fmt(m['boutWinRateA'])} <= 0.50", m["boutWinRateA"] <= 0.50)
        )
        checks.append(
            (
                f"{pid} killShareA upper {_fmt(m['killShareA95'][1])} <= 0.55",
                m["killShareA95"][1] <= 0.55,
            )
        )
    return _verdict("BG4", checks, {"tricks": len(ids)})


def gate_bg5(metrics: Mapping[str, dict], tricks: Sequence[str]) -> Gate:
    ids = [f"skilled+{t}_vs_elite" for t in tricks if f"skilled+{t}_vs_elite" in metrics]
    if not ids:
        return Gate("BG5", "not_run", "no skilled+trick pairings played")
    blocked = _need(metrics, "BG5", ["skilled_vs_elite", *ids])
    if blocked:
        return blocked
    base = metrics["skilled_vs_elite"]["killShareA"]
    checks = [
        (
            f"{pid} killShareA {_fmt(metrics[pid]['killShareA'])} <= {_fmt(base)} + 0.05",
            metrics[pid]["killShareA"] <= base + 0.05,
        )
        for pid in ids
    ]
    return _verdict("BG5", checks, {"baseKillShare": base})


def gate_bg6(metrics: Mapping[str, dict]) -> Gate:
    blocked = _need(metrics, "BG6", ["skilled_vs_elite", "skilled_vs_normal"])
    if blocked:
        return blocked
    ks_e = metrics["skilled_vs_elite"]["killShareA"]
    ks_n = metrics["skilled_vs_normal"]["killShareA"]
    return _verdict(
        "BG6",
        [
            (
                f"skilled_vs_elite killShareA {_fmt(ks_e)} in 0.40 +- 0.06",
                abs(ks_e - 0.40) <= HALF_WIDTH + 1e-12,
            ),
            (f"skilled_vs_normal killShareA {_fmt(ks_n)} >= 0.70", ks_n >= 0.70),
        ],
        {"skilledVsElite": ks_e, "skilledVsNormal": ks_n},
    )


def gate_bg7(metrics: Mapping[str, dict]) -> Gate:
    blocked = _need(metrics, "BG7", ["average_vs_normal"])
    if blocked:
        return blocked
    ks = metrics["average_vs_normal"]["killShareA"]
    return _verdict(
        "BG7",
        [(f"average_vs_normal killShareA {_fmt(ks)} in 0.45-0.65", 0.45 <= ks <= 0.65)],
        {"killShareA": ks},
    )


def gate_bg8(metrics: Mapping[str, dict], cfg: Mapping) -> Gate:
    bot = cfg["learning"]["bot"]
    on = [f"{bot}_vs_{o}" for o in cfg["learning"]["opponents"]]
    off = [f"{bot}-nolearn_vs_{o}" for o in cfg["learning"]["opponents"]]
    blocked = _need(metrics, "BG8", on + off)
    if blocked:
        return blocked
    checks = []
    for a, b in zip(on, off, strict=True):
        delta = metrics[a]["learningDelta"]
        checks.append(
            (f"{a} learningDelta {_fmt(delta)} >= +0.05", delta is not None and delta >= 0.05)
        )
        gap = metrics[a]["killShareA"] - metrics[b]["killShareA"]
        checks.append((f"{b} is {_fmt(gap)} worse for the bot (>= 0.03)", gap >= 0.03))
    return _verdict("BG8", checks, {})


def gate_bg9(metrics: Mapping[str, dict], cfg: Mapping) -> Gate:
    pid = f"{cfg['reset']['bot']}_vs_{cfg['reset']['opponent']}.reset"
    blocked = _need(metrics, "BG9", [pid])
    if blocked:
        return blocked
    window = metrics[pid]["resetWindow"]
    first, second = window.get("0"), window.get("1")
    if not first or not second or not first[1] or not second[1]:
        return Gate(
            "BG9",
            "fail",
            f"{pid}: both matches need kills in the first {cfg['reset']['windowS']} s",
        )
    ci = wilson(first[0], first[1])
    p2 = second[0] / second[1]
    return _verdict(
        "BG9",
        [
            (
                f"match 2 share {_fmt(p2)} inside match 1 interval [{_fmt(ci[0])}, {_fmt(ci[1])}]",
                ci[0] <= p2 <= ci[1],
            )
        ],
        {"match1": first, "match2": second},
    )


def gate_bg10(metrics: Mapping[str, dict], cfg: Mapping) -> Gate:
    ids = [f"adaptive_vs_{o}" for o in cfg["adaptive"]["opponents"]]
    blocked = _need(metrics, "BG10", ids)
    if blocked:
        return blocked
    checks = []
    lo, hi = cfg["adaptive"]["killWindow"]
    for pid in ids:
        b, total = metrics[pid]["killWindowB"]
        share = _ratio(b, total)
        checks.append(
            (
                f"{pid} person kill share over kills {lo}-{hi} {_fmt(share)} in 0.40-0.60",
                share is not None and 0.40 <= share <= 0.60,
            )
        )
        trace = metrics[pid]["adaptiveTrace"]
        if not trace:
            checks.append((f"{pid} has no adaptive trace", False))
            continue
        checks.append((f"{pid} s within [0, 1]", all(0.0 <= s <= 1.0 for s in trace)))
        step = max((abs(b2 - a2) for a2, b2 in zip(trace, trace[1:], strict=False)), default=0.0)
        checks.append((f"{pid} largest step {_fmt(step)} <= 0.05", step <= 0.05 + 1e-12))
    return _verdict("BG10", checks, {})


def gate_f4(metrics: Mapping[str, dict]) -> Gate:
    played = [m for m in metrics.values() if m["bouts"]]
    if not played:
        return Gate("F4", "not_run", "no bouts played")
    unclassified = sum(a.get("Unclassified", 0) for m in played for a in m["fireAudit"].values())
    shots = sum(a.get("shots", 0) for m in played for a in m["fireAudit"].values())
    return _verdict(
        "F4",
        [(f"unclassified bot shots {unclassified} of {shots} == 0", unclassified == 0)],
        {"botShots": shots, "unclassified": unclassified},
    )


def gate_f5(metrics: Mapping[str, dict]) -> Gate:
    windows = [w for m in metrics.values() for w in m.get("bearingWindows", [])]
    if len(windows) < F5_MIN_WINDOWS:
        return Gate(
            "F5", "not_run", f"{len(windows)} no-percept windows, need {F5_MIN_WINDOWS} (nightly)"
        )
    stat = f5_statistic(windows)
    return _verdict(
        "F5",
        [(f"hidden-bearing excess {_fmt(stat)} <= {F5_MAX_EXCESS}", stat <= F5_MAX_EXCESS)],
        {"windows": len(windows), "excess": stat},
    )


def gate_f7(metrics: Mapping[str, dict]) -> Gate:
    m = metrics.get("wall_opened_unseen")
    if not m or not m["bouts"]:
        return Gate("F7", "not_run", "scenario wall_opened_unseen not played")
    if m["f7Violations"] is None:
        return Gate(
            "F7", "not_run", "wall_opened_unseen ran without a plan watch (needs WP06, WP08)"
        )
    return _verdict(
        "F7",
        [(f"plans through the unseen opening: {m['f7Violations']}", m["f7Violations"] == 0)],
        {},
    )


def gate_bg12(metrics: Mapping[str, dict]) -> Gate:
    played = [m for m in metrics.values() if m["bouts"]]
    if not played:
        return Gate("BG12", "not_run", "no bouts played")
    if all(_no_combat(m) for m in played) and not any(m["timeToContactSamples"] for m in played):
        return Gate("BG12", "not_run", "no contact in any bout (null brain until WP08 lands)")
    contact = [t for m in played for t in m["timeToContactSamples"]]
    median = _median(contact)
    minutes = sum(m["matchTimeS"] for m in played) / 60.0
    stuck = sum(m["stuckEvents"] for m in played)
    per_10 = stuck / (minutes / 10.0) if minutes > 0 else 0.0
    bot_ms = [m["botMsP99"] for m in played if m["botMsP99"] is not None]
    checks = [
        (f"timeToContactS median {_fmt(median)} <= 25", median is not None and median <= 25.0),
        (f"stuckEvents {per_10:.3f} per 10 min <= 1", per_10 <= 1.0),
    ]
    if bot_ms:
        checks.append((f"botMsP99 {_fmt(max(bot_ms))} <= 0.5", max(bot_ms) <= 0.5))
    else:
        checks.append(("botMsP99 not measured (needs VerseBot timing)", True))
    return _verdict("BG12", checks, {"contactMedianS": median, "stuckPer10Min": per_10})


def gate_static(gate: str, findings: Sequence[str], what: str) -> Gate:
    if findings:
        return Gate(
            gate, "fail", f"{what}: " + "; ".join(findings[:10]), {"findings": len(findings)}
        )
    return Gate(gate, "pass", f"{what}: clean")


def gate_external(gate: str, checks: Mapping[str, Mapping], what: str) -> Gate:
    """A gate whose verdict comes from another test run (``--checks`` file)."""
    entry = checks.get(gate)
    if not entry:
        return Gate(gate, "not_run", f"{what}: no result supplied")
    return Gate(gate, entry.get("status", "not_run"), entry.get("detail", what))


def gate_bg11(parts: Mapping[str, Gate], nightly: bool) -> Gate:
    want = ["F3", "F4"] + (["F5", "F7", "L1"] if nightly else [])
    states = {g: parts[g].status for g in want if g in parts}
    failed = [g for g, s in states.items() if s == "fail"]
    if failed:
        return Gate("BG11", "fail", "failed: " + ", ".join(failed), states)
    if all(s == "not_run" for s in states.values()):
        return Gate("BG11", "not_run", "no fairness test ran", states)
    not_run = [g for g, s in states.items() if s == "not_run"]
    detail = "passed: " + ", ".join(g for g, s in states.items() if s == "pass")
    if not_run:
        detail += "; not run (listed, not silent): " + ", ".join(not_run)
    return Gate("BG11", "pass", detail, states)


def evaluate_gates(
    metrics_list: Sequence[dict],
    cfg: Mapping,
    *,
    checks: Mapping[str, Mapping] | None = None,
    l1_findings: Sequence[str] | None = None,
    nightly: bool = False,
    static_root: Path | None = None,
    only: Iterable[str] | None = None,
) -> list[Gate]:
    metrics = {m["id"]: m for m in metrics_list}
    checks = checks or {}
    source = static_root or (common.PROJECT_DIR / "Source")
    gates: dict[str, Gate] = {
        "BG1": gate_ladder(metrics, "BG1", "hard_vs_normal"),
        "BG2": gate_ladder(metrics, "BG2", "elite_vs_hard"),
        "BG3": gate_bg3(metrics, cfg["tiers"]),
        "BG4": gate_bg4(metrics, cfg["tricks"]),
        "BG5": gate_bg5(metrics, cfg["tricks"]),
        "BG6": gate_bg6(metrics),
        "BG7": gate_bg7(metrics),
        "BG8": gate_bg8(metrics, cfg),
        "BG9": gate_bg9(metrics, cfg),
        "BG10": gate_bg10(metrics, cfg),
        "F1": gate_static("F1", check_bot_isolation.check_isolation(source), "bot isolation"),
        "F2": gate_external("F2", checks, "percept boundary automation tests"),
        "F3": gate_external("F3", checks, "counterfactual invariance automation test"),
        "F4": gate_f4(metrics),
        "F5": gate_f5(metrics),
        "F6": gate_static("F6", check_bot_isolation.check_symmetry(source), "perception symmetry"),
        "F7": gate_f7(metrics),
        "BR1": gate_external("BR1", checks, "brain replay unit test"),
        "BG12": gate_bg12(metrics),
    }
    if l1_findings is None:
        gates["L1"] = gate_external("L1", checks, "no-persistence scan")
    else:
        gates["L1"] = gate_static("L1", l1_findings, "no-persistence scan")
    gates["BG11"] = gate_bg11(gates, nightly)
    wanted = list(only) if only else list(GATE_IDS)
    return [gates[g] for g in GATE_IDS if g in wanted]


# --- report ---


def build_report(
    run: str,
    seed: int,
    sets: Sequence[str],
    metrics: Sequence[dict],
    gates: Sequence[Gate],
    *,
    bouts: int | None,
    jobs: int,
    patch: Mapping | None,
    speed: Mapping | None,
    fire_audit_log: str | None = None,
) -> dict:
    return {
        "schema": "verse.balance/1",
        "run": run,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": seed,
        "sets": list(sets),
        "bouts": bouts,
        "jobs": jobs,
        "patch": dict(patch) if patch else None,
        "speed": dict(speed) if speed else None,
        "pairings": list(metrics),
        "gates": [g.to_json() for g in gates],
        "fireAuditLog": fire_audit_log,
    }


def validate(document: Mapping, schema_name: str) -> list[str]:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - CI installs it
        return []
    schema = load_json(SCHEMA_DIR / schema_name)
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"{'/'.join(str(p) for p in e.absolute_path)}: {e.message}"
        for e in validator.iter_errors(document)
    ]


# --- speed and bout table (RK1) ---


def speed_summary(speed_docs: Sequence[Mapping]) -> dict | None:
    docs = [d for d in speed_docs if float(d.get("wallS", 0)) > 0]
    if not docs:
        return None
    per_process = [float(d["simS"]) / float(d["wallS"]) for d in docs]
    ram = [float(d["peakRamMb"]) for d in docs if d.get("peakRamMb")]
    return {
        "processes": len(docs),
        "xRealTimePerProcess": round(min(per_process), 3),
        "xRealTimeMean": round(statistics.mean(per_process), 3),
        "simS": round(sum(float(d["simS"]) for d in docs), 3),
        "wallS": round(max(float(d["wallS"]) for d in docs), 3),
        "startupS": round(max(float(d.get("startupS", 0.0)) for d in docs), 3),
        "peakRamMbPerProcess": round(max(ram), 1) if ram else None,
        "targetXRealTime": 20.0,
        "meetsTarget": min(per_process) >= 20.0,
    }


#: The proportion at each gate's decision threshold, and whether its trials are bouts or kills.
GATE_TRIALS = {
    "BG1": (0.75, "bouts"),
    "BG2": (0.75, "bouts"),
    "BG3": (0.90, "bouts"),
    "BG4": (0.50, "bouts"),
    "BG5": (0.45, "kills"),
    "BG6": (0.40, "kills"),
    "BG7": (0.55, "kills"),
    "BG8": (0.50, "kills"),
    "BG9": (0.50, "kills"),
    "BG10": (0.50, "kills"),
}


def bout_table(
    speed: Mapping,
    *,
    kills_per_bout: float = DEFAULT_KILLS_PER_BOUT,
    bout_sim_s: float = 240.0,
    jobs: int = common.MAX_HEADLESS_JOBS,
    pairings_per_gate: Mapping[str, int] | None = None,
) -> dict:
    """Bouts per pairing for a 95 % interval of at most +-0.06, and their wall time."""
    x = float(speed["xRealTimePerProcess"])
    rows = {}
    for gate, (p, unit) in GATE_TRIALS.items():
        trials = trials_for_half_width(p)
        bouts = trials if unit == "bouts" else math.ceil(trials / kills_per_bout)
        pairings = (pairings_per_gate or {}).get(gate, 1)
        wall_h = bouts * pairings * bout_sim_s / x / jobs / 3600.0
        rows[gate] = {
            "p": p,
            "trials": trials,
            "unit": unit,
            "boutsPerPairing": bouts,
            "pairings": pairings,
            "wallHours": round(wall_h, 2),
        }
    return {
        "schema": "verse.bout_table/1",
        "halfWidth": HALF_WIDTH,
        "xRealTimePerProcess": x,
        "killsPerBout": kills_per_bout,
        "boutSimS": bout_sim_s,
        "jobs": jobs,
        "gates": rows,
        "queueBouts": max(rows[g]["boutsPerPairing"] for g in ("BG1", "BG2", "BG4")),
        "nightlyBouts": max(r["boutsPerPairing"] for r in rows.values()),
    }


def pairings_per_gate(cfg: Mapping) -> dict[str, int]:
    n_tricks = len(cfg["tricks"])
    return {
        "BG1": 1,
        "BG2": 1,
        "BG3": 1 + len(cfg["tiers"]),
        "BG4": n_tricks,
        "BG5": n_tricks + 1,
        "BG6": 2,
        "BG7": 1,
        "BG8": 2 * len(cfg["learning"]["opponents"]),
        "BG9": 1,
        "BG10": len(cfg["adaptive"]["opponents"]),
    }


# --- running ---


Launcher = Callable[[list[str], Path], "subprocess.Popen"]


def _launch(command: list[str], log_path: Path) -> subprocess.Popen:
    sink = open(log_path.with_suffix(".stdout.txt"), "w", encoding="utf-8", errors="replace")  # noqa: SIM115
    return subprocess.Popen(command, stdout=sink, stderr=subprocess.STDOUT)  # noqa: S603


def run_jobs(
    shards: Sequence[Sequence[Unit]],
    cfg: Mapping,
    run_dir: Path,
    run: str,
    *,
    patch: Mapping | None,
    trace_bearing: bool,
    engine: Path,
    project: Path,
    launcher: Launcher = _launch,
    lock_factory: Callable[..., object] | None = None,
    timeout_s: float = PROCESS_TIMEOUT_S,
) -> list[dict]:
    """Run one headless editor per shard inside one lock hold; returns per-job status."""
    from scripts.unreal import with_lock

    lock_factory = lock_factory or with_lock.MachineLock
    jobs = []
    for k, shard in enumerate(shards):
        job_dir = run_dir / f"job{k}"
        job_dir.mkdir(parents=True, exist_ok=True)
        scenario = scenario_document(run, k, shard, cfg, job_dir, patch, trace_bearing)
        problems = validate(scenario, "scenario.schema.json")
        if problems:
            raise common.UnrealScriptError(
                "scenario does not match verse.scenario/1: " + problems[0]
            )
        path = job_dir / "scenario.json"
        path.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
        jobs.append((k, path, job_dir / f"job{k}.log"))
    results = []
    with lock_factory("balance", f"balance.py {run} ({len(jobs)} jobs)"):
        started = time.monotonic()
        procs = [
            (k, launcher(command_for(engine, project, cfg["map"], path, log), log), log)
            for k, path, log in jobs
        ]
        for k, proc, log in procs:
            left = max(1.0, timeout_s - (time.monotonic() - started))
            try:
                code = proc.wait(timeout=left)
            except subprocess.TimeoutExpired:
                common.log(f"balance job {k} ran past {timeout_s / 60:.0f} min; stopping it")
                proc.kill()
                code = proc.wait()
            results.append({"job": k, "returncode": code, "log": str(log)})
    return results


def collect(run_dir: Path) -> tuple[list[dict], list[dict], str]:
    bouts = read_bouts(run_dir)
    speed_docs = [load_json(p) for p in sorted(run_dir.rglob("speed.json"))]
    log_text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in sorted(run_dir.rglob("job*.log"))
    )
    merge_fire_audit(bouts, parse_fire_audit(log_text))
    audit_log = run_dir / "fire_audit.log"
    audit_lines = [line for line in log_text.splitlines() if FIRE_AUDIT_TAG in line]
    audit_log.write_text("\n".join(audit_lines) + ("\n" if audit_lines else ""), encoding="utf-8")
    return bouts, speed_docs, str(audit_log)


def summarize(gates: Sequence[Gate]) -> int:
    for g in gates:
        print(f"{g.id:5s} {g.status.upper():8s} {g.detail}")
    failed = [g.id for g in gates if g.status == "fail"]
    if failed:
        print(f"balance: FAIL ({', '.join(failed)})")
        return 1
    print("balance: OK (no gate failed)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--set",
        dest="sets",
        action="append",
        choices=[*SET_NAMES, "all"],
        help="Pairing set (repeatable).",
    )
    parser.add_argument(
        "--bouts", type=int, help="Bouts per pairing (default: the bout table's nightly count)."
    )
    parser.add_argument("--seed", type=int, default=1, help="Run seed.")
    parser.add_argument("--patch", type=Path, help="Tier patch JSON applied in every unit.")
    parser.add_argument(
        "--jobs",
        type=int,
        default=common.MAX_HEADLESS_JOBS,
        help="Parallel headless processes (max 4).",
    )
    parser.add_argument("--tricks", help="Comma list limiting the trick pairings.")
    parser.add_argument("--gates", help="Comma list of gate ids to report.")
    parser.add_argument("--nightly", action="store_true", help="BG11 also requires F5, F7 and L1.")
    parser.add_argument(
        "--checks", type=Path, help="JSON {gate: {status, detail}} for F2, F3, BR1, L1."
    )
    parser.add_argument(
        "--from-bouts", type=Path, help="Recompute the report from a run folder; no run."
    )
    parser.add_argument("--plan", action="store_true", help="Print the units per job and exit.")
    parser.add_argument(
        "--speed", action="store_true", help="Measure x real time and write the bout table."
    )
    parser.add_argument(
        "--out", type=Path, help="Run folder (default Saved/Harness/balance/<run>)."
    )
    parser.add_argument("--map", help="Map override (default: sets.json, the hangar).")
    parser.add_argument("--worktree", type=Path, default=common.REPO_ROOT)
    args = parser.parse_args(argv)

    cfg = load_config()
    if args.map:
        cfg["map"] = args.map
    tricks = [t for t in (args.tricks or "").split(",") if t] or None
    only = [g for g in (args.gates or "").split(",") if g] or None
    if only and set(only) - set(GATE_IDS):
        return common.exit_with(
            common.UnrealScriptError(f"unknown gate ids: {sorted(set(only) - set(GATE_IDS))}")
        )
    patch = load_json(args.patch) if args.patch else None
    checks = load_json(args.checks) if args.checks else None
    sets = args.sets or (["ladder"] if args.speed else ["all"])
    if args.speed:
        sets = ["ladder"]
    pairings = build_pairings(sets, cfg, tricks)
    default_bouts = 2 if args.speed else _table_bouts()
    bouts = args.bouts or default_bouts
    run = f"{common.run_stamp()}-{'speed' if args.speed else '-'.join(sets)}-s{args.seed}"
    run_dir = (
        args.out or (args.worktree / "unreal" / "Verse" / "Saved" / "Harness" / "balance" / run)
    ).resolve()

    if args.from_bouts:
        run_dir = args.from_bouts.resolve()
        bouts_list, speed_docs, audit_log = collect(run_dir)
        played = {b["pairing"] for b in bouts_list}
        pairings = [p for p in build_pairings(["all"], cfg, tricks) if p.id in played] or pairings
    else:
        units = plan_units(pairings, bouts, args.seed, int(cfg.get("boutsPerMatch", 10)))
        if args.speed:
            units = units[: max(1, args.jobs)]
            for u in units:
                u.pairing.match_time_limit_s = 120.0
        shards = shard_units(units, args.jobs)
        if args.plan:
            for k, shard in enumerate(shards):
                print(f"job{k}: " + ", ".join(f"{u.pairing.id}#{u.match}x{u.bouts}" for u in shard))
            return 0
        try:
            engine = common.engine_root()
            project = common.project_file(args.worktree.resolve())
            results = run_jobs(
                shards,
                cfg,
                run_dir,
                run,
                patch=patch,
                trace_bearing=args.nightly,
                engine=engine,
                project=project,
            )
        except common.UnrealScriptError as error:
            return common.exit_with(error)
        bad = [r for r in results if r["returncode"] != 0]
        for r in bad:
            common.log(f"job {r['job']} exited {r['returncode']} (log {r['log']})")
        bouts_list, speed_docs, audit_log = collect(run_dir)
        if bad and not bouts_list:
            return 1

    speed = speed_summary(speed_docs)
    if args.speed:
        if not speed:
            return common.exit_with(
                common.UnrealScriptError("no speed.json written; see the job logs")
            )
        sim_bouts = [float(b["durationS"]) for b in bouts_list] or [240.0]
        kills = [len(b.get("kills", [])) for b in bouts_list]
        kpb = (
            statistics.mean(kills)
            if kills and statistics.mean(kills) > 0
            else DEFAULT_KILLS_PER_BOUT
        )
        table = bout_table(
            speed,
            kills_per_bout=kpb,
            bout_sim_s=max(statistics.mean(sim_bouts), 1.0),
            jobs=max(1, args.jobs),
            pairings_per_gate=pairings_per_gate(cfg),
        )
        table["measured"] = {
            "run": run,
            "speed": speed,
            "nullBrain": all(not b.get("kills") for b in bouts_list),
        }
        (run_dir / "speed_report.json").write_text(json.dumps(table, indent=2), encoding="utf-8")
        print(json.dumps(table, indent=2))
        return 0

    started = min((p.stat().st_mtime for p in run_dir.rglob("scenario.json")), default=time.time())
    l1 = None
    if any(p.id.endswith(".l1") for p in pairings):
        fields = load_json(L1_FIELDS_FILE)["fields"]
        roots = [args.worktree / "unreal" / "Verse" / "Saved"]
        data_dir = os.environ.get("DODAIOS_DATA_DIR")
        if data_dir:
            roots.append(Path(data_dir))
        l1 = l1_scan(roots, fields, started)
    metrics = aggregate(
        pairings, bouts_list, float(cfg["reset"]["windowS"]), cfg["adaptive"]["killWindow"]
    )
    gates = evaluate_gates(
        metrics, cfg, checks=checks, l1_findings=l1, nightly=args.nightly, only=only
    )
    report = build_report(
        run,
        args.seed,
        sets,
        metrics,
        gates,
        bouts=bouts,
        jobs=args.jobs,
        patch=patch,
        speed=speed,
        fire_audit_log=audit_log,
    )
    problems = validate(report, "balance.schema.json")
    if problems:
        return common.exit_with(
            common.UnrealScriptError("report does not match verse.balance/1: " + problems[0])
        )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    common.log(f"report: {run_dir / 'report.json'}")
    return summarize(gates)


def _table_bouts() -> int:
    try:
        return int(load_json(BOUT_TABLE_FILE)["nightlyBouts"])
    except (OSError, KeyError, ValueError):
        return 200


if __name__ == "__main__":
    sys.exit(main())
