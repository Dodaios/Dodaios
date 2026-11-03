"""WP14 evidence numbers from the lookdev frames and the records (host Python).

    python art/verse/weapons/look/evaluate.py

Reads `unreal/Verse/Saved/Harness/proof/WP14/lookdev/` (written by
`python scripts/unreal/import_art.py wp14`) and the baked look files in
`art/verse/.cache/unreal/look/`, and writes `metrics.json` beside the frames:

* A14.1: bones, sockets and triangles per weapon record,
* A14.3: banned pixels (art-pipeline 8.3 rendered-pixel rule) per frame,
* A14.4: mean and max CIEDE2000 of the chart rendered in Unreal against the
  Blender AgX render of the same scene-linear patches, plus the same number
  for the LUT alone (offline trilinear lookup),
* A14.5: the frame cost bound of 64 bolts in flight at 2560x1440 that the
  lookdev run measured (`vfx_cost`), against 0.1 ms.

Exit 0 only when A14.1, A14.3, A14.4 and A14.5 pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "art" / "verse"))

from weapons import specs  # noqa: E402
from weapons.look import agx, palette  # noqa: E402

PROOF = REPO / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP14"
FRAMES = PROOF / "lookdev"
LOOK = REPO / "art" / "verse" / ".cache" / "unreal" / "look"
RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import"
DELTA_E_MAX = 3.0
VFX_COST_MAX_MS = 0.1
PATCH_HALF = 6


def _image(path: Path):
    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0


def lut_error() -> dict:
    lut = _image(LOOK / "T_Verse_Grade_LUT_M.png").tolist()
    ref = _image(LOOK / "chart_agx_reference.png")[0]
    errors = [
        agx.delta_e(agx.sample(lut, p), r) for p, r in zip(agx.chart_linear(), ref, strict=True)
    ]
    return {"mean": sum(errors) / len(errors), "max": max(errors)}


def chart_error(report: dict, frame_name: str | None = None) -> dict:
    frame = _image(FRAMES / (frame_name or report["chart"]["frame"]))
    ref = _image(LOOK / "chart_agx_reference.png")[0]
    patches = []
    for (x, y), want in zip(report["chart"]["pixels"], ref, strict=True):
        region = frame[y - PATCH_HALF : y + PATCH_HALF + 1, x - PATCH_HALF : x + PATCH_HALF + 1]
        got = region.reshape(-1, 3).mean(axis=0)
        patches.append(
            {
                "got": [round(v, 4) for v in got],
                "want": [round(v, 4) for v in want],
                "delta_e": agx.delta_e(got, want),
            }
        )
    values = [p["delta_e"] for p in patches]
    return {"mean": sum(values) / len(values), "max": max(values), "patches": patches}


def banned(report: dict) -> dict:
    out = {}
    for name in report.get("frames", []):
        if name.startswith(("chart", "matprobe")):
            continue
        hits, total = palette.count_banned_image(FRAMES / name)
        out[name] = {"banned": hits, "pixels": total}
    return out


def vfx_cost(report: dict) -> dict:
    cost = report.get("vfx_cost")
    if not cost:
        return {"pass": False, "reason": "lookdev wrote no vfx_cost"}
    cost = dict(cost)
    samples = cost.get("samples_ms")
    if samples:  # the fastest sample of each configuration (load only adds time)
        best = {k: min(v) for k, v in samples.items()}
        cost["min_ms"] = {k: round(v, 4) for k, v in best.items()}
        cost["delta_64_ms"] = round(best["bolts_64"] - best["none"], 4)
        per_64 = (best["bolts_1024"] - best["none"]) * 64.0 / 1024.0
        cost["per_64_from_1024_ms"] = round(per_64, 4)
        cost["bound_ms"] = round(max(cost["delta_64_ms"], per_64, 0.0), 4)
        cost["method"] = "wall time of capture + readback, fastest of each, includes render thread"
    keys = ("median_ms", "min_ms", "delta_64_ms", "per_64_from_1024_ms", "bound_ms", "method")
    out = {k: cost.get(k) for k in keys}
    out["limit_ms"] = VFX_COST_MAX_MS
    out["pass"] = cost["bound_ms"] <= VFX_COST_MAX_MS
    return out


def budgets() -> dict:
    out = {}
    for spec in specs.ARSENAL:
        folder = spec.folder.removeprefix("/Game/Verse/")
        record = json.loads((RECORDS / folder / f"{spec.asset}.import.json").read_text("utf-8"))
        mesh = record["mesh"]
        bones = mesh.get("bones", [])
        sockets = mesh.get("sockets", [])
        out[spec.asset] = {
            "triangles": mesh["triangles"],
            "cap": spec.triangle_cap,
            "bones": len(bones),
            "sockets": sockets,
            "pass": mesh["triangles"] <= spec.triangle_cap
            and len(bones) <= specs.MAX_WEAPON_BONES
            and all(s in sockets for s in specs.required_sockets(spec)),
        }
    return out


def main() -> int:
    metrics: dict = {"A14.1": budgets(), "lut_offline": lut_error()}
    report_path = FRAMES / "lookdev.json"
    if report_path.is_file():
        report = json.loads(report_path.read_text("utf-8"))
        metrics["A14.4"] = chart_error(report)
        if "chart_agx_srgb_target.png" in report.get("frames", []):
            other = chart_error(report, "chart_agx_srgb_target.png")
            metrics["chart_srgb_target"] = {"mean": other["mean"], "max": other["max"]}
        metrics["A14.3"] = banned(report)
        metrics["A14.5"] = vfx_cost(report)
        metrics["lookdev_errors"] = report.get("errors", [])
    ok = all(v["pass"] for v in metrics["A14.1"].values())
    ok = ok and metrics.get("A14.4", {"mean": 99})["mean"] <= DELTA_E_MAX
    ok = ok and all(v["banned"] == 0 for v in metrics.get("A14.3", {"x": {"banned": 1}}).values())
    ok = ok and metrics.get("A14.5", {"pass": False})["pass"]
    metrics["pass"] = ok
    PROOF.mkdir(parents=True, exist_ok=True)
    (PROOF / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    summary = {
        "A14.1": all(v["pass"] for v in metrics["A14.1"].values()),
        "lut_offline_mean_dE": round(metrics["lut_offline"]["mean"], 3),
        "chart_mean_dE": round(metrics.get("A14.4", {}).get("mean", -1), 3),
        "chart_max_dE": round(metrics.get("A14.4", {}).get("max", -1), 3),
        "banned_total": sum(v["banned"] for v in metrics.get("A14.3", {}).values()),
        "bolt_cost_bound_ms": metrics.get("A14.5", {}).get("bound_ms"),
        "pass": ok,
    }
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
