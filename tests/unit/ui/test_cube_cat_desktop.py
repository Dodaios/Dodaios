"""The desktop model player plays the GLB clips named by pet.json."""

from __future__ import annotations

from dodaios.ui.pets.loader import builtin_root, read_manifest
from dodaios.ui.pets.states import PET_STATES
from ui.orb.cube_cat_desktop import load_cube_cat, pose


def test_idle_moves_the_body_and_every_state_has_a_clip() -> None:
    manifest = read_manifest(builtin_root() / "cube-cat", builtin=True)
    options = manifest.options
    cat = load_cube_cat(
        builtin_root() / "cube-cat" / "model.glb",
        height=options.height,
        eye=options.eye,
        aim_y=options.aim * options.height,
    )
    assert len(cat.meshes) == 7
    assert set(cat.clips) >= {"idle", "walk", "run", "static"}
    start = pose(cat, "idle", 0.0)
    later = pose(cat, "idle", 0.5)
    body = next(mesh.node for mesh in cat.meshes if mesh.count > 800)
    assert start[body] != later[body]
    assert {manifest.clip_for(state) for state in PET_STATES} <= set(cat.clips)
