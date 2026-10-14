/**
 * The city outside the Dodaios tower: a megacity in the singularity, seen from
 * high above. Hundreds of glass towers on a street grid with lit windows,
 * light seams and crowns, avenues full of traffic, flying traffic weaving
 * round the tower above the roofs, beams of light over the tallest roofs,
 * drifting mist, and off to the north the singularity itself: a black core
 * with its photon ring, a turning accretion disc, polar jets and three
 * orbital rings, inside a crater ringed by gold-crowned spires.
 *
 * The plan is pure (cityPlan.ts), every surface a shader of its own
 * (cityShaders.ts). Everything is instanced or computed on the GPU: about
 * twenty draw calls in all, nothing casts or receives a shadow, and the only
 * per-frame work is advancing one clock, keeping the sky round the camera
 * and turning the lens and the rings. With reduced motion the clock stands.
 */
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  BufferGeometry, Color, CylinderGeometry, Euler, Float32BufferAttribute, Group, InstancedBufferAttribute, InstancedBufferGeometry,
  InstancedMesh, Matrix4, type Mesh, PlaneGeometry, Quaternion, RingGeometry, SphereGeometry, TorusGeometry, Vector3,
} from "three";
import {
  beaconMaterial, beamMaterial, CITY_PALETTE, cityUniforms, coreMaterial, discMaterial, groundMaterial, lensMaterial, mistMaterial,
  orbitalRingMaterial, skyMaterial, towerMaterial, trafficMaterial, type CityUniforms,
} from "./cityShaders";
import { CITY, GROUND_Y, lcg, planCity, SINGULARITY, TOWER_KINDS, type CityPlan, type Tower, type TowerKind } from "./cityPlan";
import type { Rect } from "./officeLayout";

/** The colour behind and below the city (the sky's deep haze): the scene's background and fog for these floors. */
export const CITY_BACKDROP = CITY_PALETTE.below;

// ---------------------------------------------------------------------------
// Tower geometry: unit towers (foot at y = 0, top at y = 1, footprint 1 × 1)
// ---------------------------------------------------------------------------

interface Builder { positions: number[]; normals: number[]; tiers: number[]; index: number[] }

function pushQuad(b: Builder, a: number[], bb: number[], c: number[], d: number[], n: number[], tier: number[]) {
  const at = b.positions.length / 3;
  b.positions.push(...a, ...bb, ...c, ...d);
  for (let i = 0; i < 4; i += 1) { b.normals.push(...n); b.tiers.push(...tier); }
  b.index.push(at, at + 1, at + 2, at, at + 2, at + 3);
}

/** A box tier from y0 to y1, half size hx × hz, with its roof; corners carry seams. */
function boxTier(b: Builder, hx: number, hz: number, y0: number, y1: number) {
  const tier = [hx, hz, y1, 1];
  pushQuad(b, [-hx, y0, hz], [hx, y0, hz], [hx, y1, hz], [-hx, y1, hz], [0, 0, 1], tier);
  pushQuad(b, [hx, y0, hz], [hx, y0, -hz], [hx, y1, -hz], [hx, y1, hz], [1, 0, 0], tier);
  pushQuad(b, [hx, y0, -hz], [-hx, y0, -hz], [-hx, y1, -hz], [hx, y1, -hz], [0, 0, -1], tier);
  pushQuad(b, [-hx, y0, -hz], [-hx, y0, hz], [-hx, y1, hz], [-hx, y1, -hz], [-1, 0, 0], tier);
  pushQuad(b, [-hx, y1, hz], [hx, y1, hz], [hx, y1, -hz], [-hx, y1, -hz], [0, 1, 0], tier);
}

