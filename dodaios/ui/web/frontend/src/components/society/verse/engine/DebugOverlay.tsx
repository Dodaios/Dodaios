/**
 * Development-only alignment overlay: every socket as a marker in the 3D
 * world (seats, screens, waypoints, stations…), screen quads as outlines, the
 * occluders as wireframes and the walkable nav cells as dots at their height.
 * If the plate and the world agree, every marker sits on its object in the
 * photograph. Toggled with F9 in a development build.
 */
import { useEffect, useMemo } from "react";
import { useThree } from "@react-three/fiber";
import {
  BufferAttribute, BufferGeometry, Color, Group, LineBasicMaterial, LineSegments, Points, PointsMaterial, WireframeGeometry,
  type Mesh, type MeshBasicMaterial, type Object3D,
} from "three";
import type { Deck, Socket } from "../content/deck";
import { DEBUG_LAYER } from "./renderOrder";

const KIND_COLOUR: Record<Socket["kind"], string> = {
  seat: "#4fa3ff", stand: "#7fd18b", screen: "#ffd166", holo: "#5ad1e6", light: "#ffffff", door: "#b08cff",
  spawn: "#ff6b6b", waypoint: "#9aa5b1", bunk: "#c7a27a", lift: "#ff9f43", station: "#ff4d6d",
};

function onDebugLayer(root: Object3D): void {
  root.traverse((o) => o.layers.set(DEBUG_LAYER));
}

function socketMarkers(deck: Deck): LineSegments {
  const positions: number[] = [];
  const colours: number[] = [];
  const add = (a: number[], b: number[], c: Color) => { positions.push(...a, ...b); colours.push(c.r, c.g, c.b, c.r, c.g, c.b); };
  for (const s of deck.sockets) {
    const c = new Color(KIND_COLOUR[s.kind]);
    if (s.corners) {
      for (let i = 0; i < 4; i++) add([...s.corners[i]], [...s.corners[(i + 1) % 4]], c);
      continue;
    }
    const r = s.kind === "station" ? 0.5 : 0.18;
    // A cross on the floor and a stem with a facing tick.
    add([s.x - r, s.y, s.z], [s.x + r, s.y, s.z], c);
    add([s.x, s.y, s.z - r], [s.x, s.y, s.z + r], c);
    add([s.x, s.y, s.z], [s.x, s.y + 0.6, s.z], c);
    add([s.x, s.y + 0.6, s.z], [s.x + Math.sin(s.yaw) * 0.35, s.y + 0.6, s.z + Math.cos(s.yaw) * 0.35], c);
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
  g.setAttribute("color", new BufferAttribute(new Float32Array(colours), 3));
  const lines = new LineSegments(g, new LineBasicMaterial({ vertexColors: true, depthTest: false, toneMapped: false }));
  lines.renderOrder = 900;
  return lines;
}

/** Every walkable cell as a dot at its floor height (sunken floors read amber). */
function navDots(deck: Deck): Points {
  const { nav } = deck;
  const positions: number[] = [];
  const colours: number[] = [];
  for (let r = 0; r < nav.rows; r++) {
    for (let c = 0; c < nav.cols; c++) {
      const i = r * nav.cols + c;
      if (!nav.walkable[i]) continue;
      const h = nav.heights[i];
      positions.push(nav.x0 + (c + 0.5) * nav.cell, h + 0.01, nav.z0 + (r + 0.5) * nav.cell);
      if (h < -0.05) colours.push(1, 0.62, 0.25);
      else colours.push(0.3, 0.85, 0.45);
    }
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array(positions), 3));
  g.setAttribute("color", new BufferAttribute(new Float32Array(colours), 3));
  const dots = new Points(g, new PointsMaterial({ size: 1.5, sizeAttenuation: false, vertexColors: true, transparent: true, opacity: 0.5, depthTest: false, toneMapped: false }));
  dots.renderOrder = 899;
  return dots;
}

export function DebugOverlay({ deck }: { deck: Deck }) {
  const scene = useThree((s) => s.scene);
  const group = useMemo(() => {
    const g = new Group();
    g.name = "verse-debug";
    g.add(navDots(deck), socketMarkers(deck));
    return g;
  }, [deck]);

  useEffect(() => {
    // Occluder wireframes, built from whatever occluders are in the scene now.
    const occluders = scene.getObjectByName("occluders");
    const wire = new Group();
    occluders?.traverse((o) => {
      const mesh = o as Mesh;
      if (!mesh.isMesh) return;
      const lines = new LineSegments(new WireframeGeometry(mesh.geometry), new LineBasicMaterial({ color: 0xff3355, depthTest: false, transparent: true, opacity: 0.55, toneMapped: false }));
      lines.renderOrder = 898;
      wire.add(lines);
    });
    group.add(wire);
    onDebugLayer(group);
    scene.add(group);
    return () => {
      scene.remove(group);
      group.remove(wire);
      group.traverse((o) => {
        const m = o as Mesh;
        m.geometry?.dispose();
        (m.material as MeshBasicMaterial | undefined)?.dispose();
      });
    };
  }, [group, scene]);

  return null;
}
