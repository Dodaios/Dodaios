/**
 * The holodeck on screen, beyond the shared kit: the arch, a soft pulse that
 * runs through the gold grid from the program spot, and over every emitter a
 * hovering holographic cabinet (a translucent cyan body with gold edges,
 * scan lines, a flicker, the game's title and its two-frame attract loop).
 * Reduced motion holds everything still.
 */
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import {
  AdditiveBlending, BoxGeometry, Color, CylinderGeometry, DoubleSide, EdgesGeometry, Group, LineBasicMaterial, LineSegments,
  Matrix4, Mesh, MeshBasicMaterial, PlaneGeometry, ShaderMaterial, Shape, ShapeGeometry, Vector3, type BufferGeometry, type Material,
} from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { arcadeGame, type ArcadeGameInfo } from "../../../arcade/arcadeGames";
import type { DeckSceneProps } from "../registry";
import type { DeckPlan, Prop, Vec2 } from "../../plan/types";
import { GeoBatch } from "../../render/kit/geo";
import { castsShadow, finishMaterial, receivesShadow } from "../../render/kit/materials";
import { SHIP } from "../../render/kit/palette";
import { textPlane } from "../../render/deck/DeckScene";
import { clipPolygon } from "../../render/deck/structure";
import { AttractAtlas } from "./attract";
import { buildArch, LENS_Y } from "./holodeckProps";
import { PROGRAM_SPOT } from "./holodeckPlan";

export function HolodeckScene({ plan, reduced }: DeckSceneProps) {
  return (
    <>
      <HolodeckFittings plan={plan} />
      <GridPulse plan={plan} reduced={reduced} />
      <HoloCabinets plan={plan} reduced={reduced} />
    </>
  );
}

/** The arch: static, merged like the rest of the deck. */
function HolodeckFittings({ plan }: { plan: DeckPlan }) {
  const meshes = useMemo(() => {
    const door = plan.doors.find((d) => d.id === "holo-arch");
    if (!door) return [];
    const batch = new GeoBatch();
    // The arch belongs to its bulkhead: it sinks with it in the cut-away.
    buildArch(batch.frame(new Matrix4().setPosition(door.at.x, 0, door.at.z), { ax: plan.bounds.x0, az: door.at.z, bx: plan.bounds.x1, bz: door.at.z, kind: 2 }));
    return batch.merged().map(({ finish, geometry }) => {
      const mesh = new Mesh(geometry, finishMaterial(finish));
      mesh.castShadow = castsShadow(finish);
      mesh.receiveShadow = receivesShadow(finish);
      mesh.raycast = () => undefined;
      return mesh;
    });
  }, [plan]);
  useEffect(() => () => { for (const m of meshes) m.geometry.dispose(); }, [meshes]);
  return <>{meshes.map((m, i) => <primitive key={i} object={m} />)}</>;
}

// ── the grid pulse ────────────────────────────────────────────────────

const WORLD_VERT = /* glsl */ `varying vec3 vWorld; varying vec2 vUv;
  void main() { vUv = uv; vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }`;

const PULSE_FRAG = /* glsl */ `uniform float uTime; uniform float uMotion; uniform vec2 uCentre; uniform vec3 uGold;
  varying vec3 vWorld;
  void main() {
    vec2 p = vWorld.xz;
    vec2 g = abs(fract(p + 0.5) - 0.5);
    vec2 w = fwidth(p) * 1.2 + 0.012;
    float line = max(1.0 - smoothstep(0.0, w.x, g.x), 1.0 - smoothstep(0.0, w.y, g.y));
    float d = length(p - uCentre);
    // A wide, slow ring that leaves the program spot every few seconds.
    float wave = exp(-pow(mod(d - uTime * 2.4, 16.0) - 2.0, 2.0) * 0.35) * uMotion;
    float spot = exp(-pow((d - 1.7) * 5.0, 2.0));
    float fall = 1.0 - smoothstep(4.0, 22.0, d) * 0.6;
    gl_FragColor = vec4(uGold * (line * (0.05 + wave * 0.5) * fall + spot * 0.22), 1.0);
  }`;

