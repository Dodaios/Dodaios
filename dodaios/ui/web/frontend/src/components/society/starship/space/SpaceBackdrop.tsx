/**
 * Outside the hull: a procedural star field and nebula on a sky sphere, the
 * destination's planet below the ship (surface, night-side lights, clouds
 * and an atmosphere rim lit by the sun), its rings, the sun itself, and at
 * one destination a black hole. Everything is self-lit and cast no shadows;
 * with reduced motion the sky stands still.
 */
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import {
  AdditiveBlending, BackSide, Color, DoubleSide, Mesh, PlaneGeometry, RingGeometry, ShaderMaterial, SphereGeometry, Vector3,
} from "three";
import type { Destination } from "./destinations";

const NOISE = /* glsl */ `
float hash13(vec3 p) { p = fract(p * 0.1031); p += dot(p, p.zyx + 31.32); return fract((p.x + p.y) * p.z); }
float noise3(vec3 x) {
  vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(hash13(i), hash13(i + vec3(1,0,0)), f.x), mix(hash13(i + vec3(0,1,0)), hash13(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(hash13(i + vec3(0,0,1)), hash13(i + vec3(1,0,1)), f.x), mix(hash13(i + vec3(0,1,1)), hash13(i + vec3(1,1,1)), f.x), f.y), f.z);
}
float fbm(vec3 p) { float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++) { v += a * noise3(p); p = p * 2.03 + 17.1; a *= 0.5; } return v; }
`;

const SKY_VERT = /* glsl */ `
varying vec3 vDir;
void main() { vDir = normalize(position); vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position = p.xyww; }
`;

const SKY_FRAG = /* glsl */ `
uniform vec3 uNebulaA; uniform vec3 uNebulaB; uniform float uNebula; uniform float uStars; uniform float uBand; uniform float uTime;
varying vec3 vDir;
${NOISE}
vec3 starLayer(vec3 d, float scale, float threshold, float size) {
  vec3 p = d * scale; vec3 cell = floor(p); vec3 f = fract(p) - 0.5;
  float h = hash13(cell);
  if (h < threshold) return vec3(0.0);
  vec3 offset = vec3(hash13(cell + 1.7), hash13(cell + 7.3), hash13(cell + 3.1)) - 0.5;
  float dist = length(f - offset * 0.7);
  float b = smoothstep(size, 0.0, dist) * (h - threshold) / (1.0 - threshold);
  float tint = hash13(cell + 11.0);
  vec3 col = mix(vec3(0.7, 0.8, 1.0), vec3(1.0, 0.85, 0.7), tint);
  float tw = 0.75 + 0.25 * sin(uTime * (1.0 + h * 3.0) + h * 40.0);
  return col * b * tw;
}
void main() {
  vec3 d = normalize(vDir);
  // A galactic band across the sky.
  float band = exp(-pow(dot(d, normalize(vec3(0.3, 0.55, -0.78))) * 3.2, 2.0)) * uBand;
  float n = fbm(d * 2.2 + vec3(4.0));
  float n2 = fbm(d * 5.0 - vec3(2.0));
  float neb = smoothstep(0.42, 0.85, n) * uNebula;
  vec3 col = vec3(0.004, 0.006, 0.014);
  col += mix(uNebulaA, uNebulaB, smoothstep(0.3, 0.8, n2)) * neb * 0.55;
  col += vec3(0.55, 0.5, 0.62) * band * (0.08 + 0.12 * n2);
  // Dark dust lanes inside the band.
  col *= 1.0 - band * smoothstep(0.55, 0.75, n2) * 0.6;
  vec3 stars = starLayer(d, 180.0, 0.965, 0.22) * 2.2 + starLayer(d, 420.0, 0.975, 0.18) * 1.3 + starLayer(d, 900.0, 0.985, 0.16) * (0.8 + band * 2.0);
  col += stars * uStars;
  gl_FragColor = vec4(col, 1.0);
}
`;

const PLANET_VERT = /* glsl */ `
varying vec3 vNormal; varying vec3 vWorld; varying vec3 vLocal;
void main() {
  vLocal = position;
  vNormal = normalize(mat3(modelMatrix) * normal);
  vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz;
  gl_Position = projectionMatrix * viewMatrix * w;
}
`;

