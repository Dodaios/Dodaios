/**
 * The stations in the world. Nothing floats over the floor: the object in the
 * room is the station. Each one gets an invisible click target the size of
 * its object (so it stays usable from the overview, walking is optional) and
 * a thin rim on the object itself while the person stands at it, points at
 * it or has it open. The one prompt that names it lives in the HUD.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import type { Mesh, Object3D } from "three";
import type { OfficeLayout } from "./officeLayout";
import { sameSelection, useOfficeStore, type Selection } from "./officeStore";
import { stationsFor, type Station } from "./stations";
import { attachRim, attachedTo, createRimMaterial, detachRim, rimTargets } from "./stationRim";

/** The rim at full strength, and how fast it fades in and out (per second, exponential). */
const RIM_OPACITY = 0.92;
const RIM_FADE = 12;
/** While lit, look this often (frames) whether the object was rebuilt under the rim. */
const RIM_CHECK_FRAMES = 30;

function StationRim({ objects, lit, animate }: { objects: readonly string[]; lit: boolean; animate: boolean }) {
  const scene = useThree((s) => s.scene);
  const invalidate = useThree((s) => s.invalidate);
  const material = useMemo(createRimMaterial, []);
  const worn = useRef<{ roots: Object3D[]; shells: Mesh[] }>({ roots: [], shells: [] });
  const frames = useRef(0);
  const names = objects.join("|");

  const takeOff = () => {
    detachRim(worn.current.shells);
    worn.current = { roots: [], shells: [] };
  };
  useEffect(() => () => { takeOff(); material.dispose(); }, [material]);
  // Another object under the same station (a rebuilt floor plan): start clean.
  useEffect(() => takeOff, [names]);
  // A paused or on-demand canvas still has to draw the change.
  useEffect(() => { invalidate(); }, [lit, invalidate]);

  useFrame((_, delta) => {
    const uniform = material.uniforms.rimOpacity;
    const goal = lit ? RIM_OPACITY : 0;
    if (uniform.value !== goal) {
      uniform.value = animate ? uniform.value + (goal - uniform.value) * (1 - Math.exp(-RIM_FADE * Math.min(delta, 0.1))) : goal;
      if (Math.abs(uniform.value - goal) < 0.01) uniform.value = goal;
      invalidate();
    }
    const state = worn.current;
    if (!lit) {
      if (uniform.value === 0 && state.shells.length > 0) takeOff();
      frames.current = 0;
      return;
    }
    // Dress the object on the first lit frame, then look now and then whether it was rebuilt under the rim.
    const first = frames.current === 0;
    frames.current += 1;
    if (!first && frames.current % RIM_CHECK_FRAMES !== 0) return;
    const intact = state.roots.length > 0 && state.roots.every((root) => attachedTo(root, scene))
      && state.roots.reduce((sum, root) => sum + rimTargets(root).length, 0) === state.shells.length;
    if (intact) return;
    takeOff();
    const roots = objects.map((name) => scene.getObjectByName(name)).filter((root): root is Object3D => !!root);
    worn.current = { roots, shells: roots.flatMap((root) => attachRim(root, material)) };
  });
  return null;
}

function StationObject({ station, lit, animate }: { station: Station; lit: boolean; animate: boolean }) {
  const hovered = useRef(false);
  const leave = () => {
    if (!hovered.current) return;
    hovered.current = false;
    document.body.style.cursor = "";
    const store = useOfficeStore.getState();
    if (sameSelection(store.hover, station.selection)) store.setHover(null);
  };
  // Never leave a pointer cursor or a stale hover behind when the station goes away under the mouse.
  useEffect(() => leave, []); // eslint-disable-line react-hooks/exhaustive-deps

  const onClick = (event: ThreeEvent<MouseEvent>) => {
    // A drag that ends on the object turned the camera; only a real click uses it.
    if (event.delta > 6) return;
    event.stopPropagation();
    useOfficeStore.getState().select(station.selection);
  };
  const onPointerOver = (event: ThreeEvent<PointerEvent>) => {
    event.stopPropagation();
    hovered.current = true;
    document.body.style.cursor = "pointer";
    useOfficeStore.getState().setHover(station.selection);
  };

  return (
    <group name={`station:${station.key}`}>
      {station.hits.map((box, i) => (
        <mesh key={i} position={[box.x, box.y, box.z]} rotation={[0, box.rotationY, 0]} visible={false}
          onClick={onClick} onPointerOver={onPointerOver} onPointerOut={leave}>
          <boxGeometry args={[box.w, box.h, box.d]} />
        </mesh>
      ))}
      {station.objects.length > 0 && <StationRim objects={station.objects} lit={lit} animate={animate} />}
    </group>
  );
}

export function StationObjects({ layout, nearby, selection, animate }: {
  layout: OfficeLayout; nearby: Selection | null; selection: Selection | null; animate: boolean;
}) {
  const stations = useMemo(() => stationsFor(layout), [layout]);
  const hover = useOfficeStore((s) => s.hover);
  return (
    <>
      {stations.map((station) => (
        <StationObject key={station.key} station={station} animate={animate}
          lit={sameSelection(nearby, station.selection) || sameSelection(hover, station.selection) || sameSelection(selection, station.selection)} />
      ))}
    </>
  );
}