/** A flat polygon on the floor (y = 0), in world coordinates. */
function floorPolygon(points: readonly Vec2[]): BufferGeometry {
  const shape = new Shape(points.map((p) => ({ x: p.x, y: -p.z }) as never));
  const g = new ShapeGeometry(shape);
  g.rotateX(-Math.PI / 2);
  return g;
}

function GridPulse({ plan, reduced }: { plan: DeckPlan; reduced: boolean }) {
  const room = plan.rooms.find((r) => r.kind === "holodeck");
  const geometry = useMemo(() => {
    if (!room) return null;
    const r = room.rect;
    const poly = clipPolygon([{ x: r.x0, z: r.z0 }, { x: r.x1, z: r.z0 }, { x: r.x1, z: r.z1 }, { x: r.x0, z: r.z1 }], plan.hull);
    return poly.length >= 3 ? floorPolygon(poly) : null;
  }, [room, plan.hull]);
  const material = useMemo(() => new ShaderMaterial({
    vertexShader: WORLD_VERT, fragmentShader: PULSE_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false,
    uniforms: {
      uTime: { value: 0 }, uMotion: { value: 1 }, uCentre: { value: [PROGRAM_SPOT.x, PROGRAM_SPOT.z] },
      uGold: { value: new Color(SHIP.gold).multiplyScalar(1.6) },
    },
  }), []);
  useEffect(() => () => { geometry?.dispose(); }, [geometry]);
  useEffect(() => () => material.dispose(), [material]);
  useFrame(({ clock }) => {
    material.uniforms.uTime.value = reduced ? 0 : clock.elapsedTime;
    material.uniforms.uMotion.value = reduced ? 0 : 1;
  });
  if (!geometry) return null;
  return <mesh geometry={geometry} material={material} position={[0, 0.03, 0]} renderOrder={1} raycast={() => undefined} />;
}

// ── the holographic cabinets ──────────────────────────────────────────

const BODY_VERT = /* glsl */ `varying vec3 vWorld; varying vec3 vNormal; varying vec2 vUv;
  void main() {
    vUv = uv; vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz;
    vNormal = normalize(mat3(modelMatrix) * normal);
    gl_Position = projectionMatrix * viewMatrix * w;
  }`;

const BODY_FRAG = /* glsl */ `uniform float uTime; uniform float uFlicker; uniform vec3 uColour;
  varying vec3 vWorld; varying vec3 vNormal; varying vec2 vUv;
  void main() {
    vec3 view = normalize(cameraPosition - vWorld);
    float rim = pow(1.0 - abs(dot(normalize(vNormal), view)), 2.0);
    vec2 e = abs(vUv * 2.0 - 1.0);
    float edge = smoothstep(0.86, 1.0, max(e.x, e.y));
    float scan = 0.7 + 0.3 * sin(vWorld.y * 110.0 - uTime * 6.0);
    float sweep = exp(-pow((fract(vWorld.y * 0.45 - uTime * 0.28) - 0.5) * 9.0, 2.0));
    vec3 c = uColour * (0.07 + rim * 0.35 + edge * 0.55 + sweep * 0.22) * scan * uFlicker;
    gl_FragColor = vec4(c, 1.0);
  }`;

const SCREEN_FRAG = /* glsl */ `uniform sampler2D uMap; uniform vec4 uCell; uniform float uFrame; uniform float uTime; uniform float uFlicker; uniform vec3 uTint;
  varying vec3 vWorld; varying vec2 vUv;
  void main() {
    vec2 uv = vec2(uCell.x + (vUv.x + uFrame) * uCell.z, uCell.y + vUv.y * uCell.w);
    vec3 px = texture2D(uMap, uv).rgb;
    float scan = 0.72 + 0.28 * sin(vUv.y * 140.0 - uTime * 4.0);
    vec2 e = abs(vUv * 2.0 - 1.0);
    float frame = smoothstep(0.9, 1.0, max(e.x, e.y));
    gl_FragColor = vec4((px * 1.7 * scan + uTint * (0.05 + frame * 0.6)) * uFlicker, 1.0);
  }`;