const PLANET_FRAG = /* glsl */ `
uniform vec3 uSun; uniform vec3 uSunColour; uniform vec3 uC0; uniform vec3 uC1; uniform vec3 uC2; uniform vec3 uAtmo;
uniform float uKind; uniform float uCity; uniform float uTime; uniform float uRadius;
varying vec3 vNormal; varying vec3 vWorld; varying vec3 vLocal;
${NOISE}
void main() {
  vec3 n = normalize(vNormal);
  // The ship hangs over the planet's +y side: the poles lie along z, so it looks at the tropics, not an ice cap.
  vec3 p = normalize(vLocal).xzy;
  vec3 view = normalize(cameraPosition - vWorld);
  float light = dot(n, normalize(uSun));
  float day = smoothstep(-0.12, 0.25, light);
  vec3 surface;
  float clouds = 0.0;
  float night = 0.0;
  if (uKind < 0.5) {
    // Terran: oceans, continents, ice caps, clouds.
    float h = fbm(p * 7.5 + 1.3);
    float land = smoothstep(0.54, 0.58, h);
    vec3 ocean = mix(uC0, uC1, smoothstep(0.2, 0.52, h));
    vec3 ground = mix(vec3(0.16, 0.24, 0.12), vec3(0.42, 0.36, 0.24), smoothstep(0.56, 0.75, h));
    surface = mix(ocean, ground, land);
    surface = mix(surface, uC2, smoothstep(0.78, 0.9, abs(p.y)));
    clouds = smoothstep(0.6, 0.82, fbm(p * 13.0 + vec3(uTime * 0.004, 0.0, uTime * 0.002))) * 0.75;
    night = land * smoothstep(0.62, 0.8, fbm(p * 70.0)) * uCity;
  } else if (uKind < 1.5) {
    // Gas giant: latitude bands with turbulence.
    float lat = p.y + fbm(p * vec3(2.0, 8.0, 2.0) + vec3(uTime * 0.002, 0.0, 0.0)) * 0.18;
    float b = sin(lat * 26.0) * 0.5 + 0.5;
    surface = mix(uC0, uC1, b);
    surface = mix(surface, uC2, smoothstep(0.6, 1.0, sin(lat * 9.0 + 1.0)) * 0.6);
  } else if (uKind < 2.5) {
    // Ice: bright plains crossed by dark fractures.
    float c = abs(fbm(p * 7.0) - 0.5);
    surface = mix(uC1, uC2, smoothstep(0.3, 0.7, fbm(p * 2.5)));
    surface = mix(uC0, surface, smoothstep(0.0, 0.04, c));
  } else if (uKind < 3.5) {
    // Lava: dark crust and glowing seams that also show on the night side.
    float c = abs(fbm(p * 5.0) - 0.5);
    surface = mix(uC0, uC1, smoothstep(0.35, 0.75, fbm(p * 2.0)));
    night = smoothstep(0.05, 0.0, c) * 1.6;
  } else {
    // Aurora world: terran with a green aurora round both poles.
    float h = fbm(p * 3.0 + 4.2);
    float land = smoothstep(0.5, 0.55, h);
    surface = mix(mix(uC0, uC1, h), vec3(0.2, 0.3, 0.22), land);
    clouds = smoothstep(0.55, 0.8, fbm(p * 5.0 + uTime * 0.003));
    night = land * smoothstep(0.64, 0.8, fbm(p * 40.0)) * uCity;
  }
  vec3 col = surface * (0.06 + 0.94 * max(0.0, light)) * uSunColour;
  col = mix(col, vec3(1.0) * max(0.0, light) * uSunColour, clouds * 0.85);
  // City lights and lava glow live on the dark side.
  vec3 glow = uKind > 2.5 && uKind < 3.5 ? vec3(1.6, 0.55, 0.15) : vec3(1.4, 1.0, 0.55);
  col += glow * night * (1.0 - day) * (1.0 - clouds * 0.7);
  if (uKind > 3.5) {
    float aur = smoothstep(0.72, 0.82, abs(p.y)) * (1.0 - smoothstep(0.86, 0.95, abs(p.y)));
    aur *= 0.5 + 0.5 * sin(atan(p.z, p.x) * 18.0 + uTime * 0.25);
    col += vec3(0.25, 1.4, 0.7) * aur * (1.0 - day * 0.6);
  }
  // Atmosphere: a rim that glows where the sun reaches.
  float rim = pow(1.0 - max(0.0, dot(n, view)), 3.0);
  col += uAtmo * rim * (0.15 + 1.6 * smoothstep(-0.3, 0.4, light));
  gl_FragColor = vec4(col, 1.0);
}
`;

const HALO_FRAG = /* glsl */ `
uniform vec3 uAtmo; uniform vec3 uSun; varying vec3 vNormal; varying vec3 vWorld;
void main() {
  vec3 view = normalize(cameraPosition - vWorld);
  float facing = dot(normalize(vNormal), view);
  float a = pow(clamp(1.0 + facing, 0.0, 1.0), 6.0);
  float lit = smoothstep(-0.4, 0.5, dot(normalize(vNormal), normalize(uSun)));
  gl_FragColor = vec4(uAtmo * a * (0.2 + lit * 1.4), a * (0.25 + lit));
}
`;

