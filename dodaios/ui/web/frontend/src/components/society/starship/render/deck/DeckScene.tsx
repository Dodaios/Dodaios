/**
 * A deck on screen: its merged architecture and furniture, the live console
 * screens, the holo-tables of the divisions, the transporter, sliding doors,
 * the room signs and the lights. Everything static is built once per plan.
 */
import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import {
  AdditiveBlending, BoxGeometry, FrontSide, BufferAttribute, CanvasTexture, Color, CylinderGeometry, DoubleSide, Group, IcosahedronGeometry,
  InstancedMesh, Matrix4, Mesh, MeshBasicMaterial, Object3D, PlaneGeometry, Quaternion, SRGBColorSpace, ShaderMaterial, Vector3,
} from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { DeckPlan, Prop, Station } from "../../plan/types";
import { GeoBatch } from "../kit/geo";
import { castsShadow, finishMaterial, receivesShadow } from "../kit/materials";
import { SHIP, STATE } from "../kit/palette";
import { buildProps, CONSOLE_SCREEN, nearestWallCut } from "./props";
import { withCutaway } from "../kit/cutaway";
import { buildStructure, WALL_H } from "./structure";
import { buildExterior } from "./exterior";
import { buildDressing } from "./dressing";
import { ScreenAtlas, type ScreenContent } from "./screens";

export function StaticDeck({ plan, extra }: { plan: DeckPlan; extra?: (batch: GeoBatch) => void }) {
  const meshes = useMemo(() => {
    const batch = buildStructure(plan);
    buildExterior(plan, batch);
    buildDressing(plan, batch);
    buildProps(plan, batch);
    extra?.(batch);
    return batch.merged().map(({ finish, geometry }) => {
      const mesh = new Mesh(geometry, finishMaterial(finish));
      mesh.castShadow = castsShadow(finish);
      mesh.receiveShadow = receivesShadow(finish);
      mesh.raycast = () => undefined;
      if (finish === "glass") mesh.renderOrder = 2;
      return mesh;
    });
  }, [plan, extra]);
  useEffect(() => () => { for (const m of meshes) m.geometry.dispose(); }, [meshes]);
  return <>{meshes.map((m, i) => <primitive key={i} object={m} />)}</>;
}

/** World matrix of a console's screen plane. */
export function screenMatrix(p: Prop): Matrix4 {
  const base = new Matrix4().makeRotationY(p.yaw).setPosition(p.x, 0, p.z);
  const local = new Matrix4().compose(new Vector3(0, CONSOLE_SCREEN.y, CONSOLE_SCREEN.z + 0.004), new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), CONSOLE_SCREEN.tilt), new Vector3(1, 1, 1));
  return base.multiply(local);
}

/**
 * The console screens: one merged mesh over one atlas. `content(prop)` says
 * what each shows; `onScreen` takes a click on one (the console's owner).
 */
const CONSOLE_KINDS: readonly Prop["kind"][] = ["console"];