const BEAM_FRAG = /* glsl */ `uniform float uFlicker; uniform vec3 uColour; varying vec2 vUv;
  void main() {
    float fade = smoothstep(0.0, 0.25, vUv.y) * (1.0 - smoothstep(0.6, 1.0, vUv.y));
    gl_FragColor = vec4(uColour * fade * 0.28 * uFlicker, 1.0);
  }`;

/** The cabinet's silhouette in its own frame: foot at y = 0, the screen side towards +z. */
const SHAPE = [
  { w: 0.74, h: 0.86, d: 0.6, y: 0, z: -0.04, pitch: 0 },
  { w: 0.8, h: 0.07, d: 0.34, y: 0.86, z: 0.18, pitch: 0.2 },
  { w: 0.74, h: 0.8, d: 0.5, y: 0.93, z: -0.09, pitch: 0 },
  { w: 0.8, h: 0.22, d: 0.46, y: 1.73, z: -0.07, pitch: 0 },
] as const;
const SCREEN = { w: 0.58, h: 0.44, y: 1.34, z: 0.165, tilt: -0.1 } as const;
const HOVER = LENS_Y + 0.12;
const TITLE_Y = 2.28;

function silhouette(): { fill: BufferGeometry; edges: BufferGeometry } {
  const fills: BufferGeometry[] = [], edges: BufferGeometry[] = [];
  for (const s of SHAPE) {
    const box = new BoxGeometry(s.w, s.h, s.d);
    box.translate(0, s.h / 2, 0);
    const m = new Matrix4().makeRotationX(s.pitch).setPosition(0, s.y, s.z);
    box.applyMatrix4(m);
    fills.push(box);
    edges.push(new EdgesGeometry(box));
  }
  const fill = mergeGeometries(fills, false) as BufferGeometry;
  const edge = mergeGeometries(edges, false) as BufferGeometry;
  for (const g of [...fills, ...edges]) g.dispose();
  return { fill, edges: edge };
}

interface Cabinet {
  game: ArcadeGameInfo;
  group: Group;
  hover: Group;
  title: Mesh;
  body: ShaderMaterial;
  screen: ShaderMaterial;
  beam: ShaderMaterial;
  edges: LineBasicMaterial;
  seed: number;
}

/** Deterministic noise in [0, 1). */
function noise(n: number): number {
  const s = Math.sin(n * 127.1) * 43758.5453;
  return s - Math.floor(s);
}

