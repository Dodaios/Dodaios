"""`import_art.py wp14`: the whole WP14 chain in one editor session (one lock hold).

Order matters: the grade LUT first (the post-process master references
it), then the masters, the MIs, the weapon and VFX meshes (their slots need
the MIs), then validation, then the lookdev captures (deferred, GPU).
"""

from __future__ import annotations

from verse_pipeline import (
    import_assets,
    lookdev,
    masters,
    materials,
    records,
    validate_assets,
    weapons,
)


def wp14_records() -> list[str]:
    out = []
    for record in records.load_all():
        if weapons.is_wp14(record) or record["asset_path"].startswith("/Game/Verse/PostProcess/"):
            out.append(record["name"])
    return out


def run(*, with_lookdev: bool = True) -> dict:
    names = wp14_records()
    steps = {}
    steps["lut"] = import_assets.run(["T_Verse_Grade_LUT_M"])
    steps["masters"] = masters.run([])
    steps["materials"] = materials.run([])
    steps["assets"] = import_assets.run([n for n in names if n != "T_Verse_Grade_LUT_M"])
    recipe_names = [r["name"] for r in materials.load_recipes()]
    steps["validate"] = validate_assets.run(
        [n for n in names if not n.startswith(("SKEL_", "T_"))] + recipe_names
    )
    errors = [f"{k}: {e}" for k, v in steps.items() for e in v.get("errors", [])]
    for k, v in steps.items():
        if v.get("error"):
            errors.append(f"{k}: {v['error']}")
    summary = {"steps": steps, "errors": errors}
    if with_lookdev:
        return lookdev.run(prelude=summary)
    summary["ok"] = not errors
    return summary
