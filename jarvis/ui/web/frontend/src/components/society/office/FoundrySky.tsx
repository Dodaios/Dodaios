/**
 * The Foundry deck's sky: a nebula dome with a star field, and a ringed planet
 * far below the deck's north-west edge, where the office camera (from the
 * south-east, looking down) sees past the railing. All three are shaders on
 * plain geometry, drawn behind everything (no depth write, no fog), so the sky
 * costs three draw calls and no textures.
 */
import { useEffect, useMemo } from "react";
import { useFrame } from "@react-three/fiber";
import { AdditiveBlending, BackSide, Color, DoubleSide, ShaderMaterial, Vector3 } from "three";
import { FOUNDRY } from "./foundryPalette";

const SKY_RADIUS = 520;
/** Render order of the planet (the sky follows it): after every opaque part of the deck. */
const SKY_ORDER = 1000;

const SKY_VERTEX = /* glsl */ `
  varying vec3 vDir;
  void main() {
    vDir = normalize(position);
    vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    gl_Position = p.xyww;
  }
`;

/** Value-noise FBM over the view direction; star cells hashed on a sphere grid. */
const SKY_FRAGMENT = /* glsl */ `
  uniform float uTime;
  uniform vec3 uDeep, uViolet, uMagenta, uTeal, uGlow;
  varying vec3 vDir;
  float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
  float noise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float n000 = hash(i), n100 = hash(i + vec3(1,0,0)), n010 = hash(i + vec3(0,1,0)), n110 = hash(i + vec3(1,1,0));
    float n001 = hash(i + vec3(0,0,1)), n101 = hash(i + vec3(1,0,1)), n011 = hash(i + vec3(0,1,1)), n111 = hash(i + vec3(1,1,1));
    return mix(mix(mix(n000, n100, f.x), mix(n010, n110, f.x), f.y), mix(mix(n001, n101, f.x), mix(n011, n111, f.x), f.y), f.z);
  }
  float fbm(vec3 p) {
    float v = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + vec3(1.7, 9.2, 3.1); a *= 0.5; }
    return v;
  }
  void main() {
    vec3 d = normalize(vDir);
    vec3 drift = vec3(uTime * 0.004, 0.0, uTime * 0.002);
    float cloud = fbm(d * 2.2 + drift);
    float wisp = fbm(d * 5.0 - drift * 2.0 + cloud * 1.6);
    // A band of nebula across the sky, brightest where it crosses the north-west.
    float band = smoothstep(0.55, 0.0, abs(d.y * 0.8 + d.x * 0.35 - 0.05 + (cloud - 0.5) * 0.6));
    vec3 col = uDeep;
    col = mix(col, uViolet, smoothstep(0.35, 0.8, cloud) * 0.85);
    col = mix(col, uTeal, smoothstep(0.55, 0.9, wisp) * band * 0.7);
    col = mix(col, uMagenta, smoothstep(0.6, 0.95, cloud * wisp * 1.6) * band * 0.6);
    col += uGlow * pow(smoothstep(0.62, 1.0, wisp * band), 3.0) * 0.55;
    col *= 0.55 + band * 0.6;
    // Stars: one candidate per cell of a direction grid, a few of them bright.
    vec3 cell = floor(d * 180.0);
    float h = hash(cell);
    float star = step(0.9965, h) * smoothstep(0.42, 0.0, length(fract(d * 180.0) - 0.5));
    float twinkle = 0.6 + 0.4 * sin(uTime * (1.0 + h * 3.0) + h * 40.0);
    col += vec3(0.85, 0.9, 1.0) * star * twinkle * (0.6 + 1.6 * step(0.9993, h));
    gl_FragColor = vec4(col, 1.0);
  }
`;

