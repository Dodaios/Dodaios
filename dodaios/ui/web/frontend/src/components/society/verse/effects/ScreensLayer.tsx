/**
 * Live screens on the deck's screen sockets: a canvas texture on the exact
 * quad the cook exported, nudged 2 cm toward the viewer so it sits on the
 * glass of the photographed monitor. Redrawn only when what it shows changes
 * (and for the cursor blink), a few screens per frame at most.
 *
 * Two kinds of screen: a text face (a bridge console, a standby page) and a
 * terminal face, which draws coding panes cell for cell from the IDE's own
 * xterm buffers (lib/liveTerminals), falling back to the server's plain
 * replay for a pane the IDE has not mounted.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { BufferAttribute, BufferGeometry, CanvasTexture, Group, LinearFilter, Mesh, MeshBasicMaterial, Raycaster, SRGBColorSpace, Vector3, type Object3D } from "three";
import { liveTerminal } from "@/lib/liveTerminals";
import { themeFor } from "@/components/agentic/terminalThemes";
import type { Deck, Socket } from "../content/deck";
import { BACKDROP_LAYER, RENDER_ORDER } from "../engine/renderOrder";
import { cameraBasis } from "../engine/plateMath";
import { paintScreen, screenCanvasSize, type ScreenFace } from "./screenPainter";
import { paintTerminalGrid, snapshotText, snapshotXterm, type GridTile, type TerminalFace, type TerminalTileFace } from "./terminalCanvas";

const LIFT_M = 0.02;
/** Never push a screen further toward the camera than this to clear its console's occluder. */
const MAX_CLEARANCE_M = 1.5;
const BLINK_MS = 560;
const MAX_PAINTS_PER_FRAME = 3;
/** A terminal screen repaints at most this often, however fast its pane streams. */
const TERMINAL_MIN_MS = 90;
/** Canvas pixels per metre for terminal screens, bounded by the texture limits below. */
const TERMINAL_PX_PER_M = 820;
const TERMINAL_MAX_W = 2048, TERMINAL_MAX_H = 1024;
const TERMINAL_BLEED_M = 0.015;

export type ScreenView = ScreenFace | TerminalFace;

export function isTerminalFace(view: ScreenView): view is TerminalFace {
  return (view as TerminalFace).kind === "terminals";
}

interface Screen {
  socket: Socket;
  mesh: Mesh<BufferGeometry, MeshBasicMaterial>;
  ctx: CanvasRenderingContext2D;
  texture: CanvasTexture;
  /** The face last read for this screen, and the text it stands for (built once per new face, not per frame). */
  face: ScreenView | null;
  content: string;
  /** What the canvas shows now. */
  painted: string;
  paintedBlink: boolean;
  paintedAt: number;
  /** Where the quad sits in the plate view: slid out of its console's occluder toward the plate camera. */
  plateOffset: Vector3;
}

/** Everything a text face draws except the cursor blink. */
function faceContent(face: ScreenView): string {
  if (isTerminalFace(face)) return face.tiles.map((t) => `${t.header.tone}|${t.header.title}|${t.header.status}`).join("\n");
  return `${face.tone}|${face.title}|${face.status}|${face.lines.join("\n")}`;
}

/** What a terminal tile shows right now: the live buffer's version, or the replay's stamp. */
export function tileStamp(tile: TerminalTileFace): string {
  const live = liveTerminal(tile.workspaceId, tile.names);
  if (live) return `L${live.version}`;
  const f = tile.fallback;
  return f ? `F${f.at}:${f.cursor?.join(",") ?? ""}` : "-";
}

export function tileSnapshot(tile: TerminalTileFace): GridTile {
  const live = liveTerminal(tile.workspaceId, tile.names);
  if (live) return { header: tile.header, snap: snapshotXterm(live.term) };
  if (tile.fallback) return { header: tile.header, snap: snapshotText(tile.fallback, themeFor("dark")) };
  return { header: tile.header, snap: null };
}

/** Canvas size for a terminal screen of the given metres: sharp enough to read a pane when zoomed in. Pure. */
export function terminalCanvasSize(widthM: number, heightM: number): { width: number; height: number } {
  const scale = Math.min(TERMINAL_PX_PER_M, TERMINAL_MAX_W / widthM, TERMINAL_MAX_H / heightM);
  return { width: Math.max(64, Math.round(widthM * scale)), height: Math.max(32, Math.round(heightM * scale)) };
}

