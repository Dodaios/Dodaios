#!/usr/bin/env python3
"""Build every Verse sound from ``unreal/Verse/Data/audio/cues.json`` (WP19).

Writes one mono 48 kHz 16-bit WAV per cue variant into the ignored cache
``art/verse/.cache/audio/<Group>/SW_<cue>_<nn>.wav`` plus
``art/verse/.cache/audio/manifest.json`` (cue, variant, file, SHA-256,
duration, licence). WAVs are never committed (architecture 8.4); only the
imported ``.uasset`` files are. Deterministic: the same manifest gives the
same bytes.

    python art/verse/audio/build_audio.py            # everything
    python art/verse/audio/build_audio.py --only wpn_rifle_fp_body imp_glass
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dsp  # noqa: E402
import recipes  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "unreal" / "Verse" / "Data" / "audio"
CUES_FILE = DATA_DIR / "cues.json"
CACHE_DIR = REPO_ROOT / "art" / "verse" / ".cache" / "audio"


def load_cues(path: Path = CUES_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def asset_name(cue_id: str, variant: int) -> str:
    return f"SW_{cue_id}_{variant + 1:02d}"


def variant_params(cue: dict, variant: int) -> dict:
    params = dict(cue.get("params", {}))
    files = cue.get("files")
    if files:
        params["file"] = files[variant % len(files)]
    return params


def render_variant(cue: dict, variant: int) -> np.ndarray:
    params = variant_params(cue, variant)
    if cue.get("loop") and cue["recipe"] == "cc0":
        params["loop"] = True
    x = recipes.build(cue["recipe"], cue["seed"] + variant, params)
    if not cue.get("loop"):
        # Trim trailing silence below -70 dBFS relative to the peak, keep a 20 ms tail.
        peak = np.max(np.abs(x)) + 1e-12
        idx = np.nonzero(np.abs(x) > peak * 10 ** (-70 / 20))[0]
        if idx.size:
            x = x[: min(len(x), idx[-1] + dsp.seconds(0.02))]
        x = dsp.fade(x, 0.0003, 0.01)
    return dsp.normalize_peak(x, float(cue["peak_db"]))


def write_wav(path: Path, x: np.ndarray) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = dsp.to_pcm16(x)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(dsp.SR)
        w.writeframes(pcm.tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float64) / 32767.0


def build(only: set[str] | None = None, cache: Path = CACHE_DIR) -> dict:
    doc = load_cues()
    entries = []
    for cue in doc["cues"]:
        if only and cue["id"] not in only:
            continue
        for v in range(int(cue["variants"])):
            x = render_variant(cue, v)
            rel = Path(cue["group"]) / f"{asset_name(cue['id'], v)}.wav"
            sha = write_wav(cache / rel, x)
            entries.append(
                {
                    "cue": cue["id"],
                    "variant": v,
                    "asset": asset_name(cue["id"], v),
                    "group": cue["group"],
                    "file": rel.as_posix(),
                    "sha256": sha,
                    "duration_s": round(len(x) / dsp.SR, 4),
                    "loop": bool(cue.get("loop")),
                    "licence": cue["licence"],
                }
            )
    manifest = {"schema": "verse.audio.build/1", "sample_rate": dsp.SR, "sounds": entries}
    if not only:
        (cache / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", nargs="*", help="cue ids to build (default: all)")
    args = parser.parse_args(argv)
    manifest = build(set(args.only) if args.only else None)
    total = sum(e["duration_s"] for e in manifest["sounds"])
    print(f"built {len(manifest['sounds'])} sounds ({total:.1f} s) into {CACHE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