const RING_FRAG = /* glsl */ `
uniform vec3 uColour; uniform float uInner; uniform float uOuter; varying vec3 vLocal;
${NOISE}
void main() {
  float r = length(vLocal.xy);
  float t = (r - uInner) / (uOuter - uInner);
  float bands = 0.55 + 0.45 * sin(t * 90.0) * sin(t * 23.0 + 1.0);
  float edge = smoothstep(0.0, 0.04, t) * smoothstep(1.0, 0.92, t);
  float gap = 1.0 - smoothstep(0.02, 0.0, abs(t - 0.62)) * 0.9;
  float a = edge * bands * gap * 0.75;
  gl_FragColor = vec4(uColour * (0.6 + bands * 0.6), a);
}
`;

const SUN_FRAG = /* glsl */ `
uniform vec3 uColour; varying vec2 vUv;
void main() {
  float d = length(vUv - 0.5) * 2.0;
  float core = smoothstep(0.12, 0.08, d);
  float glow = exp(-d * 5.0) * 0.9 + exp(-d * 14.0);
  float rays = pow(max(0.0, 1.0 - abs(vUv.x - 0.5) * 60.0), 2.0) * exp(-abs(vUv.y - 0.5) * 6.0) * 0.4
             + pow(max(0.0, 1.0 - abs(vUv.y - 0.5) * 60.0), 2.0) * exp(-abs(vUv.x - 0.5) * 6.0) * 0.4;
  vec3 col = uColour * (core * 6.0 + glow * 2.2 + rays * 2.0);
  gl_FragColor = vec4(col, 1.0);
}
`;

const DISC_FRAG = /* glsl */ `
uniform float uTime; varying vec3 vLocal;
${NOISE}
void main() {
  float r = length(vLocal.xy);
  float t = clamp((r - 60.0) / 260.0, 0.0, 1.0);
  float a = atan(vLocal.y, vLocal.x);
  float swirl = fbm(vec3(cos(a - uTime * 0.05 + t * 6.0) * 3.0, sin(a - uTime * 0.05 + t * 6.0) * 3.0, t * 8.0));
  float glow = (1.0 - t) * (1.0 - t) * (0.5 + swirl);
  vec3 col = mix(vec3(1.6, 0.7, 0.25), vec3(2.6, 2.1, 1.4), 1.0 - t) * glow * 2.0;
  gl_FragColor = vec4(col, smoothstep(0.0, 0.05, t) * glow);
}
`;

const VARY_VERT = /* glsl */ `
varying vec3 vLocal; varying vec2 vUv; varying vec3 vNormal; varying vec3 vWorld;
void main() { vLocal = position; vUv = uv; vNormal = normalize(mat3(modelMatrix) * normal); vec4 w = modelMatrix * vec4(position, 1.0); vWorld = w.xyz;
  gl_Position = projectionMatrix * viewMatrix * w; }
`;

function hex(colour: string): Color { return new Color(colour); }

const KIND: Record<Destination["planet"]["kind"], number> = { terran: 0, gas: 1, ice: 2, lava: 3, aurora: 4, none: -1 };