/** Corners of a screen, lifted off the glass along its normal and grown by `bleed` metres on every edge. Pure. */
export function screenCorners(socket: Socket, bleed = 0): [number, number, number][] | null {
  const c = socket.corners;
  if (!c || c.length !== 4) return null;
  // Normal from the corners (TL, TR, BR, BL as the viewer sees them).
  const ux = c[1][0] - c[0][0], uy = c[1][1] - c[0][1], uz = c[1][2] - c[0][2];
  const vx = c[3][0] - c[0][0], vy = c[3][1] - c[0][1], vz = c[3][2] - c[0][2];
  let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
  const len = Math.hypot(nx, ny, nz) || 1;
  // TL→TR × TL→BL points away from the viewer; flip toward them.
  nx = -nx / len; ny = -ny / len; nz = -nz / len;
  const ul = Math.hypot(ux, uy, uz) || 1, vl = Math.hypot(vx, vy, vz) || 1;
  // TL, TR, BR, BL: which way each corner moves along the screen's width and height.
  const signs = [[-1, -1], [1, -1], [1, 1], [-1, 1]];
  return c.map((q, i): [number, number, number] => {
    const su = (signs[i][0] * bleed) / ul, sv = (signs[i][1] * bleed) / vl;
    return [
      q[0] + nx * LIFT_M + ux * su + vx * sv,
      q[1] + ny * LIFT_M + uy * su + vy * sv,
      q[2] + nz * LIFT_M + uz * su + vz * sv,
    ];
  });
}

/**
 * How far a screen (TL, TR, BR, BL corners) must move toward the camera to
 * leave every occluder it sits inside. The cook's console occluders enclose
 * their monitor glass, so a screen on the glass would be hidden by its own
 * console. The plate camera is orthographic: sliding the quad along the view
 * ray changes its depth, never where it lands in the picture. The occluder
 * is not a plain box around the glass, so a grid of points is tested, not
 * just the corners.
 */
export function occluderClearance(corners: readonly [number, number, number][], toCamera: Vector3, occluders: Object3D | undefined): number {
  if (!occluders || corners.length !== 4) return 0;
  const ray = new Raycaster();
  ray.layers.set(BACKDROP_LAYER);
  ray.far = MAX_CLEARANCE_M;
  let lift = 0;
  const normal = new Vector3();
  const [tl, tr, , bl] = corners.map((c) => new Vector3(c[0], c[1], c[2]));
  const across = tr.clone().sub(tl), down = bl.clone().sub(tl);
  const steps = 6;
  for (let i = 0; i <= steps; i += 1) for (let j = 0; j <= steps; j += 1) {
    const point = tl.clone().addScaledVector(across, i / steps).addScaledVector(down, j / steps);
    ray.set(point, toCamera);
    // The cook merges every occluder box into one mesh, so count faces, not objects:
    // a face whose outward normal points toward the camera is a way out of a box.
    // The corner is clear after the last exit that comes before any entry.
    for (const hit of ray.intersectObject(occluders, true)) {
      if (!hit.face) continue;
      normal.copy(hit.face.normal).transformDirection(hit.object.matrixWorld);
      if (normal.dot(toCamera) <= 0) break;
      lift = Math.max(lift, hit.distance);
    }
  }
  return lift > 0 ? lift + 0.015 : 0;
}

function screenQuad(corners: readonly [number, number, number][]): BufferGeometry {
  const p = corners.flatMap((q) => [q[0], q[1], q[2]]);
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array(p), 3));
  g.setAttribute("uv", new BufferAttribute(new Float32Array([0, 1, 1, 1, 1, 0, 0, 0]), 2));
  g.setIndex([0, 3, 2, 0, 2, 1]);
  return g;
}

