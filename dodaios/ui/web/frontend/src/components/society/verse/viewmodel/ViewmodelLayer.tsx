/**
 * Mounts the first-person viewmodel on a stage with an eye-level view: cuts
 * the arms from the commander's own body (the officer the deck and the duel
 * draw for them) once the character library has it, dresses them in the
 * commander's uniform, hands them to the eye view (`runtime.viewmodel`), and
 * every frame tells them what to show: the deck's empty hands while the
 * commander walks in first person, the blaster while a duel is fought
 * through the eyes, nothing in third person or bird's-eye.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useFrame } from "@react-three/fiber";
import type { SkinnedMesh } from "three";
import type { Deck } from "../content/deck";
import type { StageRuntime } from "../runtime";
import { COMMANDER_SKIN, disposeInstance, type CharacterLibrary } from "../actors/characters";
import type { Look } from "../actors/look";
import type { DuelController } from "../duel/duelController";
import { OWN_ACCENT } from "../duel/DuelLayer";
import { hash32 } from "../life/crew";
import { CUT, cutArms } from "./armMesh";
import { ARM } from "./arms";
import { MOTION, viewmodelVisibility } from "./motion";
import { Viewmodel, VIEWMODEL, type ArmColours, type ViewmodelFrame } from "./viewmodel";

interface Props {
  runtime: StageRuntime;
  duel: DuelController;
  deck: Deck;
  library: CharacterLibrary | null;
  commanderId: string;
  commanderLook: Look;
}

/** The uniform tiers' colours when the character contract has not loaded yet. */
const FALLBACK: ArmColours = { uniform: "#3b3f47", trim: "#5a5f68" };
/** A walking officer's speed (the bob is measured against it) when the library has none. */
const WALK_SPEED = 1.4;

/** The Sovereign's sleeves: black velvet with a gold cuff (its own colours, whatever the rank). */
export const SOVEREIGN_ARMS: ArmColours = { uniform: "#201e23", trim: "#201e23", cuff: "#d1a650", skin: "#c2b4a8" };

export function armColours(library: CharacterLibrary | null, look: Look): ArmColours {
  if (library?.contract.models.some((m) => m.id === COMMANDER_SKIN)) return SOVEREIGN_ARMS;
  const tier = library?.contract.tiers[look.tier];
  return tier ? { uniform: tier.M_Uniform, trim: tier.M_Trim } : FALLBACK;
}

export function ViewmodelLayer({ runtime, duel, deck, library, commanderId, commanderLook }: Props) {
  const { uniform, trim, cuff, skin } = armColours(library, commanderLook);
  const vmRef = useRef<Viewmodel | null>(null);
  const [vm, setVm] = useState<Viewmodel | null>(null);
  useEffect(() => {
    const made = new Viewmodel(FALLBACK, OWN_ACCENT);
    vmRef.current = made;
    runtime.viewmodel = made;
    setVm(made);
    // Development handle: tune the layout live (edit `layout`, then `retune()`).
    if (import.meta.env.DEV) Object.assign(window, { __verseViewmodel: { layout: VIEWMODEL, arm: ARM, cut: CUT, motion: MOTION, retune: () => made.retune(), viewmodel: made } });
    return () => {
      if (runtime.viewmodel === made) runtime.viewmodel = null;
      if (vmRef.current === made) vmRef.current = null;
      made.dispose();
    };
  }, [runtime]);
  // The arms are the commander's own: the officer body the deck and the duel draw for them (same choice by id).
  useEffect(() => {
    if (!library || !vm) return;
    const model = library.model("officer", COMMANDER_SKIN, hash32(commanderId));
    if (!model) return;
    let alive = true;
    library.instantiate(model).then((instance) => {
      try {
        if (alive && vmRef.current === vm) vm.attachArms(cutArms(instance.meshes.filter((m): m is SkinnedMesh => (m as SkinnedMesh).isSkinnedMesh)));
      } catch (error: unknown) {
        console.warn("Verse first-person arms unavailable", error);
      }
      // The cut copied what it needs; the atlas it keeps is shared with the body.
      disposeInstance(instance);
    }, (error: unknown) => console.warn("Verse first-person arms unavailable", error));
    return () => { alive = false; };
  }, [vm, library, commanderId]);
  // The sleeves wear the commander's uniform (a promotion repaints them).
  useEffect(() => { vm?.setColours({ uniform, trim, cuff, skin }); }, [vm, uniform, trim, cuff, skin]);

  const frame = useMemo<ViewmodelFrame>(() => ({
    visibility: { arms: false, mode: "deck", hideOwnBody: false, raise: 0 },
    player: null, speed: 0, walkSpeed: WALK_SPEED, x: 0, y: 0, z: 0, deck: null, reduced: false, frozen: false,
  }), []);
  const last = useRef({ x: 0, z: 0, primed: false });

  // Before the eye view renders (priority 1) and after the duel's frame: what the arms show this frame.
  useFrame((_, dt) => {
    const vm = vmRef.current;
    if (!vm) return;
    const eyeOn = !!runtime.eye;
    const step = Math.min(0.25, Math.max(1e-4, dt));
    const view = duel.active ? duel.view : null;
    const me = view ? view.players[view.slot] ?? null : null;
    frame.visibility = viewmodelVisibility({
      eyeOn,
      firstShare: runtime.shoulder.firstShare,
      thirdDistance: runtime.shoulder.actual,
      duelFirstShare: duel.active ? duel.camera.firstShare : null,
    });
    frame.deck = deck;
    frame.reduced = runtime.view.reduced;
    frame.player = me;
    frame.frozen = duel.active && duel.phase !== "running";
    if (me) {
      frame.speed = me.speed;
      frame.x = me.x;
      frame.y = duel.floorY;
      frame.z = me.z;
      vm.shot(duel.ownShots, duel.lastShotAds);
      last.current.primed = false;
    } else {
      const pose = runtime.poses.get(commanderId);
      if (pose) {
        const l = last.current;
        const moved = l.primed ? Math.hypot(pose.x - l.x, pose.z - l.z) : 0;
        // A jump (a lift ride, a duel's end) is not a walk.
        const speed = moved > 1 ? 0 : moved / step;
        frame.speed += (speed - frame.speed) * Math.min(1, step / 0.08);
        l.x = pose.x;
        l.z = pose.z;
        l.primed = true;
        frame.x = pose.x;
        frame.y = pose.y;
        frame.z = pose.z;
      } else {
        frame.speed = 0;
      }
    }
    vm.set(frame);
  }, 0);

  return null;
}
