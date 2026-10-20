/**
 * Live screens on the deck's screen sockets: a canvas texture on the exact
 * quad the cook exported, nudged 2 cm toward the viewer so it sits on the
 * glass of the photographed monitor. Redrawn only when what it shows changes
 * (and for the cursor blink), a few screens per frame at most.
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { BufferAttribute, BufferGeometry, CanvasTexture, Group, LinearFilter, Mesh, MeshBasicMaterial, SRGBColorSpace } from "three";
import type { Deck, Socket } from "../content/deck";
import { RENDER_ORDER } from "../engine/renderOrder";
import { paintScreen, screenCanvasSize, type ScreenFace } from "./screenPainter";

const LIFT_M = 0.02;
const BLINK_MS = 560;
const MAX_PAINTS_PER_FRAME = 3;

interface Screen {
  socket: Socket;
  mesh: Mesh<BufferGeometry, MeshBasicMaterial>;
  ctx: CanvasRenderingContext2D;
  texture: CanvasTexture;
  /** The face last read for this screen, and the text it stands for (built once per new face, not per frame). */
  face: ScreenFace | null;
  content: string;
  /** What the canvas shows now. */
  painted: string;
  paintedBlink: boolean;
}

/** Everything a face draws except the cursor blink. */
function faceContent(face: ScreenFace): string {
  return `${face.tone}|${face.title}|${face.status}|${face.lines.join("\n")}`;
}

function screenQuad(socket: Socket): BufferGeometry | null {
  const c = socket.corners;
  if (!c || c.length !== 4) return null;
  // Normal from the corners (TL, TR, BR, BL as the viewer sees them).
  const ux = c[1][0] - c[0][0], uy = c[1][1] - c[0][1], uz = c[1][2] - c[0][2];
  const vx = c[3][0] - c[0][0], vy = c[3][1] - c[0][1], vz = c[3][2] - c[0][2];
  let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
  const len = Math.hypot(nx, ny, nz) || 1;
  // TL→TR × TL→BL points away from the viewer; flip toward them.
  nx = -nx / len; ny = -ny / len; nz = -nz / len;
  const p = c.flatMap((q) => [q[0] + nx * LIFT_M, q[1] + ny * LIFT_M, q[2] + nz * LIFT_M]);
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array(p), 3));
  g.setAttribute("uv", new BufferAttribute(new Float32Array([0, 1, 1, 1, 1, 0, 0, 0]), 2));
  g.setIndex([0, 3, 2, 0, 2, 1]);
  return g;
}

export function ScreensLayer({ deck, faces }: { deck: Deck; faces: ReadonlyMap<string, ScreenFace> }) {
  const scene = useThree((s) => s.scene);
  const facesRef = useRef(faces);
  facesRef.current = faces;
  const group = useMemo(() => new Group(), []);

  const screens = useMemo(() => {
    const out: Screen[] = [];
    for (const socket of deck.sockets) {
      if (socket.kind !== "screen" || !socket.size) continue;
      const geometry = screenQuad(socket);
      if (!geometry) continue;
      const canvas = document.createElement("canvas");
      const size = screenCanvasSize(socket.size[0], socket.size[1]);
      canvas.width = size.width;
      canvas.height = size.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) continue;
      const texture = new CanvasTexture(canvas);
      texture.colorSpace = SRGBColorSpace;
      texture.minFilter = LinearFilter;
      texture.generateMipmaps = false;
      const material = new MeshBasicMaterial({ map: texture, toneMapped: false, polygonOffset: true, polygonOffsetFactor: -1, polygonOffsetUnits: -2 });
      const mesh = new Mesh(geometry, material);
      mesh.renderOrder = RENDER_ORDER.screen;
      mesh.name = `screen:${socket.id}`;
      out.push({ socket, mesh, ctx, texture, face: null, content: "", painted: "", paintedBlink: false });
    }
    return out;
  }, [deck]);

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
    const blinkOn = Math.floor(performance.now() / BLINK_MS) % 2 === 0;
    let budget = MAX_PAINTS_PER_FRAME;
    for (const s of screens) {
      if (budget === 0) break;
      const face = facesRef.current.get(s.socket.id);
      if (!face) { s.mesh.visible = false; continue; }
      s.mesh.visible = true;
      // The feed hands over a new face object only when something changed; the same one is not re-read.
      if (face !== s.face) { s.face = face; s.content = faceContent(face); }
      const blink = face.cursor && blinkOn;
      if (s.content === s.painted && blink === s.paintedBlink) continue;
      paintScreen(s.ctx, face, blinkOn);
      s.texture.needsUpdate = true;
      s.painted = s.content;
      s.paintedBlink = blink;
      budget -= 1;
    }
  });

  return null;
}
