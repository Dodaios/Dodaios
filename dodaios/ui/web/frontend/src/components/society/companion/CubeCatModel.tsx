/**
 * The cube cat, played from the clips in its GLB. An explicit `clip` (the
 * pets page asks for `run`) wins; otherwise the owner's ground speed picks
 * idle, walk or run.
 */
import { useEffect, useMemo, useRef } from "react";
import { useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { AnimationMixer, Box3, LoopRepeat, type AnimationAction, type Mesh } from "three";
import cubeCatUrl from "@/assets/pets/cube-cat.glb";
import { cubeClipFor } from "./cubeCat";
import type { PetDrive } from "./PetModel";

useGLTF.preload(cubeCatUrl);

export function CubeCatModel({ url = cubeCatUrl, clip, drive, reduced, paused, heightM }: {
  /** The GLB. The cube cat's bundled file when a pack does not say. */
  url?: string;
  /** Force one clip. Omit it and the cat follows `drive` speed. */
  clip?: string;
  drive?: { current: PetDrive };
  reduced: boolean;
  paused: boolean;
  /** How tall the model should stand, metres. */
  heightM: number;
}) {
  const gltf = useGLTF(url);
  const rig = useMemo(() => {
    const model = gltf.scene.clone(true);
    model.traverse((object) => {
      if ((object as Mesh).isMesh) (object as Mesh).castShadow = true;
    });
    const mixer = new AnimationMixer(model);
    const actions = new Map<string, AnimationAction>();
    for (const animation of gltf.animations) {
      const action = mixer.clipAction(animation);
      action.loop = LoopRepeat;
      action.clampWhenFinished = false;
      actions.set(animation.name, action);
    }
    const box = new Box3().setFromObject(model);
    const height = Math.max(0.001, box.max.y - box.min.y);
    const centerX = (box.min.x + box.max.x) / 2;
    const centerZ = (box.min.z + box.max.z) / 2;
    return { model, mixer, actions, height, minY: box.min.y, centerX, centerZ };
  }, [gltf]);
  useEffect(() => () => {
    rig.mixer.stopAllAction();
    rig.mixer.uncacheRoot(rig.model);
  }, [rig]);

  const playing = useRef("");
  useFrame((_, dt) => {
    const wanted = reduced ? "static" : (clip ?? cubeClipFor(drive?.current.speed ?? 0, false));
    let switched = false;
    if (wanted !== playing.current) {
      const previous = rig.actions.get(playing.current);
      const next = rig.actions.get(wanted) ?? rig.actions.get("idle");
      if (next) {
        next.reset();
        if (previous) {
          next.fadeIn(0.15);
          previous.fadeOut(0.15);
        }
        next.play();
        playing.current = wanted;
        switched = true;
      }
    }
    if (!paused && !reduced) rig.mixer.update(Math.min(dt, 0.05));
    else if (switched) rig.mixer.update(0);
  });

  const scale = heightM / rig.height;
  return (
    <group scale={scale}>
      <group position={[-rig.centerX, -rig.minY, -rig.centerZ]}>
        <primitive object={rig.model} dispose={null} />
      </group>
    </group>
  );
}