export function ConsoleScreens({ plan, content, onScreen, kinds = CONSOLE_KINDS }: {
  plan: DeckPlan;
  content: (prop: Prop) => ScreenContent;
  onScreen?: (prop: Prop) => void;
  kinds?: readonly Prop["kind"][];
}) {
  const atlas = useMemo(() => new ScreenAtlas(), []);
  const consoles = useMemo(() => plan.props.filter((p) => kinds.includes(p.kind)), [plan, kinds]);
  const material = useMemo(() => new MeshBasicMaterial({ map: atlas.texture, toneMapped: false, color: new Color(1.25, 1.25, 1.25) }), [atlas]);
  const mesh = useMemo(() => {
    const geos = consoles.map((p) => {
      const g = new PlaneGeometry(CONSOLE_SCREEN.w, CONSOLE_SCREEN.h);
      const [u0, v0, u1, v1] = atlas.uv(p.id);
      const uv = g.attributes.uv as BufferAttribute;
      for (let i = 0; i < uv.count; i += 1) uv.setXY(i, u0 + uv.getX(i) * (u1 - u0), v0 + uv.getY(i) * (v1 - v0));
      g.applyMatrix4(screenMatrix(p));
      // Which console a face belongs to, for clicks.
      const ids = new Float32Array(g.attributes.position.count).fill(consoles.indexOf(p));
      g.setAttribute("consoleIndex", new BufferAttribute(ids, 1));
      return g;
    });
    const merged = geos.length ? mergeGeometries(geos, false) : null;
    for (const g of geos) g.dispose();
    if (!merged) return null;
    const m = new Mesh(merged, material);
    return m;
  }, [consoles, atlas, material]);
  useEffect(() => () => { mesh?.geometry.dispose(); }, [mesh]);
  // Cells of consoles a rebuilt plan no longer has go back to the atlas.
  const held = useRef(new Set<string>());
  useEffect(() => {
    const now = new Set(consoles.map((p) => p.id));
    for (const id of held.current) if (!now.has(id)) atlas.release(id);
    held.current = now;
  }, [consoles, atlas]);
  useEffect(() => () => { material.dispose(); atlas.texture.dispose(); }, [material, atlas]);
  const contentRef = useRef(content);
  contentRef.current = content;
  useFrame(() => {
    for (const p of consoles) atlas.set(p.id, contentRef.current(p));
    atlas.tick(Date.now());
  });
  if (!mesh) return null;
  const click = (e: ThreeEvent<MouseEvent>) => {
    if (!onScreen || e.face == null) return;
    const attr = mesh.geometry.getAttribute("consoleIndex") as BufferAttribute;
    const p = consoles[attr.getX(e.face.a)];
    if (p) { e.stopPropagation(); onScreen(p); }
  };
  return <primitive object={mesh} onClick={click} />;
}

