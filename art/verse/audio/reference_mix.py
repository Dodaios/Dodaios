#!/usr/bin/env python3
"""Render the reference duel replay offline and measure it (WP19 A19.4).

The replay is ``unreal/Verse/Data/audio/reference_duel.json``: a fixed 90 s
hangar duel as the listener hears it (own shots, the opponent's shots at
range, bullet flybys, spent casings, impacts, footsteps, reloads, breaks, a breach and a finisher
over the hangar bed). The mix uses the same rules as
``UVerseAudioSubsystem``: cue volumes, bus gains and master gain from
``mix.json``, the distance curve of ``VerseAudioAttenuation.cpp``, the shot
layer crossfade and the no-repeat variant picker.

Pass: integrated -16 LUFS within 1 LU, true peak at most -1 dBTP.

    python art/verse/audio/reference_mix.py                 # report + WAV in Saved/
    python art/verse/audio/reference_mix.py --check         # exit 1 when it fails
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_audio  # noqa: E402
import dsp  # noqa: E402
import loudness  # noqa: E402

REPO_ROOT = build_audio.REPO_ROOT
DATA_DIR = build_audio.DATA_DIR
PROOF_DIR = REPO_ROOT / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP19" / "19.1"
TARGET_LUFS, TOLERANCE_LU, MAX_TRUE_PEAK = -16.0, 1.0, -1.0

#: bot.md 3.2 ranges in metres; whole-arena rows have no range (None). Mirrors DA_Audibility.
NOISE_RANGE_M = {
    "Noise.Shot": None,
    "Noise.Footstep.Sprint": 20.0,
    "Noise.Footstep.Run": 10.0,
    "Noise.Footstep.Walk": 4.0,
    "Noise.Move.Slide": 12.0,
    "Noise.Move.Land": 12.0,
    "Noise.Move.Mantle": 12.0,
    "Noise.Reload": 7.0,
    "Noise.Gadget.BulwarkDeploy": 15.0,
    "Noise.Gadget.BulwarkHum": 5.0,
    "Noise.Gadget.BreachPlant": 10.0,
    "Noise.Gadget.BreachDetonate": None,
    "Noise.Fracture": 40.0,  # x loudness
    "Noise.Drone": 40.0,  # x loudness
    "Noise.Melee": 8.0,
    "Noise.Finisher": 8.0,
    "Noise.Impact": 3.0,
}
SCALED = {"Noise.Fracture", "Noise.Drone"}


def db(x: float) -> float:
    return 10 ** (x / 20)


def distance_gain(d: float, range_m: float | None, dist: dict) -> float:
    """Python twin of Verse::Audio::DistanceGain."""
    ref, roll = dist["reference_m"], dist["rolloff"]
    g = 1.0 if d <= ref else (ref / d) ** roll
    g = max(g, db(dist["floor_db"]))
    if range_m is None:
        return g
    if d >= range_m:
        return 0.0
    start = dist["fade_start_fraction"] * range_m
    if d > start:
        u = (d - start) / (range_m - start)
        g *= 1 - (3 * u * u - 2 * u**3)
    return g


def smoothstep(a: float, b: float, x: float) -> float:
    u = min(max((x - a) / (b - a), 0.0), 1.0)
    return u * u * (3 - 2 * u)


class Picker:
    """No-repeat variant picker (parity Z-15), same rule as FVerseVariantPicker."""

    def __init__(self, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.last: dict[str, int] = {}

    def pick(self, cue: str, count: int) -> int:
        if count <= 1:
            return 0
        last = self.last.get(cue, -1)
        v = int(self.rng.integers(0, count - 1 if last >= 0 else count))
        if last >= 0 and v >= last:
            v += 1
        self.last[cue] = v
        return v


def render(events: list[dict], length_s: float, cues: dict, mix: dict, cache: Path) -> np.ndarray:
    out = np.zeros(dsp.seconds(length_s))
    picker = Picker()
    sounds: dict[str, np.ndarray] = {}

    def sound(cue_id: str, variant: int) -> np.ndarray:
        key = f"{cue_id}:{variant}"
        if key not in sounds:
            c = cues[cue_id]
            sounds[key] = build_audio.read_wav(
                cache / c["group"] / f"{build_audio.asset_name(cue_id, variant)}.wav"
            )
        return sounds[key]

    def place(cue_id: str, at: float, gain: float, until: float | None = None) -> None:
        c = cues[cue_id]
        v = picker.pick(cue_id, int(c["variants"]))
        x = sound(cue_id, v)
        g = (
            gain
            * float(np.mean(c["volume"]))
            * db(mix["bus_gain_db"][c["bus"]])
            * db(mix["master_gain_db"])
        )
        start = dsp.seconds(at)
        if c.get("loop"):
            end = dsp.seconds(until if until is not None else length_s)
            reps = int(np.ceil((end - start) / len(x))) + 1
            x = np.tile(x, reps)[: end - start]
        n = min(len(x), len(out) - start)
        if n > 0:
            out[start : start + n] += g * x[:n]

    dist = mix["distance"]
    for ev in events:
        at, d = float(ev["t"]), float(ev.get("d", 0.0))
        kind = ev["kind"]
        if kind == "shot":
            w = ev.get("weapon", "rifle")
            if ev.get("own"):
                for layer in ("fp_mech", "fp_body", "tail"):
                    place(f"wpn_{w}_{layer}", at, 1.0)
            else:
                g = distance_gain(d, None, dist)
                far = smoothstep(
                    mix["shot_layers"]["near_full_m"], mix["shot_layers"]["far_full_m"], d
                )
                place(f"wpn_{w}_tp_near", at, g * (1 - far))
                place(f"wpn_{w}_tp_far", at, g * far)
                place(f"wpn_{w}_tp_tail", at, g)
            # The spent casing lands at the shooter's feet a moment later (cue range_m, as flybys).
            casing = cues.get(f"casing_{w}")
            if casing:
                lo, hi = mix["casing"]["delay_s"]
                drop = mix["casing"]["drop_m"]
                when = at + float(picker.rng.uniform(lo, hi))
                cg = (
                    1.0
                    if ev.get("own")
                    else distance_gain(float(np.hypot(d, drop)), float(casing["range_m"]), dist)
                )
                if cg > 0.0:
                    place(f"casing_{w}", when, cg)
            continue
        cue_id = ev["cue"]
        c = cues[cue_id]
        gain = float(ev.get("gain", 1.0))
        if c["space"] == "3d" and not ev.get("own"):
            noise = c.get("noise") or ""
            if ev.get("own_feedback") and c.get("range_m"):
                rng_m = float(c["range_m"])
            elif noise:
                base = NOISE_RANGE_M[noise]
                rng_m = (
                    None
                    if base is None
                    else base * (float(ev.get("loudness", 1.0)) if noise in SCALED else 1.0)
                )
            else:
                rng_m = float(c.get("range_m") or 0.0) or None
            gain *= distance_gain(d, rng_m, dist)
        place(cue_id, at, gain, ev.get("until"))
    return out


def limit(x: np.ndarray, lim: dict) -> np.ndarray:
    """Look-ahead peak limiter: model of the SMX_VerseMaster dynamics processor (limiter mode)."""
    thr = db(lim["threshold_db"])
    look = max(1, dsp.seconds(lim["lookahead_ms"] / 1000))
    rel = np.exp(-1.0 / (lim["release_ms"] / 1000 * dsp.SR))
    att = np.exp(-1.0 / (lim["attack_ms"] / 1000 * dsp.SR))
    # Peak of the window ahead (the signal is delayed by `look`, so the gain is ready in time).
    padded = np.concatenate([np.abs(x), np.zeros(look)])
    from scipy.ndimage import maximum_filter1d

    ahead = maximum_filter1d(padded, size=look + 1, origin=-(look // 2))[: len(x)]
    want = np.minimum(1.0, thr / np.maximum(ahead, 1e-12))
    gain = np.empty_like(want)
    g = 1.0
    for i, w in enumerate(want):
        g = w if w < g else g  # instant attack inside the look-ahead window
        g = w + (g - w) * (att if w < g else rel)
        gain[i] = g
    return x * gain


def run(check: bool) -> dict:
    cues_doc = build_audio.load_cues()
    cues = {c["id"]: c for c in cues_doc["cues"]}
    mix = json.loads((DATA_DIR / "mix.json").read_text(encoding="utf-8"))
    replay = json.loads((DATA_DIR / "reference_duel.json").read_text(encoding="utf-8"))
    cache = build_audio.CACHE_DIR
    missing = [
        cid
        for cid in cues
        if not (cache / cues[cid]["group"] / f"{build_audio.asset_name(cid, 0)}.wav").exists()
    ]
    if missing:
        build_audio.build()
    x = render(replay["events"], float(replay["length_s"]), cues, mix, cache)
    x = limit(x, mix["limiter"])
    lufs = loudness.integrated_lufs(x, dsp.SR)
    tp = loudness.true_peak_dbtp(x, dsp.SR)
    ok = abs(lufs - TARGET_LUFS) <= TOLERANCE_LU and tp <= MAX_TRUE_PEAK
    report = {
        "test": "A19.4 loudness",
        "replay": "unreal/Verse/Data/audio/reference_duel.json",
        "events": len(replay["events"]),
        "length_s": replay["length_s"],
        "integrated_lufs": round(lufs, 2),
        "true_peak_dbtp": round(tp, 2),
        "target_lufs": TARGET_LUFS,
        "tolerance_lu": TOLERANCE_LU,
        "max_true_peak_dbtp": MAX_TRUE_PEAK,
        "master_gain_db": mix["master_gain_db"],
        "limiter": mix["limiter"],
        "pass": bool(ok),
    }
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    build_audio.write_wav(PROOF_DIR / "reference_duel_capture.wav", x)
    (PROOF_DIR / "loudness_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    if check and not ok:
        raise SystemExit(1)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 when the loudness gate fails")
    args = parser.parse_args(argv)
    run(args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