function HoloCabinets({ plan, reduced }: { plan: DeckPlan; reduced: boolean }) {
  const atlas = useMemo(() => new AttractAtlas(), []);
  const shared = useMemo(() => ({ ...silhouette(), screen: new PlaneGeometry(SCREEN.w, SCREEN.h), beam: new CylinderGeometry(0.46, 0.21, HOVER - LENS_Y + 0.08, 28, 1, true) }), []);
  const cabinets = useMemo(() => plan.props
    .filter((p): p is Prop & { ref: string } => p.kind === "cabinet" && !!p.ref && !!arcadeGame(p.ref))
    .map((p, i): Cabinet => {
      const game = arcadeGame(p.ref) as ArcadeGameInfo;
      const group = new Group();
      group.position.set(p.x, 0, p.z);
      group.rotation.y = p.yaw;
      const hover = new Group();
      hover.position.y = HOVER;
      group.add(hover);
      const holo = { transparent: true, blending: AdditiveBlending, depthWrite: false, side: DoubleSide } as const;
      const body = new ShaderMaterial({ ...holo, vertexShader: BODY_VERT, fragmentShader: BODY_FRAG,
        uniforms: { uTime: { value: 0 }, uFlicker: { value: 1 }, uColour: { value: new Color(SHIP.cyan).multiplyScalar(0.42) } } });
      const fill = new Mesh(shared.fill, body);
      fill.renderOrder = 3;
      hover.add(fill);
      const edges = new LineBasicMaterial({ color: new Color(SHIP.gold).multiplyScalar(1.15), transparent: true, opacity: 0.85, blending: AdditiveBlending, depthWrite: false, toneMapped: false });
      const lines = new LineSegments(shared.edges, edges);
      lines.renderOrder = 3;
      hover.add(lines);
      const [u0, v0, du, dv] = atlas.cell(game.id);
      const screen = new ShaderMaterial({ ...holo, vertexShader: WORLD_VERT, fragmentShader: SCREEN_FRAG,
        uniforms: {
          uMap: { value: atlas.texture }, uCell: { value: [u0, v0, du, dv] }, uFrame: { value: 0 }, uTime: { value: 0 }, uFlicker: { value: 1 },
          uTint: { value: new Color(game.look.accent) },
        } });
      const face = new Mesh(shared.screen, screen);
      face.position.set(0, SCREEN.y, SCREEN.z);
      face.rotation.x = SCREEN.tilt;
      face.renderOrder = 4;
      hover.add(face);
      const beam = new ShaderMaterial({ ...holo, vertexShader: WORLD_VERT, fragmentShader: BEAM_FRAG,
        uniforms: { uFlicker: { value: 1 }, uColour: { value: new Color(SHIP.cyan).multiplyScalar(0.55) } } });
      const cone = new Mesh(shared.beam, beam);
      cone.position.y = LENS_Y + (HOVER - LENS_Y + 0.08) / 2;
      cone.renderOrder = 2;
      group.add(cone);
      const title = textPlane(game.title, game.look.marqueeText, { size: 0.24 });
      title.position.y = TITLE_Y;
      title.renderOrder = 5;
      group.add(title);
      for (const o of [fill, lines, face, cone]) o.raycast = () => undefined;
      return { game, group, hover, title, body, screen, beam, edges, seed: i * 1.37 + 0.4 };
    }), [plan, atlas, shared]);

  useEffect(() => () => {
    for (const c of cabinets) {
      for (const m of [c.body, c.screen, c.beam, c.edges] as Material[]) m.dispose();
      const tm = c.title.material as MeshBasicMaterial;
      tm.map?.dispose(); tm.dispose(); c.title.geometry.dispose();
    }
  }, [cabinets]);
  useEffect(() => () => {
    shared.fill.dispose(); shared.edges.dispose(); shared.screen.dispose(); shared.beam.dispose();
    atlas.dispose();
  }, [shared, atlas]);

  const at = useMemo(() => new Vector3(), []);
  useFrame(({ camera, clock }) => {
    const t = reduced ? 0 : clock.elapsedTime;
    for (const c of cabinets) {
      // A steady shimmer with a rare drop-out, each cabinet on its own beat.
      let flicker = 1;
      if (!reduced) {
        flicker = 0.92 + 0.08 * Math.sin(t * 13 + c.seed * 5) * Math.sin(t * 7.3 + c.seed);
        if (noise(Math.floor(t * 9) + c.seed * 31) > 0.985) flicker *= 0.45;
      }
      c.hover.position.y = HOVER + (reduced ? 0 : Math.sin(t * 1.3 + c.seed) * 0.022);
      c.body.uniforms.uTime.value = t;
      c.body.uniforms.uFlicker.value = flicker;
      c.screen.uniforms.uTime.value = t;
      c.screen.uniforms.uFlicker.value = flicker;
      c.screen.uniforms.uFrame.value = reduced ? 0 : Math.floor(t * 2 + c.seed) % 2;
      c.beam.uniforms.uFlicker.value = flicker;
      c.edges.opacity = 0.85 * flicker;
      (c.title.material as MeshBasicMaterial).opacity = flicker;
      c.title.getWorldPosition(at);
      c.title.lookAt(camera.position.x, at.y, camera.position.z);
    }
  });

  return <>{cabinets.map((c) => <primitive key={c.game.id} object={c.group} />)}</>;
}