/** An eight-sided prism from y0 to y1, tapering from radius r0 to r1, with a flat roof (no corner seams). */
function prismTier(b: Builder, r0: number, r1: number, y0: number, y1: number, roof: boolean) {
  const sides = 8, tier = [r1, r1, y1, 0];
  for (let i = 0; i < sides; i += 1) {
    const a0 = (i / sides) * Math.PI * 2, a1 = ((i + 1) / sides) * Math.PI * 2, am = (a0 + a1) / 2;
    const slope = (r0 - r1) / (y1 - y0);
    const n = new Vector3(Math.cos(am), slope, Math.sin(am)).normalize();
    pushQuad(b,
      [Math.cos(a1) * r0, y0, Math.sin(a1) * r0], [Math.cos(a0) * r0, y0, Math.sin(a0) * r0],
      [Math.cos(a0) * r1, y1, Math.sin(a0) * r1], [Math.cos(a1) * r1, y1, Math.sin(a1) * r1], [n.x, n.y, n.z], tier);
  }
  if (!roof) return;
  const at = b.positions.length / 3;
  b.positions.push(0, y1, 0); b.normals.push(0, 1, 0); b.tiers.push(...tier);
  for (let i = 0; i <= sides; i += 1) {
    const a = (i / sides) * Math.PI * 2;
    b.positions.push(Math.cos(a) * r1, y1, Math.sin(a) * r1); b.normals.push(0, 1, 0); b.tiers.push(...tier);
  }
  for (let i = 0; i < sides; i += 1) b.index.push(at, at + 2 + i, at + 1 + i);
}

/** A needle: eight steep sides from radius r0 at y0 to a point at y1 (its faces stay façades, not roofs). */
function needle(b: Builder, r0: number, y0: number, y1: number) {
  prismTier(b, r0, 0.002, y0, y1, false);
}

export function towerGeometry(kind: TowerKind): BufferGeometry {
  const b: Builder = { positions: [], normals: [], tiers: [], index: [] };
  if (kind === "block") boxTier(b, 0.5, 0.5, 0, 1);
  if (kind === "setback") { boxTier(b, 0.5, 0.5, 0, 0.58); boxTier(b, 0.38, 0.38, 0.58, 0.84); boxTier(b, 0.25, 0.25, 0.84, 1); }
  if (kind === "prism") prismTier(b, 0.5, 0.42, 0, 1, true);
  if (kind === "spire") { prismTier(b, 0.5, 0.4, 0, 0.8, true); prismTier(b, 0.22, 0.16, 0.8, 0.9, true); needle(b, 0.06, 0.9, 1); }
  const g = new BufferGeometry();
  g.setAttribute("position", new Float32BufferAttribute(b.positions, 3));
  g.setAttribute("normal", new Float32BufferAttribute(b.normals, 3));
  g.setAttribute("aTier", new Float32BufferAttribute(b.tiers, 4));
  g.setIndex(b.index);
  return g;
}

const _m = new Matrix4(), _q = new Quaternion(), _e = new Euler(), _p = new Vector3(), _s = new Vector3();

/** One class of towers: one instanced draw call, the per-tower look in instanced attributes. */
function TowerClass({ kind, towers, material }: { kind: TowerKind; towers: readonly Tower[]; material: CityMaterial }) {
  const geometry = useMemo(() => {
    const g = towerGeometry(kind);
    const look = new Float32Array(towers.length * 4), accent = new Float32Array(towers.length);
    towers.forEach((t, i) => { look.set([t.seed, t.lit, t.seams ? 1 : 0, t.crown ? 1 : 0], i * 4); accent[i] = t.accent; });
    g.setAttribute("aLook", new InstancedBufferAttribute(look, 4));
    g.setAttribute("aAccent", new InstancedBufferAttribute(accent, 1));
    return g;
  }, [kind, towers]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    towers.forEach((t, i) => {
      _m.compose(_p.set(t.x, GROUND_Y, t.z), _q.setFromEuler(_e.set(0, t.rot, 0)), _s.set(t.w, t.h, t.d));
      mesh.setMatrixAt(i, _m);
    });
    mesh.instanceMatrix.needsUpdate = true;
  }, [towers]);
  if (towers.length === 0) return null;
  return <instancedMesh ref={ref} args={[geometry, material, towers.length]} frustumCulled={false} userData={{ cityTowers: kind }} />;
}

type CityMaterial = ReturnType<typeof towerMaterial>;