export function SpaceBackdrop({ destination, reduced }: { destination: Destination; reduced: boolean }) {
  const sunDir = useMemo(() => new Vector3(...destination.sun.direction).normalize(), [destination]);
  const sky = useMemo(() => new ShaderMaterial({
    vertexShader: SKY_VERT, fragmentShader: SKY_FRAG, side: BackSide, depthWrite: false, depthTest: false,
    uniforms: {
      uNebulaA: { value: hex(destination.sky.nebula[0]) }, uNebulaB: { value: hex(destination.sky.nebula[1]) },
      uNebula: { value: destination.sky.nebulaStrength }, uStars: { value: destination.sky.stars }, uBand: { value: destination.sky.band },
      uTime: { value: 0 },
    },
  }), [destination]);
  const planet = useMemo(() => destination.planet.kind === "none" ? null : new ShaderMaterial({
    vertexShader: PLANET_VERT, fragmentShader: PLANET_FRAG,
    uniforms: {
      uSun: { value: sunDir }, uSunColour: { value: hex(destination.sun.colour) },
      uC0: { value: hex(destination.planet.colours[0]) }, uC1: { value: hex(destination.planet.colours[1]) }, uC2: { value: hex(destination.planet.colours[2]) },
      uAtmo: { value: hex(destination.planet.atmosphere) }, uKind: { value: KIND[destination.planet.kind] },
      uCity: { value: destination.planet.cityLights ? 1 : 0 }, uTime: { value: 0 }, uRadius: { value: destination.planet.radius },
    },
  }), [destination, sunDir]);
  const halo = useMemo(() => destination.planet.kind === "none" ? null : new ShaderMaterial({
    vertexShader: PLANET_VERT, fragmentShader: HALO_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false, side: BackSide,
    uniforms: { uAtmo: { value: hex(destination.planet.atmosphere) }, uSun: { value: sunDir } },
  }), [destination, sunDir]);
  const rings = useMemo(() => destination.planet.rings ? new ShaderMaterial({
    vertexShader: VARY_VERT, fragmentShader: RING_FRAG, transparent: true, depthWrite: false, side: DoubleSide,
    uniforms: { uColour: { value: hex(destination.planet.rings.colour) }, uInner: { value: destination.planet.rings.inner }, uOuter: { value: destination.planet.rings.outer } },
  }) : null, [destination]);
  const sun = useMemo(() => new ShaderMaterial({
    vertexShader: VARY_VERT, fragmentShader: SUN_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false, toneMapped: false,
    uniforms: { uColour: { value: hex(destination.sun.colour) } },
  }), [destination]);
  const disc = useMemo(() => destination.singularity ? new ShaderMaterial({
    vertexShader: VARY_VERT, fragmentShader: DISC_FRAG, transparent: true, blending: AdditiveBlending, depthWrite: false, side: DoubleSide, toneMapped: false,
    uniforms: { uTime: { value: 0 } },
  }) : null, [destination]);
  const geos = useMemo(() => ({
    sky: new SphereGeometry(4000, 48, 24),
    planet: new SphereGeometry(1, 128, 64),
    ring: destination.planet.rings ? new RingGeometry(destination.planet.rings.inner, destination.planet.rings.outer, 160, 1) : null,
    sun: new PlaneGeometry(1, 1),
    disc: new RingGeometry(60, 320, 128, 1),
  }), [destination]);
  useEffect(() => () => {
    for (const m of [sky, planet, halo, rings, sun, disc]) m?.dispose();
    for (const g of Object.values(geos)) g?.dispose();
  }, [sky, planet, halo, rings, sun, disc, geos]);

  const planetRef = useRef<Mesh>(null);
  const sunRefs = useRef<(Mesh | null)[]>([]);
  useFrame(({ camera, clock }, dt) => {
    const t = reduced ? 0 : clock.elapsedTime;
    sky.uniforms.uTime.value = t;
    if (planet) planet.uniforms.uTime.value = t;
    if (disc) disc.uniforms.uTime.value = t;
    if (planetRef.current && !reduced) planetRef.current.rotation.y += dt * 0.004;
    for (const s of sunRefs.current) s?.lookAt(camera.position);
  });

  const p = destination.planet;
  const sunAt = sunDir.clone().multiplyScalar(3200);
  return (
    <group>
      <mesh geometry={geos.sky} material={sky} renderOrder={-10} frustumCulled={false} />
      {planet && halo && (
        <group position={p.centre}>
          <mesh ref={planetRef} geometry={geos.planet} material={planet} scale={p.radius} />
          <mesh geometry={geos.planet} material={halo} scale={p.radius * 1.06} />
          {rings && geos.ring && <mesh geometry={geos.ring} material={rings} rotation={[-Math.PI / 2 + (p.rings?.tilt ?? 0), 0, 0.2]} />}
        </group>
      )}
      <mesh ref={(m) => { sunRefs.current[0] = m; }} geometry={geos.sun} material={sun} position={sunAt} scale={900 * destination.sun.size} />
      {destination.sun.twin && (
        <mesh ref={(m) => { sunRefs.current[1] = m; }} geometry={geos.sun} material={sun}
          position={sunAt.clone().add(new Vector3(520, -160, 260))} scale={560 * destination.sun.size} />
      )}
      {destination.singularity && disc && <Singularity disc={disc} geometry={geos.disc} />}
    </group>
  );
}

function Singularity({ disc, geometry }: { disc: ShaderMaterial; geometry: RingGeometry }) {
  const core = useMemo(() => new SphereGeometry(58, 48, 24), []);
  const black = useMemo(() => new ShaderMaterial({
    vertexShader: VARY_VERT,
    fragmentShader: /* glsl */ `varying vec3 vNormal; varying vec3 vWorld;
      void main() { vec3 v = normalize(cameraPosition - vWorld); float rim = pow(1.0 - max(0.0, dot(normalize(vNormal), v)), 6.0);
        gl_FragColor = vec4(vec3(2.4, 1.7, 1.0) * rim, 1.0); }`,
    toneMapped: false,
  }), []);
  useEffect(() => () => { core.dispose(); black.dispose(); }, [core, black]);
  return (
    <group position={[-900, -380, -2200]} rotation={[0.35, 0.4, 0]}>
      <mesh geometry={core} material={black} />
      <mesh geometry={geometry} material={disc} rotation={[-Math.PI / 2 + 0.18, 0, 0]} />
      <mesh geometry={geometry} material={disc} rotation={[0.1, 0, 0]} scale={0.55} />
    </group>
  );
}
