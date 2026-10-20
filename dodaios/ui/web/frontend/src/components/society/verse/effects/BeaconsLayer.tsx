/**
 * Where the crew is and how they are, readable at any zoom:
 *
 * - a status beacon above each crew member's head: steady green on duty,
 *   slow amber pulse when they need the commander, red pulse on a fault
 *   (colours from the rank system's duty table);
 * - a thin ring on the floor at every crew member's feet, in the same colour
 *   (a quiet grey off duty), so the crew can be found from the overview of a
 *   large deck.
 *
 * Both keep a constant few pixels on screen and are drawn over everything, so
 * neither is lost behind a console; the x-ray silhouette shows whose it is.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { CanvasTexture, Group, Mesh, MeshBasicMaterial, RingGeometry, Sprite, SpriteMaterial, type Texture } from "three";
import type { StageRuntime } from "../runtime";
import { DUTY, type DutyStatus } from "../ranks";
import { RENDER_ORDER } from "../engine/renderOrder";

/** Beacon diameter on screen, CSS pixels. */
const SIZE_PX = 9;
/** Floor ring diameter on screen, CSS pixels. */
const RING_PX = 10;
/** Ring colour of a member with no beacon (off duty, stood down). */
const QUIET: Readonly<Record<DutyStatus, string>> = { working: "", waiting: "", error: "", idle: "#c4ccd4", paused: "#7d868f" };

function dotTexture(): Texture {
  const s = 32;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = s;
  const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
  const g = ctx.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.38, "rgba(255,255,255,1)");
  g.addColorStop(0.5, "rgba(255,255,255,0.35)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, s, s);
  return new CanvasTexture(canvas);
}

interface Marks {
  beacon: Sprite;
  ring: Mesh<RingGeometry, MeshBasicMaterial>;
  shade: Mesh<RingGeometry, MeshBasicMaterial>;
  /** The colours last handed to the materials: a CSS colour is parsed only when it changes. */
  beaconColour: string | null;
  ringColour: string | null;
  /** The last frame this member was drawn in. */
  frame: number;
}

/** A floor ring is seen at the camera's 60° pitch: scale it up so it reads at its size on screen. */
const FLOOR_SQUASH = Math.sin(Math.PI / 3);

export function BeaconsLayer({ runtime, statuses, reduced }: { runtime: StageRuntime; statuses: ReadonlyMap<string, DutyStatus>; reduced: boolean }) {
  const scene = useThree((s) => s.scene);
  const texture = useMemo(dotTexture, []);
  // A unit ring (diameter 1) lying on the floor, and a dark backing a little wider for contrast on bright floors.
  const ringGeometry = useMemo(() => new RingGeometry(0.36, 0.5, 40).rotateX(-Math.PI / 2), []);
  const shadeGeometry = useMemo(() => new RingGeometry(0.3, 0.58, 40).rotateX(-Math.PI / 2), []);
  const group = useMemo(() => new Group(), []);
  const marks = useRef(new Map<string, Marks>());
  const frame = useRef(0);
  const statusRef = useRef(statuses);
  statusRef.current = statuses;

  useEffect(() => {
    scene.add(group);
    const own = marks.current;
    return () => {
      scene.remove(group);
      for (const m of own.values()) { m.beacon.material.dispose(); m.ring.material.dispose(); m.shade.material.dispose(); }
      own.clear();
      texture.dispose();
      ringGeometry.dispose();
      shadeGeometry.dispose();
    };
  }, [group, scene, texture, ringGeometry, shadeGeometry]);

  useFrame(() => {
    const t = performance.now() / 1000;
    const worldPerPx = 1 / Math.max(1e-3, runtime.view.current.scale);
    const stamp = ++frame.current;
    for (const [id, status] of statusRef.current) {
      const style = DUTY[status];
      const pose = runtime.poses.get(id);
      if (!pose) continue;
      let m = marks.current.get(id);
      if (!m) {
        const flat = (color: string, opacity: number) => new MeshBasicMaterial({ color, transparent: true, opacity, depthTest: false, depthWrite: false, toneMapped: false });
        m = {
          beacon: new Sprite(new SpriteMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false, toneMapped: false })),
          ring: new Mesh(ringGeometry, flat("#ffffff", 0.9)),
          shade: new Mesh(shadeGeometry, flat("#05070a", 0.45)),
          beaconColour: null,
          ringColour: null,
          frame: 0,
        };
        m.beacon.renderOrder = RENDER_ORDER.beacon;
        m.ring.renderOrder = RENDER_ORDER.beacon - 1;
        m.shade.renderOrder = RENDER_ORDER.beacon - 2;
        marks.current.set(id, m);
        group.add(m.beacon, m.shade, m.ring);
      }
      m.frame = stamp;
      // A slow breath for the statuses that want attention; steady otherwise.
      const breath = style.pulse && !reduced ? 0.55 + 0.45 * (0.5 + 0.5 * Math.sin(t * Math.PI * 1.1)) : 0.95;
      m.beacon.visible = !!style.beacon;
      if (style.beacon) {
        if (m.beaconColour !== style.beacon) { m.beacon.material.color.set(style.beacon); m.beaconColour = style.beacon; }
        m.beacon.material.opacity = breath;
        m.beacon.position.set(pose.x, pose.y + pose.height + 0.22, pose.z);
        m.beacon.scale.setScalar(SIZE_PX * worldPerPx);
      }
      const ringColour = style.beacon ?? QUIET[status];
      if (m.ringColour !== ringColour) { m.ring.material.color.set(ringColour); m.ringColour = ringColour; }
      m.ring.material.opacity = style.beacon ? Math.max(0.7, breath) : 0.75;
      // The ring lies on the floor; on screen it is foreshortened like the floor itself.
      const size = (RING_PX * worldPerPx) / FLOOR_SQUASH;
      m.ring.position.set(pose.x, pose.y + 0.02, pose.z);
      m.ring.scale.setScalar(size);
      m.shade.position.set(pose.x, pose.y + 0.02, pose.z);
      m.shade.scale.setScalar(size);
    }
    for (const [id, m] of marks.current) {
      if (m.frame === stamp) continue;
      group.remove(m.beacon, m.ring, m.shade);
      m.beacon.material.dispose();
      m.ring.material.dispose();
      m.shade.material.dispose();
      marks.current.delete(id);
    }
  });

  return null;
}