/** The building's own tower under the slab, in the city's glass: gold seams, more lit windows than its neighbours. */
function OwnTower({ bounds, material }: { bounds: Rect; material: CityMaterial }) {
  const tower = useMemo<Tower[]>(() => [{
    kind: "block", x: (bounds.minX + bounds.maxX) / 2, z: (bounds.minZ + bounds.maxZ) / 2,
    w: bounds.maxX - bounds.minX - 1.2, d: bounds.maxZ - bounds.minZ - 1.2, h: -0.6 - GROUND_Y,
    rot: 0, seed: 0.37, lit: 0.24, seams: true, crown: false, accent: 2,
  }], [bounds]);
  return <TowerClass kind="block" towers={tower} material={material} />;
}

/** Flying traffic: one streak per car, every car of every lane in one instanced draw call. */
function Traffic({ plan, uniforms }: { plan: CityPlan; uniforms: CityUniforms }) {
  const material = useMemo(() => trafficMaterial(uniforms), [uniforms]);
  const geometry = useMemo(() => {
    const quad = new PlaneGeometry(1, 1);
    const g = new InstancedBufferGeometry();
    g.index = quad.index;
    g.setAttribute("position", quad.getAttribute("position"));
    const total = plan.lanes.reduce((n, lane) => n + lane.cars, 0);
    const orbit = new Float32Array(total * 4), motion = new Float32Array(total * 4), look = new Float32Array(total * 4);
    const head = new Color(CITY_PALETTE.head), tail = new Color(CITY_PALETTE.tail), cyan = new Color(CITY_PALETTE.cyan), gold = new Color(CITY_PALETTE.accents[2]);
    const rand = lcg(0x7a11c);
    let i = 0;
    plan.lanes.forEach((lane, laneIndex) => {
      for (let c = 0; c < lane.cars; c += 1, i += 1) {
        // Cars bunch a little along the lane instead of keeping an exact spacing.
        const phase = ((c + (rand() - 0.5) * 0.7) / lane.cars) * Math.PI * 2;
        // Two streams per lane, side by side, a car's lights showing the way it goes.
        const offset = (c % 2 === 0 ? 1 : -1) * 2.4;
        const roll = rand();
        const colour = roll < 0.06 ? cyan : roll < 0.1 ? gold : lane.omega > 0 === (c % 2 === 0) ? head : tail;
        orbit.set([lane.cx, lane.cz, lane.rx + offset, lane.rz + offset], i * 4);
        motion.set([lane.y + (rand() - 0.5) * 1.5, phase, lane.omega * (c % 2 === 0 ? 1 : -1) * (0.9 + rand() * 0.2), lane.bob], i * 4);
        look.set([colour.r, colour.g, colour.b, 4.5 + rand() * 3.5 + (laneIndex >= plan.lanes.length - 3 ? 3 : 0)], i * 4);
      }
    });
    g.setAttribute("aOrbit", new InstancedBufferAttribute(orbit, 4));
    g.setAttribute("aMotion", new InstancedBufferAttribute(motion, 4));
    g.setAttribute("aLook", new InstancedBufferAttribute(look, 4));
    g.instanceCount = total;
    return g;
  }, [plan]);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <mesh geometry={geometry} material={material} frustumCulled={false} renderOrder={3} />;
}

function Beacons({ plan, uniforms }: { plan: CityPlan; uniforms: CityUniforms }) {
  const material = useMemo(() => beaconMaterial(uniforms), [uniforms]);
  const geometry = useMemo(() => {
    const g = new BufferGeometry();
    g.setAttribute("position", new Float32BufferAttribute(plan.beacons.flatMap((b) => [b.x, b.y, b.z]), 3));
    g.setAttribute("aBeacon", new Float32BufferAttribute(plan.beacons.flatMap((b) => [b.kind, b.phase]), 2));
    return g;
  }, [plan]);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <points geometry={geometry} material={material} frustumCulled={false} renderOrder={3} />;
}

const BEAM_COLOURS = CITY_PALETTE.accents.map((hex) => new Color(hex));