const PLANET_VERTEX = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vLocal;
  varying vec3 vView;
  void main() {
    vLocal = normalize(position);
    vNormal = normalize(normalMatrix * normal);
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

const PLANET_FRAGMENT = /* glsl */ `
  uniform vec3 uDay, uBand, uNight, uRim, uSun;
  uniform float uTime;
  varying vec3 vNormal;
  varying vec3 vLocal;
  varying vec3 vView;
  float hash(vec3 p) { return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
  float noise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x), mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),
      mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x), mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z);
  }
  void main() {
    float lat = vLocal.y;
    float turb = noise(vLocal * 6.0 + vec3(uTime * 0.01, 0.0, 0.0)) * 0.35 + noise(vLocal * 18.0) * 0.12;
    float bands = 0.5 + 0.5 * sin(lat * 28.0 + turb * 6.0);
    vec3 surface = mix(uDay, uBand, bands * 0.75);
    float light = clamp(dot(normalize(vNormal), normalize(uSun)), 0.0, 1.0);
    vec3 col = mix(uNight, surface, smoothstep(0.0, 0.55, light));
    float fres = pow(1.0 - clamp(dot(normalize(vNormal), vView), 0.0, 1.0), 2.6);
    col += uRim * fres * (0.35 + light * 0.9);
    gl_FragColor = vec4(col, 1.0);
  }
`;

const RING_VERTEX = /* glsl */ `
  varying vec3 vPos;
  void main() {
    vPos = position;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const RING_FRAGMENT = /* glsl */ `
  uniform vec3 uRing;
  uniform float uInner, uOuter;
  varying vec3 vPos;
  float hash(float n) { return fract(sin(n) * 43758.5453); }
  void main() {
    float r = (length(vPos.xy) - uInner) / (uOuter - uInner);
    float lanes = 0.55 + 0.45 * sin(r * 90.0) * sin(r * 23.0 + 1.3);
    float gap = smoothstep(0.42, 0.45, r) * (1.0 - smoothstep(0.49, 0.52, r));
    float edge = smoothstep(0.0, 0.06, r) * (1.0 - smoothstep(0.9, 1.0, r));
    float a = edge * lanes * (1.0 - gap * 0.85) * 0.32;
    gl_FragColor = vec4(uRing * (0.45 + lanes * 0.35), a);
  }
`;

const RING = { inner: 1.4, outer: 2.05 } as const;
/** The planet's radius: far out to the west, it fills a corner of the view, not the whole of it. */
const PLANET_R = 78;

/** The nebula dome, the planet and its ring; `animate` drifts the clouds and the planet's storms. */
export function FoundrySky({ centre, animate }: { centre: [number, number]; animate: boolean }) {
  const materials = useMemo(() => {
    const c = (hex: string) => new Color(hex);
    const sky = new ShaderMaterial({
      vertexShader: SKY_VERTEX, fragmentShader: SKY_FRAGMENT, side: BackSide, depthWrite: false, fog: false,
      uniforms: {
        uTime: { value: 0 }, uDeep: { value: c(FOUNDRY.nebula.deep) }, uViolet: { value: c(FOUNDRY.nebula.violet) },
        uMagenta: { value: c(FOUNDRY.nebula.magenta) }, uTeal: { value: c(FOUNDRY.nebula.teal) }, uGlow: { value: c(FOUNDRY.nebula.glow) },
      },
    });
    const planet = new ShaderMaterial({
      vertexShader: PLANET_VERTEX, fragmentShader: PLANET_FRAGMENT, fog: false,
      uniforms: {
        uTime: { value: 0 }, uDay: { value: c(FOUNDRY.planet.day) }, uBand: { value: c(FOUNDRY.planet.band) },
        uNight: { value: c(FOUNDRY.planet.night) }, uRim: { value: c(FOUNDRY.planet.rim) },
        uSun: { value: new Vector3(0.6, 0.55, 0.4).normalize() },
      },
    });
    const ring = new ShaderMaterial({
      vertexShader: RING_VERTEX, fragmentShader: RING_FRAGMENT, side: DoubleSide, transparent: true, depthWrite: false,
      blending: AdditiveBlending, fog: false,
      uniforms: { uRing: { value: c(FOUNDRY.planet.ring) }, uInner: { value: PLANET_R * RING.inner }, uOuter: { value: PLANET_R * RING.outer } },
    });
    return { sky, planet, ring };
  }, []);
  useEffect(() => () => { materials.sky.dispose(); materials.planet.dispose(); materials.ring.dispose(); }, [materials]);
  useFrame((_, delta) => {
    if (!animate) return;
    const step = Math.min(delta, 0.1);
    materials.sky.uniforms.uTime.value += step;
    materials.planet.uniforms.uTime.value += step;
  });
  const [cx, cz] = centre;
  return (
    <group>
      {/* Sky and planet draw after the deck, so the depth test skips every pixel the deck already covers. */}
      <mesh material={materials.sky} renderOrder={SKY_ORDER + 1} frustumCulled={false}>
        <sphereGeometry args={[SKY_RADIUS, 48, 24]} />
      </mesh>
      {/* Far below the deck's north end, off to the right: the camera sees it beside the deck, not behind all of it. */}
      <group position={[cx - 5, -190, cz - 330]} rotation={[0.32, 0.6, -0.18]}>
        <mesh material={materials.planet} renderOrder={SKY_ORDER}>
          <sphereGeometry args={[PLANET_R, 64, 32]} />
        </mesh>
        <mesh material={materials.ring} rotation={[-Math.PI / 2 + 0.22, 0, 0]} renderOrder={-8}>
          <ringGeometry args={[PLANET_R * RING.inner, PLANET_R * RING.outer, 128, 1]} />
        </mesh>
      </group>
    </group>
  );
}