export function ScreensLayer({ deck, faces, terminalSockets, plateView = true }: {
  deck: Deck;
  faces: ReadonlyMap<string, ScreenView>;
  /** Sockets that show terminals and get a sharper canvas. */
  terminalSockets: ReadonlySet<string>;
  /**
   * Is the photographed plate the view on screen? Only there is a screen slid out of its
   * occluder; the eye-level view renders the same scene in perspective, where it stays on the glass.
   */
  plateView?: boolean;
}) {
  const scene = useThree((s) => s.scene);
  const plateViewRef = useRef(plateView);
  plateViewRef.current = plateView;
  const facesRef = useRef(faces);
  facesRef.current = faces;
  const group = useMemo(() => new Group(), []);
  // Where the next frame starts looking, so a busy screen early in the list never starves the rest.
  const startRef = useRef(0);

  const screens = useMemo(() => {
    const out: Screen[] = [];
    for (const socket of deck.sockets) {
      if (socket.kind !== "screen" || !socket.size) continue;
      // A terminal covers the photographed glass edge to edge; the cooked socket is a little inset.
      const corners = screenCorners(socket, terminalSockets.has(socket.id) ? TERMINAL_BLEED_M : 0);
      if (!corners) continue;
      const toCamera = new Vector3(...cameraBasis(deck.camera.pitchDeg).dir).negate().normalize();
      const geometry = screenQuad(corners);
      const plateOffset = toCamera.clone().multiplyScalar(occluderClearance(corners, toCamera, scene.getObjectByName("occluders")));
      const canvas = document.createElement("canvas");
      const size = terminalSockets.has(socket.id)
        ? terminalCanvasSize(socket.size[0], socket.size[1])
        : screenCanvasSize(socket.size[0], socket.size[1]);
      canvas.width = size.width;
      canvas.height = size.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) continue;
      const texture = new CanvasTexture(canvas);
      texture.colorSpace = SRGBColorSpace;
      texture.minFilter = LinearFilter;
      texture.generateMipmaps = false;
      texture.anisotropy = 8;
      const material = new MeshBasicMaterial({ map: texture, toneMapped: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -2 });
      const mesh = new Mesh(geometry, material);
      mesh.renderOrder = RENDER_ORDER.screen;
      mesh.name = `screen:${socket.id}`;
      out.push({ socket, mesh, ctx, texture, face: null, content: "", painted: "", paintedBlink: false, paintedAt: 0, plateOffset });
    }
    return out;
  }, [deck, terminalSockets, scene]);

  useEffect(() => {
    for (const s of screens) group.add(s.mesh);
    scene.add(group);
    return () => {
      scene.remove(group);
      for (const s of screens) {
        group.remove(s.mesh);
        s.mesh.geometry.dispose();
        s.mesh.material.dispose();
        s.texture.dispose();
      }
    };
  }, [screens, group, scene]);

  useFrame(() => {
    const now = performance.now();
    const plate = plateViewRef.current;
    for (const s of screens) {
      if (plate) s.mesh.position.copy(s.plateOffset); else s.mesh.position.set(0, 0, 0);
    }
    const blinkOn = Math.floor(now / BLINK_MS) % 2 === 0;
    let budget = MAX_PAINTS_PER_FRAME;
    const n = screens.length;
    for (let k = 0; k < n; k += 1) {
      const s = screens[(startRef.current + k) % n];
      const face = facesRef.current.get(s.socket.id);
      if (!face) { s.mesh.visible = false; continue; }
      s.mesh.visible = true;
      // The feed hands over a new face object only when something changed; the same one is not re-read.
      if (face !== s.face) { s.face = face; s.content = faceContent(face); }
      if (isTerminalFace(face)) {
        // Live buffers change without React knowing: their version is part of what is shown.
        const shown = `${s.content}\n${face.tiles.map(tileStamp).join(",")}`;
        if (shown === s.painted || now - s.paintedAt < TERMINAL_MIN_MS) continue;
        paintTerminalGrid(s.ctx, face.tiles.map(tileSnapshot), true);
        s.painted = shown;
        s.paintedAt = now;
      } else {
        const blink = face.cursor && blinkOn;
        if (s.content === s.painted && blink === s.paintedBlink) continue;
        paintScreen(s.ctx, face, blinkOn);
        s.painted = s.content;
        s.paintedBlink = blink;
      }
      s.texture.needsUpdate = true;
      budget -= 1;
      if (budget === 0) { startRef.current = (startRef.current + k + 1) % n; break; }
    }
  });

  return null;
}
