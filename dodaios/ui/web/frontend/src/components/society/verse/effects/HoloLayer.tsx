/**
 * Holo emitters: a restrained blue projection over a table — a faint light
 * pool on the emitter, a few slowly turning rings and a wire globe of the
 * ship's sector, with a soft scan travelling up through it. Additive, low
 * intensity, no bloom: it should read as light in the room, not as a sticker.
 * An emitter is lit while its table is in use (a team round at the briefing
 * table) or always (the strategy table).
 */
import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending, BufferAttribute, BufferGeometry, CircleGeometry, Color, Group, IcosahedronGeometry, LineBasicMaterial,
  LineSegments, Mesh, ShaderMaterial, WireframeGeometry,
} from "three";
import type { Socket } from "../content/deck";
import { RENDER_ORDER } from "../engine/renderOrder";

const HOLO = new Color("#5aa8e8");

function ringGeometry(radius: number, segments = 64): BufferGeometry {
  const p: number[] = [];
  for (let i = 0; i < segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    const b = ((i + 1) / segments) * Math.PI * 2;
    p.push(Math.cos(a) * radius, 0, Math.sin(a) * radius, Math.cos(b) * radius, 0, Math.sin(b) * radius);
  }
  const g = new BufferGeometry();
  g.setAttribute("position", new BufferAttribute(new Float32Array(p), 3));
  return g;
}

const poolMaterial = () => new ShaderMaterial({
  transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false,
  uniforms: { colour: { value: HOLO }, strength: { value: 0 } },
  vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
  fragmentShader: `
    uniform vec3 colour; uniform float strength; varying vec2 vUv;
    void main() {
      float r = length(vUv - 0.5) * 2.0;
      float a = smoothstep(1.0, 0.0, r) * 0.16 + smoothstep(0.98, 0.9, r) * smoothstep(0.84, 0.92, r) * 0.18;
      gl_FragColor = vec4(colour * a * strength, 1.0);
    }`,
});

interface Emitter {
  socket: Socket; group: Group; pool: Mesh<CircleGeometry, ShaderMaterial>; lines: LineBasicMaterial[]; globe: LineSegments;
  scan: LineSegments<BufferGeometry, LineBasicMaterial>; radius: number; level: number;
}

export function HoloLayer({ sockets, lit, reduced }: { sockets: readonly Socket[]; lit: ReadonlySet<string>; reduced: boolean }) {
  const scene = useThree((s) => s.scene);
  const litRef = useRef(lit);
  litRef.current = lit;

  const emitters = useMemo<Emitter[]>(() => sockets.map((socket) => {
    const radius = Math.max(0.35, typeof socket.props.radius === "number" ? socket.props.radius : (socket.size?.[0] ?? 1.2) / 2);
    const group = new Group();
    group.position.set(socket.x, socket.y, socket.z);
    const pool = new Mesh(new CircleGeometry(radius, 48), poolMaterial());
    pool.rotation.x = -Math.PI / 2;
    pool.position.y = 0.01;
    pool.renderOrder = RENDER_ORDER.holo;
    group.add(pool);
    const lines: LineBasicMaterial[] = [];
    const line = () => {
      const m = new LineBasicMaterial({ color: HOLO, transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false, toneMapped: false });
      lines.push(m);
      return m;
    };
    for (const [h, r] of [[0.08, 0.92], [0.42, 0.62], [0.78, 0.4]] as const) {
      const ring = new LineSegments(ringGeometry(radius * r), line());
      ring.position.y = h * radius;
      ring.renderOrder = RENDER_ORDER.holo;
      group.add(ring);
    }
    const globe = new LineSegments(new WireframeGeometry(new IcosahedronGeometry(radius * 0.38, 1)), line());
    globe.position.y = radius * 0.62;
    globe.renderOrder = RENDER_ORDER.holo;
    group.add(globe);
    const scan = new LineSegments(ringGeometry(radius * 0.7), new LineBasicMaterial({
      color: HOLO, transparent: true, opacity: 0, blending: AdditiveBlending, depthWrite: false, toneMapped: false,
    }));
    scan.renderOrder = RENDER_ORDER.holo;
    group.add(scan);
    return { socket, group, pool, lines, globe, scan, radius, level: 0 };
  }), [sockets]);

  useEffect(() => {
    for (const e of emitters) scene.add(e.group);
    return () => {
      for (const e of emitters) {
        scene.remove(e.group);
        e.group.traverse((o) => {
          const m = o as Mesh;
          m.geometry?.dispose();
          (m.material as { dispose?: () => void } | undefined)?.dispose?.();
        });
      }
    };
  }, [emitters, scene]);

  useFrame((_, dt) => {
    const t = performance.now() / 1000;
    for (const e of emitters) {
      const on = litRef.current.has(e.socket.id);
      // Power up and down over half a second.
      e.level = reduced ? (on ? 1 : 0) : Math.max(0, Math.min(1, e.level + (on ? dt : -dt) * 2));
      e.group.visible = e.level > 0.001;
      if (!e.group.visible) continue;
      // A faint, irregular shimmer, never a strobe.
      const shimmer = reduced ? 1 : 0.9 + 0.06 * Math.sin(t * 7.3) + 0.04 * Math.sin(t * 17.1 + e.socket.x);
      e.pool.material.uniforms.strength.value = e.level * shimmer;
      e.lines.forEach((m, i) => { m.opacity = e.level * shimmer * (i === e.lines.length - 1 ? 0.2 : 0.14); });
      if (!reduced) {
        e.globe.rotation.y = t * 0.25;
        const phase = (((t / 3.2 + e.socket.z) % 1) + 1) % 1;
        e.scan.position.y = phase * e.radius * 1.1;
        e.scan.material.opacity = e.level * 0.22 * Math.sin(phase * Math.PI);
      }
      e.scan.visible = !reduced;
    }
  });

  return null;
}
