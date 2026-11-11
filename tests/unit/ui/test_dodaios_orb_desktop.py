"""The desktop Dodaios orb is the scene, not a fragment stand-in."""

from __future__ import annotations

from dodaios.ui.pets.states import PET_STATES
from ui.orb.dodaios_orb_desktop import _CORE_FRAG, Motion, build_scene, mood_for, step_motion


def test_scene_has_the_page_parts_and_idle_turns() -> None:
    scene = build_scene()
    assert scene.core_count > 200
    assert scene.particle_count == 165
    assert scene.filament_count == 18
    assert len(scene.dashed) == 4
    assert len(scene.flat) == 5
    assert scene.spoke_count > 10
    motion = step_motion(Motion(), "idle", 0.0, 0.0)
    before = motion.root_y
    step_motion(motion, "idle", 0.5, 0.0)
    assert motion.root_y != before
    assert mood_for("sleeping")["energy"] < mood_for("idle")["energy"]
    for state in PET_STATES:
        assert mood_for(state)["energy"] > 0
    loud = step_motion(Motion(), "talking", 0.0, 1.0)
    assert loud.shown_energy > mood_for("talking")["energy"]


def test_core_shimmer_does_not_stripe_across_the_shell() -> None:
    assert "n.y *" not in _CORE_FRAG
    assert "n.x *" not in _CORE_FRAG