function Beams({ plan, uniforms }: { plan: CityPlan; uniforms: CityUniforms }) {
  const material = useMemo(() => beamMaterial(uniforms), [uniforms]);
  const geometry = useMemo(() => new CylinderGeometry(1, 1, 1, 16, 1, true).translate(0, 0.5, 0), []);
  useEffect(() => () => material.dispose(), [material]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  const s = plan.singularity;
  // The singularity's jets: up into the night and down to the crater floor, wider and brighter than a roof beam.
  const beams = useMemo(() => [
    ...plan.beams.map((b) => ({ ...b, colour: BEAM_COLOURS[b.accent], flip: false })),
    { x: s.x, y: s.y + SINGULARITY.core * 0.6, z: s.z, height: 620, radius: 3.4, colour: new Color("#bfe9ff").multiplyScalar(1.6), flip: false },
    { x: s.x, y: s.y - SINGULARITY.core * 0.6, z: s.z, height: s.y - SINGULARITY.core * 0.6 - GROUND_Y, radius: 3.4, colour: new Color("#bfe9ff").multiplyScalar(1.3), flip: true },
  ], [plan, s]);
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    beams.forEach((b, i) => {
      _m.compose(_p.set(b.x, b.y, b.z), _q.setFromEuler(_e.set(b.flip ? Math.PI : 0, 0, 0)), _s.set(b.radius, b.height, b.radius));
      mesh.setMatrixAt(i, _m);
      mesh.setColorAt(i, b.colour);
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [beams]);
  return <instancedMesh ref={ref} args={[geometry, material, beams.length]} frustumCulled={false} renderOrder={4} />;
}

/** The singularity: core, disc, lens, and the three orbital rings turning round it. */
function Singularity({ plan, uniforms, reduced }: { plan: CityPlan; uniforms: CityUniforms; reduced: boolean }) {
  const s = plan.singularity, size = SINGULARITY.core * 9;
  const parts = useMemo(() => ({
    core: coreMaterial(uniforms),
    disc: discMaterial(uniforms, SINGULARITY.disc.inner, SINGULARITY.disc.outer),
    lens: lensMaterial(uniforms, SINGULARITY.core, size),
    rings: SINGULARITY.rings.map((r) => orbitalRingMaterial(uniforms, Math.sign(r.speed))),
  }), [uniforms, size]);
  const geometries = useMemo(() => ({
    core: new SphereGeometry(SINGULARITY.core, 48, 32),
    disc: new RingGeometry(SINGULARITY.disc.inner, SINGULARITY.disc.outer, 160, 1),
    lens: new PlaneGeometry(size, size),
    rings: SINGULARITY.rings.map((r) => new TorusGeometry(r.radius, 0.9, 8, 256)),
  }), [size]);
  useEffect(() => () => { parts.core.dispose(); parts.disc.dispose(); parts.lens.dispose(); for (const m of parts.rings) m.dispose(); }, [parts]);
  useEffect(() => () => {
    geometries.core.dispose(); geometries.disc.dispose(); geometries.lens.dispose(); for (const g of geometries.rings) g.dispose();
  }, [geometries]);
  const lens = useRef<Mesh>(null);
  const rings = useRef<(Group | null)[]>([]);
  useFrame(({ camera }, dt) => {
    lens.current?.quaternion.copy(camera.quaternion);
    if (reduced) return;
    SINGULARITY.rings.forEach((r, i) => { const g = rings.current[i]; if (g) g.rotation.z += r.speed * Math.min(dt, 0.1); });
  });
  return (
    <group position={[s.x, s.y, s.z]}>
      <mesh geometry={geometries.core} material={parts.core} />
      <mesh geometry={geometries.disc} material={parts.disc} rotation={[-Math.PI / 2 + SINGULARITY.disc.tilt, 0, 0.3]} renderOrder={2} />
      <mesh ref={lens} geometry={geometries.lens} material={parts.lens} renderOrder={5} />
      {SINGULARITY.rings.map((r, i) => (
        <group key={i} rotation={[Math.PI / 2 + r.tilt[0], r.tilt[1], 0]}>
          <group ref={(g) => { rings.current[i] = g; }}>
            <mesh geometry={geometries.rings[i]} material={parts.rings[i]} renderOrder={3} />
          </group>
        </group>
      ))}
    </group>
  );
}

/** Two sheets of drifting mist between the roofs. */
const MIST_SHEETS = [{ y: GROUND_Y + 60, strength: 0.2, drift: 1 }, { y: GROUND_Y + 150, strength: 0.1, drift: -1.4 }] as const;

export function SingularityCity({ bounds: given, reduced = false }: { bounds: Rect; reduced?: boolean }) {
  // Keyed on the floor's size, not the object: every rebuilt layout passes a new one, and a new plan would mean
  // new materials and compiling every shader again.
  const { minX, maxX, minZ, maxZ } = given;
  const bounds = useMemo<Rect>(() => ({ minX, maxX, minZ, maxZ }), [minX, maxX, minZ, maxZ]);
  const plan = useMemo(() => planCity(bounds), [bounds]);
  const plaza = Math.hypot(bounds.maxX - bounds.minX, bounds.maxZ - bounds.minZ) / 2 + CITY.clear - 6;
  // The materials live as long as the city does; a new plan (a floor that changed size) only moves their uniforms.
  const [uniforms, materials] = useMemo(() => {
    const shared = cityUniforms(plan.singularity);
    return [shared, {
      tower: towerMaterial(shared),
      ground: groundMaterial(shared, plan.centre, CITY.cell, CITY.avenueEvery, plaza),
      mist: MIST_SHEETS.map((m) => mistMaterial(shared, plan.centre, plaza, m.strength, m.drift)),
      sky: skyMaterial(shared),
    }] as const;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    uniforms.uSing.value.set(plan.singularity.x, plan.singularity.y, plan.singularity.z);
    for (const m of [materials.ground, ...materials.mist]) {
      m.uniforms.uCentre.value = [plan.centre.x, plan.centre.z];
      m.uniforms.uPlaza.value = plaza;
    }
  }, [uniforms, materials, plan, plaza]);
  const geometries = useMemo(() => ({
    ground: new PlaneGeometry(CITY.radius * 2.8, CITY.radius * 2.8).rotateX(-Math.PI / 2),
    mist: new PlaneGeometry(CITY.radius * 2.4, CITY.radius * 2.4).rotateX(-Math.PI / 2),
    sky: new SphereGeometry(500, 48, 24),
  }), []);
  useEffect(() => () => {
    materials.tower.dispose(); materials.ground.dispose(); materials.sky.dispose(); for (const m of materials.mist) m.dispose();
  }, [materials]);
  useEffect(() => () => { geometries.ground.dispose(); geometries.mist.dispose(); geometries.sky.dispose(); }, [geometries]);
  const byKind = useMemo(() => TOWER_KINDS.map((kind) => plan.towers.filter((t) => t.kind === kind)), [plan]);
  const sky = useRef<Mesh>(null);
  useFrame(({ camera, size, viewport }, dt) => {
    sky.current?.position.copy(camera.position);
    const fov = "fov" in camera ? (camera as { fov: number }).fov : 35;
    uniforms.uPxScale.value = (size.height * viewport.dpr) / (2 * Math.tan((fov * Math.PI) / 360));
    // The clock wraps once a day so its precision never decays; traffic and pulses jump once at the wrap.
    if (!reduced) uniforms.uTime.value = (uniforms.uTime.value + Math.min(dt, 0.1)) % 86_400;
  });
  return (
    <group userData={{ city: "singularity" }}>
      <mesh ref={sky} geometry={geometries.sky} material={materials.sky} renderOrder={-1000} frustumCulled={false} />
      <mesh geometry={geometries.ground} material={materials.ground} position={[plan.centre.x, GROUND_Y, plan.centre.z]} />
      {TOWER_KINDS.map((kind, i) => <TowerClass key={kind} kind={kind} towers={byKind[i]} material={materials.tower} />)}
      <OwnTower bounds={bounds} material={materials.tower} />
      {MIST_SHEETS.map((m, i) => (
        <mesh key={i} geometry={geometries.mist} material={materials.mist[i]} position={[plan.centre.x, m.y, plan.centre.z]} renderOrder={1} />
      ))}
      <Traffic plan={plan} uniforms={uniforms} />
      <Beacons plan={plan} uniforms={uniforms} />
      <Beams plan={plan} uniforms={uniforms} />
      <Singularity plan={plan} uniforms={uniforms} reduced={reduced} />
    </group>
  );
}