const HOLO_VERT = /* glsl */ `varying vec2 vUv; varying vec3 vPos; void main() { vUv = uv; vPos = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
const BEAM_FRAG = /* glsl */ `uniform float uTime; uniform vec3 uColour; uniform float uStrength; varying vec2 vUv; varying vec3 vPos;
  float h(float x) { return fract(sin(x * 91.7) * 43758.5); }
  void main() {
    float a = atan(vPos.z, vPos.x) * 9.0;
    float streak = smoothstep(0.75, 1.0, h(floor(a)) ) * (0.5 + 0.5 * sin(vUv.y * 30.0 - uTime * 6.0 + floor(a)));
    float fade = smoothstep(0.0, 0.15, vUv.y) * (1.0 - smoothstep(0.55, 1.0, vUv.y));
    gl_FragColor = vec4(uColour * (0.25 + streak) * fade * uStrength, (0.08 + streak * 0.5) * fade * uStrength);
  }`;

/** The holo-tables: each division's name floating over its table, the members as lights round a turning emblem. */
export function HoloTables({ plan, label, memberState, reduced }: {
  plan: DeckPlan;
  label: (division: DeckPlan["divisions"][number]) => string;
  memberState: (agentId: string) => string;
  reduced: boolean;
}) {
  const group = useRef<Group>(null);
  const emblems = useMemo(() => plan.divisions.map((d) => {
    const g = new Group();
    g.position.set(d.centre.x, 0, d.centre.z);
    const colour = new Color(d.colour);
    const ico = new Mesh(new IcosahedronGeometry(0.34, 1), new MeshBasicMaterial({ color: colour.clone().multiplyScalar(1.6), wireframe: true, transparent: true, opacity: 0.7, toneMapped: false, depthWrite: false }));
    ico.position.y = 1.55;
    g.add(ico);
    const beam = new Mesh(new CylinderGeometry(0.62, 0.95, 1.1, 32, 1, true), new ShaderMaterial({
      vertexShader: HOLO_VERT, fragmentShader: BEAM_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false, side: DoubleSide,
      uniforms: { uTime: { value: 0 }, uColour: { value: new Color(SHIP.cyan).multiplyScalar(1.4) }, uStrength: { value: 0.7 } },
    }));
    beam.position.y = 1.5;
    g.add(beam);
    const text = textPlane(label(d), d.colour);
    text.position.y = 2.35;
    g.add(text);
    const dots = new InstancedMesh(new BoxGeometry(0.06, 0.06, 0.06), new MeshBasicMaterial({ toneMapped: false }), Math.max(1, d.members.length));
    dots.position.y = 1.08;
    g.add(dots);
    return { division: d, group: g, ico, beam, text, dots };
  }), [plan, label]);
  useEffect(() => () => {
    for (const e of emblems) e.dots.dispose();
    for (const e of emblems) e.group.traverse((o) => {
      const m = o as Mesh;
      m.geometry?.dispose();
      const mat = m.material as MeshBasicMaterial | undefined;
      mat?.map?.dispose();
      mat?.dispose();
    });
  }, [emblems]);
  const tmp = useMemo(() => new Object3D(), []);
  const c = useMemo(() => new Color(), []);
  const at = useMemo(() => new Vector3(), []);
  useFrame(({ camera, clock }) => {
    const t = reduced ? 0 : clock.elapsedTime;
    for (const e of emblems) {
      e.ico.rotation.set(t * 0.3, t * 0.5, 0);
      (e.beam.material as ShaderMaterial).uniforms.uTime.value = t;
      e.text.lookAt(camera.position.x, e.text.getWorldPosition(at).y, camera.position.z);
      const n = e.division.members.length;
      e.division.members.forEach((id, i) => {
        const a = (i / Math.max(1, n)) * Math.PI * 2 + t * 0.4;
        tmp.position.set(Math.sin(a) * 0.55, Math.sin(t * 2 + i) * 0.02, Math.cos(a) * 0.55);
        tmp.updateMatrix();
        e.dots.setMatrixAt(i, tmp.matrix);
        const s = memberState(id);
        c.set(s === "working" ? STATE.working : s === "waiting" ? STATE.waiting : s === "paused" ? STATE.paused : STATE.idle).multiplyScalar(2);
        e.dots.setColorAt(i, c);
      });
      e.dots.count = n;
      e.dots.instanceMatrix.needsUpdate = true;
      if (e.dots.instanceColor) e.dots.instanceColor.needsUpdate = true;
    }
  });
  return <group ref={group}>{emblems.map((e) => <primitive key={e.division.id} object={e.group} />)}</group>;
}

/** A label on a transparent plane (canvas text), 1 m tall per 128 px. */
export function textPlane(text: string, colour: string, opts: { size?: number; width?: number; font?: string; oneSided?: boolean } = {}): Mesh {
  const size = opts.size ?? 0.34;
  const c = document.createElement("canvas");
  const ctx = c.getContext("2d") as CanvasRenderingContext2D;
  const font = opts.font ?? "600 64px 'Space Grotesk', 'Inter Variable', sans-serif";
  ctx.font = font;
  const w = Math.min(1600, Math.ceil(ctx.measureText(text).width) + 48);
  c.width = w; c.height = 96;
  ctx.font = font;
  ctx.textBaseline = "middle";
  ctx.textAlign = "center";
  ctx.shadowColor = colour; ctx.shadowBlur = 16;
  ctx.fillStyle = "#ffffff";
  ctx.fillText(text, w / 2, 50);
  const tex = new CanvasTexture(c);
  tex.colorSpace = SRGBColorSpace;
  const mat = new MeshBasicMaterial({ map: tex, transparent: true, toneMapped: false, depthWrite: false, color: new Color(colour).lerp(new Color("#ffffff"), 0.55).multiplyScalar(1.3), side: opts.oneSided ? FrontSide : DoubleSide });
  const mesh = new Mesh(new PlaneGeometry((w / 96) * size, size), mat);
  mesh.raycast = () => undefined;
  return mesh;
}

/** Room signs over the doors and on the walls. */
export function RoomSigns({ plan, text }: { plan: DeckPlan; text: (room: DeckPlan["rooms"][number]) => string | null }) {
  const signs = useMemo(() => plan.rooms.filter((r) => r.sign && r.signAt).map((room) => {
    const label = text(room);
    if (!label) return null;
    const mesh = textPlane(label, room.accent, { size: 0.3, oneSided: true });
    const at = room.signAt!;
    // Placed in the geometry itself, so the cut-away (which works on positions) sinks it with its wall.
    mesh.geometry.applyMatrix4(new Matrix4().makeRotationY(at.yaw).setPosition(at.x + Math.sin(at.yaw) * 0.02, WALL_H - 0.32, at.z + Math.cos(at.yaw) * 0.02));
    const cut = nearestWallCut(plan, at.x, at.z, 0.8);
    const n = mesh.geometry.attributes.position.count;
    const ab = new Float32Array(n * 4), kind = new Float32Array(n);
    if (cut) for (let i = 0; i < n; i += 1) { ab.set([cut.ax, cut.az, cut.bx, cut.bz], i * 4); kind[i] = cut.kind; }
    mesh.geometry.setAttribute("cutAB", new BufferAttribute(ab, 4));
    mesh.geometry.setAttribute("cutKind", new BufferAttribute(kind, 1));
    withCutaway(mesh.material as MeshBasicMaterial, 0.14, 0.4);
    return { id: room.id, mesh };
  }).filter((s): s is { id: string; mesh: Mesh } => s !== null), [plan, text]);
  useEffect(() => () => { for (const s of signs) { s.mesh.geometry.dispose(); const m = s.mesh.material as MeshBasicMaterial; m.map?.dispose(); m.dispose(); } }, [signs]);
  return <>{signs.map((s) => <primitive key={s.id} object={s.mesh} />)}</>;
}

/** Sliding doors: two leaves per door that part as anyone comes near. */
export function SlidingDoors({ plan, bodies }: { plan: DeckPlan; bodies: () => Iterable<{ x: number; z: number }> }) {
  const doors = useMemo(() => plan.doors.filter((d) => d.slides && d.id !== "lift-door"), [plan]);
  const mesh = useMemo(() => {
    const m = new InstancedMesh(new BoxGeometry(1, 2.3, 0.08), finishMaterial("panel"), Math.max(1, doors.length * 2));
    m.castShadow = true;
    m.raycast = () => undefined;
    return m;
  }, [doors]);
  const glow = useMemo(() => {
    const m = new InstancedMesh(new BoxGeometry(1, 0.03, 0.1), finishMaterial("glow"), Math.max(1, doors.length * 2));
    m.raycast = () => undefined;
    return m;
  }, [doors]);
  useEffect(() => () => { mesh.geometry.dispose(); glow.geometry.dispose(); mesh.dispose(); glow.dispose(); }, [mesh, glow]);
  const open = useRef<number[]>([]);
  const tmp = useMemo(() => new Object3D(), []);
  const colour = useMemo(() => new Color(), []);
  useEffect(() => {
    open.current = doors.map(() => 0);
    doors.forEach((_, i) => {
      for (const k of [0, 1]) { mesh.setColorAt(i * 2 + k, colour.set(SHIP.panelCool)); glow.setColorAt(i * 2 + k, colour.set(SHIP.cyan)); }
    });
  }, [doors, mesh, glow, colour]);
  useFrame((_, dt) => {
    const near = [...bodies()];
    doors.forEach((d, i) => {
      const want = near.some((b) => Math.hypot(b.x - d.at.x, b.z - d.at.z) < 2.4) ? 1 : 0;
      const o = (open.current[i] += (want - open.current[i]) * Math.min(1, dt * 7));
      const leaf = d.width / 2;
      for (const k of [0, 1]) {
        const s = k ? 1 : -1;
        const along = s * (leaf / 2 + o * leaf * 0.92);
        tmp.position.set(d.axis === "x" ? d.at.x + along : d.at.x, 0.03 + 1.15, d.axis === "x" ? d.at.z : d.at.z + along);
        tmp.rotation.set(0, d.axis === "x" ? 0 : Math.PI / 2, 0);
        tmp.scale.set(leaf, 1, 1);
        tmp.updateMatrix();
        mesh.setMatrixAt(i * 2 + k, tmp.matrix);
        tmp.position.y = 1.4;
        tmp.scale.set(leaf * 0.7, 1, 1);
        tmp.updateMatrix();
        glow.setMatrixAt(i * 2 + k, tmp.matrix);
      }
    });
    mesh.count = glow.count = doors.length * 2;
    mesh.instanceMatrix.needsUpdate = true;
    glow.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    if (glow.instanceColor) glow.instanceColor.needsUpdate = true;
  });
  return <><primitive object={mesh} /><primitive object={glow} /></>;
}

/** The transporter's shimmer: faint at rest, a column of light while someone beams in. */
export function TransporterBeam({ at, active, reduced }: { at: { x: number; z: number }; active: boolean; reduced: boolean }) {
  const mat = useMemo(() => new ShaderMaterial({
    vertexShader: HOLO_VERT, fragmentShader: BEAM_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false, side: DoubleSide,
    uniforms: { uTime: { value: 0 }, uColour: { value: new Color("#bfeaff").multiplyScalar(1.6) }, uStrength: { value: 0.25 } },
  }), []);
  const geo = useMemo(() => new CylinderGeometry(1.7, 1.7, 3.2, 48, 1, true), []);
  useEffect(() => () => { mat.dispose(); geo.dispose(); }, [mat, geo]);
  useFrame(({ clock }, dt) => {
    mat.uniforms.uTime.value = reduced ? 0 : clock.elapsedTime;
    const goal = active ? 1.6 : 0.22;
    mat.uniforms.uStrength.value += (goal - mat.uniforms.uStrength.value) * Math.min(1, dt * 3);
  });
  return <mesh geometry={geo} material={mat} position={[at.x, 1.7, at.z]} raycast={() => undefined} />;
}

/**
 * Invisible click targets for the stations, sized to their props, so every
 * station can be used from afar.
 */
export function StationTargets({ plan, onStation, onHover }: { plan: DeckPlan; onStation: (s: Station) => void; onHover: (s: Station | null) => void }) {
  const targets = useMemo(() => plan.stations.map((s) => {
    const p = plan.props.find((q) => q.id === s.propId);
    if (!p) return null;
    return { station: s, prop: p };
  }).filter((x): x is { station: Station; prop: Prop } => x !== null), [plan]);
  return (
    <group>
      {targets.map(({ station, prop }) => (
        <mesh key={station.id} position={[prop.x, Math.max(0.6, prop.h) / 2, prop.z]} rotation={[0, prop.yaw, 0]}
          onClick={(e) => { e.stopPropagation(); onStation(station); }}
          onPointerOver={(e) => { e.stopPropagation(); onHover(station); }}
          onPointerOut={() => onHover(null)}>
          <boxGeometry args={[prop.w + 0.2, Math.max(0.6, prop.h) + 0.2, prop.d + 0.2]} />
          <meshBasicMaterial visible={false} />
        </mesh>
      ))}
    </group>
  );
}

/** A soft rim of light round the station the captain stands at. */
export function StationHalo({ plan, id }: { plan: DeckPlan; id: string | null }) {
  const station = id ? plan.stations.find((s) => s.id === id) : undefined;
  const prop = station ? plan.props.find((p) => p.id === station.propId) : undefined;
  const ring = useRef<Mesh>(null);
  useFrame(({ clock }) => {
    if (ring.current) (ring.current.material as MeshBasicMaterial).opacity = 0.55 + Math.sin(clock.elapsedTime * 3) * 0.2;
  });
  if (!prop) return null;
  const r = Math.max(prop.w, prop.d) / 2 + 0.35;
  return (
    <mesh ref={ring} position={[prop.x, 0.03, prop.z]} rotation={[-Math.PI / 2, 0, 0]} raycast={() => undefined}>
      <ringGeometry args={[r, r + 0.06, 64]} />
      <meshBasicMaterial color={new Color(SHIP.gold).multiplyScalar(2)} transparent opacity={0.7} toneMapped={false} depthWrite={false} />
    </mesh>
  );
}

