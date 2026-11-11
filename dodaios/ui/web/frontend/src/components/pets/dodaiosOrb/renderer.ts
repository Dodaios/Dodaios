// Vendored from cyber1443/jarvis-ai-orb-web-animation @ 8af5ad1d. MIT.
// The notice is dodaiosOrb/LICENSE and third_party/orb-web-animation/LICENSE.
import * as THREE from "three";
import {
  STATE_TARGETS,
  resolvePalette,
  resolveStateTarget,
  sameStateTarget,
  stateChangeKick,
  type JarvisPalette,
  type JarvisPaletteValues,
  type JarvisSizePreset,
  type JarvisState,
  type JarvisStateName,
  type JarvisStateTarget,
} from "./states";

export interface RendererOptions {
  canvas: HTMLCanvasElement;
  preset: JarvisSizePreset;
  dpr: number;
  targetFps?: number;
  filamentFrameStride?: number;
  initialState: JarvisState;
  initialPalette: JarvisPalette;
}

export interface Renderer {
  setState: (state: JarvisState) => void;
  setPalette: (palette: JarvisPalette) => void;
  setPointer: (x: number, y: number, active: boolean) => void;
  setSpinActive: (active: boolean) => void;
  spinBy: (deltaX: number, deltaY: number) => void;
  setBreathing: (enabled: boolean, intensity?: number) => void;
  pulse: (amount?: number) => void;
  setIntensityOverride: (value: number | null) => void;
  setPaused: (paused: boolean) => void;
  resize: () => void;
  dispose: () => void;
}

const TAU = Math.PI * 2;

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function lerp(current: number, target: number, speed: number): number {
  return current + (target - current) * speed;
}

function seeded(seed: number): number {
  const value = Math.sin(seed * 12.9898) * 43758.5453;
  return value - Math.floor(value);
}

function spherePoint(index: number, count: number, radius = 1): THREE.Vector3 {
  const offset = 2 / count;
  const increment = Math.PI * (3 - Math.sqrt(5));
  const y = index * offset - 1 + offset / 2;
  const r = Math.sqrt(Math.max(0, 1 - y * y));
  const phi = index * increment;

  return new THREE.Vector3(Math.cos(phi) * r * radius, y * radius, Math.sin(phi) * r * radius);
}

function colorUniform(value: number): { value: THREE.Color } {
  return { value: new THREE.Color(value) };
}

function createHaloTexture(color: THREE.Color): THREE.CanvasTexture {
  const size = 192;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;

  const ctx = canvas.getContext("2d");
  if (ctx) {
    const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    const c = `rgb(${Math.round(color.r * 255)}, ${Math.round(color.g * 255)}, ${Math.round(color.b * 255)})`;
    gradient.addColorStop(0, "rgba(255,255,255,0.92)");
    gradient.addColorStop(0.18, c.replace("rgb", "rgba").replace(")", ",0.62)"));
    gradient.addColorStop(0.48, c.replace("rgb", "rgba").replace(")", ",0.18)"));
    gradient.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, size, size);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createCoreMaterial(colors: JarvisPaletteValues): THREE.ShaderMaterial {

  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uCore: colorUniform(colors.core),
      uPrimary: colorUniform(colors.primary),
      uEnergy: { value: 0.8 },
      uPulse: { value: 0 },
      uTime: { value: 0 },
    },
    vertexShader: `
      varying vec3 vNormal;
      varying vec3 vView;

      void main() {
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        vNormal = normalize(normalMatrix * normal);
        vView = normalize(-mvPosition.xyz);
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      uniform vec3 uCore;
      uniform vec3 uPrimary;
      uniform float uEnergy;
      uniform float uPulse;
      uniform float uTime;
      varying vec3 vNormal;
      varying vec3 vView;

      void main() {
        float fresnel = pow(1.0 - max(dot(normalize(vNormal), normalize(vView)), 0.0), 2.35);
        float shimmer = 0.72 + 0.28 * sin(uTime * 3.2 + vNormal.y * 18.0 + vNormal.x * 9.0);
        float alpha = 0.17 + fresnel * (0.72 + uEnergy * 0.16) + uPulse * 0.16;
        vec3 color = mix(uPrimary, uCore, 0.58 + fresnel * 0.38) * shimmer * (0.8 + uEnergy * 0.34 + uPulse * 0.4);
        gl_FragColor = vec4(color, alpha);
      }
    `,
  });
}

function createFlatRingMaterial(colors: JarvisPaletteValues, opacity: number): THREE.ShaderMaterial {

  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    uniforms: {
      uColor: colorUniform(colors.primary),
      uOpacity: { value: opacity },
      uPulse: { value: 0 },
      uTime: { value: 0 },
    },
    vertexShader: `
      varying vec3 vObjectNormal;
      varying vec3 vViewNormal;
      varying vec3 vView;

      void main() {
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        vObjectNormal = normalize(normal);
        vViewNormal = normalize(normalMatrix * normal);
        vView = normalize(-mvPosition.xyz);
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      uniform vec3 uColor;
      uniform float uOpacity;
      uniform float uPulse;
      uniform float uTime;
      varying vec3 vObjectNormal;
      varying vec3 vViewNormal;
      varying vec3 vView;

      void main() {
        float cap = smoothstep(0.58, 0.96, abs(vObjectNormal.z));
        float side = 1.0 - cap;
        float fresnel = pow(1.0 - max(dot(normalize(vViewNormal), normalize(vView)), 0.0), 2.2);
        float shimmer = 0.86 + 0.14 * sin(uTime * 2.0 + vObjectNormal.x * 18.0 + vObjectNormal.y * 9.0);
        vec3 sideColor = uColor * vec3(0.38, 0.72, 0.86);
        vec3 capColor = uColor * 1.34;
        vec3 color = mix(sideColor, capColor, cap) * shimmer;
        float alpha = uOpacity * (0.54 + cap * 0.48 + side * 0.18 + fresnel * 0.34 + uPulse * 0.22);
        gl_FragColor = vec4(color, alpha);
      }
    `,
  });
}

function createParticleMaterial(colors: JarvisPaletteValues, pointScale: number, dpr: number): THREE.ShaderMaterial {

  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uPrimary: colorUniform(colors.primary),
      uAccent: colorUniform(colors.tertiary),
      uTime: { value: 0 },
      uEnergy: { value: 0.8 },
      uPulse: { value: 0 },
      uPointScale: { value: pointScale },
      uPixelRatio: { value: dpr },
    },
    vertexShader: `
      attribute float aSeed;
      varying float vAlpha;
      varying float vMix;
      uniform float uTime;
      uniform float uEnergy;
      uniform float uPulse;
      uniform float uPointScale;
      uniform float uPixelRatio;

      void main() {
        vec3 p = position;
        float wobble = sin(uTime * (0.22 + aSeed * 0.24) + aSeed * 31.0) * 0.025;
        p *= 1.0 + wobble * uEnergy + uPulse * 0.035;

        vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mvPosition;

        float twinkle = 0.5 + 0.5 * sin(uTime * (1.3 + aSeed * 2.2) + aSeed * 64.0);
        vAlpha = (0.24 + twinkle * 0.82) * (0.58 + uEnergy * 0.34 + uPulse * 0.32);
        vMix = twinkle;
        gl_PointSize = uPixelRatio * uPointScale * (1.08 + twinkle * 1.38 + uPulse * 0.48) * (3.0 / max(0.7, -mvPosition.z));
      }
    `,
    fragmentShader: `
      varying float vAlpha;
      varying float vMix;
      uniform vec3 uPrimary;
      uniform vec3 uAccent;

      void main() {
        vec2 p = gl_PointCoord.xy - 0.5;
        float d = length(p);
        float alpha = smoothstep(0.5, 0.0, d) * vAlpha;
        vec3 color = mix(uPrimary, uAccent, vMix * 0.5);
        gl_FragColor = vec4(color, alpha);
      }
    `,
  });
}

function createDataPacketMaterial(colors: JarvisPaletteValues, pointScale: number, dpr: number): THREE.ShaderMaterial {

  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    uniforms: {
      uCore: colorUniform(colors.core),
      uPrimary: colorUniform(colors.primary),
      uTime: { value: 0 },
      uEnergy: { value: 0.8 },
      uPulse: { value: 0 },
      uPointScale: { value: pointScale },
      uPixelRatio: { value: dpr },
    },
    vertexShader: `
      attribute float aSeed;
      attribute float aDirection;
      varying float vAlpha;
      varying float vMix;
      uniform float uTime;
      uniform float uEnergy;
      uniform float uPulse;
      uniform float uPointScale;
      uniform float uPixelRatio;

      mat2 rot(float a) {
        float c = cos(a);
        float s = sin(a);
        return mat2(c, -s, s, c);
      }

      void main() {
        vec3 dir = normalize(position);
        float speed = 0.17 + aSeed * 0.15;
        float phase = fract(uTime * speed + aSeed * 1.73);
        float travel = aDirection > 0.0 ? phase : 1.0 - phase;
        float radius = mix(0.14, 1.2 + uPulse * 0.04, travel);

        dir.xz = rot(uTime * (0.07 + aSeed * 0.08) + travel * 0.34) * dir.xz;
        dir.xy = rot(sin(uTime * 0.22 + aSeed * 8.0) * 0.06) * dir.xy;

        vec3 p = dir * radius;
        vec4 mvPosition = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mvPosition;

        float head = smoothstep(0.0, 0.14, phase) * (1.0 - smoothstep(0.84, 1.0, phase));
        float coreBoost = 1.0 - smoothstep(0.0, 0.42, abs(travel - 0.5));
        vAlpha = head * (0.46 + coreBoost * 0.24) * (0.74 + uEnergy * 0.28 + uPulse * 0.34);
        vMix = travel;
        gl_PointSize = uPixelRatio * uPointScale * (1.0 + coreBoost * 0.7 + uPulse * 0.36) * (3.0 / max(0.72, -mvPosition.z));
      }
    `,
    fragmentShader: `
      varying float vAlpha;
      varying float vMix;
      uniform vec3 uCore;
      uniform vec3 uPrimary;

      void main() {
        vec2 p = gl_PointCoord.xy - 0.5;
        float d = length(p);
        float alpha = smoothstep(0.5, 0.0, d) * vAlpha;
        vec3 color = mix(uCore, uPrimary, 0.42 + vMix * 0.4);
        gl_FragColor = vec4(color, alpha);
      }
    `,
  });
}

function createParticleField(count: number, radius: number): {
  geometry: THREE.BufferGeometry;
  seeds: Float32Array;
} {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);

  for (let i = 0; i < count; i += 1) {
    const base = spherePoint(i, count, radius * (0.88 + seeded(i + 2.1) * 0.26));
    const jitter = 0.965 + seeded(i + 11.4) * 0.075;
    positions[i * 3] = base.x * jitter;
    positions[i * 3 + 1] = base.y * jitter;
    positions[i * 3 + 2] = base.z * jitter;
    seeds[i] = seeded(i + 41.2);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
  return { geometry, seeds };
}

function createDataPacketField(count: number): THREE.BufferGeometry {
  const positions = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  const directions = new Float32Array(count);

  for (let i = 0; i < count; i += 1) {
    const dir = spherePoint(Math.floor(seeded(i + 71.2) * 1200), 1200, 1);
    positions[i * 3] = dir.x;
    positions[i * 3 + 1] = dir.y;
    positions[i * 3 + 2] = dir.z;
    seeds[i] = seeded(i + 95.4);
    directions[i] = seeded(i + 18.1) > 0.48 ? 1 : -1;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
  geometry.setAttribute("aDirection", new THREE.BufferAttribute(directions, 1));
  return geometry;
}

interface FilamentData {
  geometry: THREE.BufferGeometry;
  positions: Float32Array;
  a: Float32Array;
  b: Float32Array;
  seeds: Float32Array;
}

function createFilaments(count: number): FilamentData {
  const positions = new Float32Array(count * 2 * 3);
  const a = new Float32Array(count * 3);
  const b = new Float32Array(count * 3);
  const seeds = new Float32Array(count);

  for (let i = 0; i < count; i += 1) {
    const s = seeded(i + 12.7);
    const p1 = spherePoint(Math.floor(seeded(i + 4.1) * 900), 900, 0.34 + seeded(i + 8.2) * 0.42);
    const p2 =
      s > 0.62
        ? spherePoint(Math.floor(seeded(i + 44.1) * 900), 900, 0.86 + seeded(i + 32.3) * 0.32)
        : p1.clone().normalize().multiplyScalar(0.86 + seeded(i + 32.3) * 0.32);

    a[i * 3] = p1.x;
    a[i * 3 + 1] = p1.y;
    a[i * 3 + 2] = p1.z;
    b[i * 3] = p2.x;
    b[i * 3 + 1] = p2.y;
    b[i * 3 + 2] = p2.z;
    seeds[i] = s;
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

  return { geometry, positions, a, b, seeds };
}

function updateFilaments(data: FilamentData, time: number, shellRadius: number, pulse: number, pointerX: number, pointerY: number) {
  for (let i = 0; i < data.seeds.length; i += 1) {
    const seed = data.seeds[i];
    const wave = Math.sin(time * (0.72 + seed * 1.8) + seed * 17.0);
    const scaleA = 0.9 + wave * 0.025 + pulse * 0.025;
    const scaleB = shellRadius + wave * 0.035 + pulse * 0.055;
    const n = i * 6;
    const a = i * 3;

    data.positions[n] = data.a[a] * scaleA + pointerX * 0.018;
    data.positions[n + 1] = data.a[a + 1] * scaleA + pointerY * 0.018;
    data.positions[n + 2] = data.a[a + 2] * scaleA;
    data.positions[n + 3] = data.b[a] * scaleB + pointerX * 0.035;
    data.positions[n + 4] = data.b[a + 1] * scaleB + pointerY * 0.035;
    data.positions[n + 5] = data.b[a + 2] * scaleB;
  }

  const attr = data.geometry.getAttribute("position") as THREE.BufferAttribute;
  attr.needsUpdate = true;
}

function createDashedRing(radius: number, segmentCount: number, dashSeed: number): THREE.BufferGeometry {
  const values: number[] = [];

  for (let i = 0; i < segmentCount; i += 1) {
    const on = seeded(i * 2.17 + dashSeed) > 0.34;
    if (!on) continue;

    const start = (i / segmentCount) * TAU;
    const end = ((i + 0.64 + seeded(i + dashSeed) * 0.18) / segmentCount) * TAU;
    values.push(Math.cos(start) * radius, Math.sin(start) * radius, 0);
    values.push(Math.cos(end) * radius, Math.sin(end) * radius, 0);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(values, 3));
  return geometry;
}

function createRectCrossSectionRing(
  radius: number,
  radialThickness: number,
  depth: number,
  segments: number,
  gapRatio = 0,
  dashCount = 0,
  dashSeed = 0,
): THREE.BufferGeometry {
  const positions: number[] = [];
  const outer = radius + radialThickness / 2;
  const inner = radius - radialThickness / 2;
  const top = depth / 2;
  const bottom = -depth / 2;

  const addQuad = (a: number[], b: number[], c: number[], d: number[]) => {
    positions.push(...a, ...b, ...c, ...a, ...c, ...d);
  };

  const isActive = (index: number) => {
    if (gapRatio <= 0 || dashCount <= 0) return true;
    const local = ((index / segments) * dashCount + dashSeed) % 1;
    return local > gapRatio;
  };

  for (let i = 0; i < segments; i += 1) {
    if (!isActive(i)) continue;

    const a = (i / segments) * TAU;
    const nextA = ((i + 1) / segments) * TAU;
    const x = Math.cos(a);
    const y = Math.sin(a);
    const nx = Math.cos(nextA);
    const ny = Math.sin(nextA);

    const outerTop = [x * outer, y * outer, top];
    const outerTopNext = [nx * outer, ny * outer, top];
    const innerTop = [x * inner, y * inner, top];
    const innerTopNext = [nx * inner, ny * inner, top];
    const outerBottom = [x * outer, y * outer, bottom];
    const outerBottomNext = [nx * outer, ny * outer, bottom];
    const innerBottom = [x * inner, y * inner, bottom];
    const innerBottomNext = [nx * inner, ny * inner, bottom];

    addQuad(outerTop, outerTopNext, innerTopNext, innerTop);
    addQuad(outerBottom, innerBottom, innerBottomNext, outerBottomNext);
    addQuad(outerTop, outerBottom, outerBottomNext, outerTopNext);
    addQuad(innerTop, innerTopNext, innerBottomNext, innerBottom);

    if (!isActive((i - 1 + segments) % segments)) {
      addQuad(outerTop, innerTop, innerBottom, outerBottom);
    }
    if (!isActive((i + 1) % segments)) {
      addQuad(outerTopNext, outerBottomNext, innerBottomNext, innerTopNext);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

function createSpokes(count: number): THREE.BufferGeometry {
  const values: number[] = [];

  for (let i = 0; i < count; i += 1) {
    const angle = (i / count) * TAU + seeded(i + 81) * 0.04;
    const inner = 0.18 + seeded(i + 22) * 0.12;
    const outer = 0.7 + seeded(i + 41) * 0.48;
    const fade = seeded(i + 9.2);
    if (fade < 0.22) continue;
    values.push(Math.cos(angle) * inner, Math.sin(angle) * inner * 0.72, 0);
    values.push(Math.cos(angle) * outer, Math.sin(angle) * outer * 0.72, 0);
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(values, 3));
  return geometry;
}

function disposeScene(object: THREE.Object3D) {
  object.traverse((child) => {
    const maybeMesh = child as THREE.Object3D & {
      geometry?: THREE.BufferGeometry;
      material?: THREE.Material | THREE.Material[];
    };

    maybeMesh.geometry?.dispose();
    const materials = Array.isArray(maybeMesh.material) ? maybeMesh.material : maybeMesh.material ? [maybeMesh.material] : [];
    for (const material of materials) material.dispose();
  });
}

export function createRenderer(opts: RendererOptions): Renderer {
  const { canvas, preset, initialState, initialPalette } = opts;
  const dpr = Math.max(1, Math.min(opts.dpr || 1, preset.dpr));
  const compact = preset.px <= 120;
  const frameInterval = opts.targetFps && opts.targetFps < 60 ? 1000 / opts.targetFps : 0;
  const filamentFrameStride = Math.max(1, Math.round(opts.filamentFrameStride ?? 1));
  const renderer = new THREE.WebGLRenderer({
    canvas,
    alpha: true,
    antialias: true,
    powerPreference: "high-performance",
    premultipliedAlpha: false,
  });

  renderer.setPixelRatio(dpr);
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0, 4.1);

  const interactionGroup = new THREE.Group();
  const root = new THREE.Group();
  const ringGroup = new THREE.Group();
  const coreGroup = new THREE.Group();
  root.scale.setScalar(preset.sceneScale);
  scene.add(interactionGroup);
  interactionGroup.add(root);
  root.add(coreGroup, ringGroup);

  let paletteValues: JarvisPaletteValues = resolvePalette(initialPalette);
  let haloTexture = createHaloTexture(new THREE.Color(paletteValues.primary));
  const haloMaterial = new THREE.SpriteMaterial({
    map: haloTexture,
    color: paletteValues.primary,
    transparent: true,
    opacity: compact ? 0.28 : 0.62,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const halo = new THREE.Sprite(haloMaterial);
  halo.scale.setScalar(compact ? 2.2 : 3.0);
  root.add(halo);

  const coreMaterial = createCoreMaterial(paletteValues);
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.3, compact ? 3 : 4), coreMaterial);
  coreGroup.add(core);

  const innerMaterial = new THREE.MeshBasicMaterial({
    color: paletteValues.core,
    transparent: true,
    opacity: compact ? 0.58 : 0.74,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const innerCore = new THREE.Mesh(new THREE.SphereGeometry(0.095, 24, 12), innerMaterial);
  coreGroup.add(innerCore);

  const particleMaterial = createParticleMaterial(paletteValues, compact ? 1.55 : 3.65, dpr);
  const particles = createParticleField(preset.particleCount, 1.05);
  const particlePoints = new THREE.Points(particles.geometry, particleMaterial);
  root.add(particlePoints);

  const dataPacketMaterial = createDataPacketMaterial(paletteValues, compact ? 1.9 : 4.3, dpr);
  const dataPackets = new THREE.Points(
    createDataPacketField(Math.max(34, Math.round(preset.particleCount * 0.11))),
    dataPacketMaterial,
  );
  root.add(dataPackets);

  const filamentData = createFilaments(preset.filamentCount);
  const filamentMaterial = new THREE.LineBasicMaterial({
    color: paletteValues.primary,
    transparent: true,
    opacity: compact ? 0.16 : 0.24,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const filaments = new THREE.LineSegments(filamentData.geometry, filamentMaterial);
  root.add(filaments);

  const lineMaterials: Array<THREE.LineBasicMaterial | THREE.MeshBasicMaterial> = [filamentMaterial];
  const ringConfigs = [
    { radius: 0.5, tiltX: 0.96, tiltY: -0.18, speed: 0.36, opacity: compact ? 0.82 : 0.64, seed: 2.4 },
    { radius: 0.72, tiltX: -0.58, tiltY: 0.32, speed: -0.54, opacity: compact ? 0.9 : 0.78, seed: 8.8 },
    { radius: 0.91, tiltX: 0.25, tiltY: 1.0, speed: 0.44, opacity: compact ? 0.82 : 0.7, seed: 15.5 },
    { radius: 1.12, tiltX: -0.14, tiltY: -0.7, speed: -0.22, opacity: compact ? 0.68 : 0.58, seed: 24.1 },
  ];

  for (const config of ringConfigs) {
    const material = new THREE.LineBasicMaterial({
      color: paletteValues.secondary,
      transparent: true,
      opacity: config.opacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const ring = new THREE.LineSegments(
      createDashedRing(config.radius, preset.ringSegments, config.seed),
      material,
    );
    ring.rotation.x = config.tiltX;
    ring.rotation.y = config.tiltY;
    ring.userData.speed = config.speed;
    ring.userData.baseOpacity = config.opacity;
    lineMaterials.push(material);
    ringGroup.add(ring);

    const bandMaterial = new THREE.MeshBasicMaterial({
      color: paletteValues.primary,
      transparent: true,
      opacity: config.opacity * 0.16,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const band = new THREE.Mesh(
      new THREE.TorusGeometry(config.radius, 0.0045 + config.radius * 0.0025, 6, preset.ringSegments),
      bandMaterial,
    );
    band.rotation.x = config.tiltX;
    band.rotation.y = config.tiltY;
    band.userData.speed = config.speed * 0.72;
    band.userData.baseOpacity = config.opacity * 0.16;
    lineMaterials.push(bandMaterial);
    ringGroup.add(band);
  }

  const flatRingMaterials: THREE.ShaderMaterial[] = [];
  const flatRingConfigs = [
    { radius: 0.56, radial: 0.038, depth: 0.048, gap: 0, dash: 0, seed: 0, tiltX: 0.72, tiltY: -0.34, speed: -0.34, opacity: compact ? 0.12 : 0.18 },
    { radius: 0.69, radial: 0.088, depth: 0.032, gap: 0.32, dash: 1, seed: 0.11, tiltX: 0.2, tiltY: 0.72, speed: 0.34, opacity: compact ? 0.11 : 0.17 },
    { radius: 0.84, radial: 0.054, depth: 0.076, gap: 0.36, dash: 4, seed: 0.43, tiltX: -0.34, tiltY: 0.92, speed: 0.26, opacity: compact ? 0.1 : 0.16 },
    { radius: 1.02, radial: 0.112, depth: 0.028, gap: 0.46, dash: 1, seed: 0.27, tiltX: -0.92, tiltY: -0.18, speed: -0.2, opacity: compact ? 0.09 : 0.14 },
    { radius: 1.17, radial: 0.03, depth: 0.09, gap: 0.22, dash: 3, seed: 0.62, tiltX: -0.2, tiltY: -0.86, speed: -0.28, opacity: compact ? 0.08 : 0.13 },
  ];

  for (const config of flatRingConfigs) {
    const material = createFlatRingMaterial(paletteValues, config.opacity);
    const flatRing = new THREE.Mesh(
      createRectCrossSectionRing(
        config.radius,
        config.radial,
        config.depth,
        preset.ringSegments,
        config.gap,
        config.dash,
        config.seed,
      ),
      material,
    );
    flatRing.rotation.x = config.tiltX;
    flatRing.rotation.y = config.tiltY;
    flatRing.userData.speed = config.speed;
    flatRing.userData.baseOpacity = config.opacity;
    flatRingMaterials.push(material);
    ringGroup.add(flatRing);
  }

  const spokeMaterial = new THREE.LineBasicMaterial({
    color: paletteValues.tertiary,
    transparent: true,
    opacity: compact ? 0.11 : 0.16,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const spokes = new THREE.LineSegments(createSpokes(Math.max(26, Math.round(preset.ringSegments * 0.44))), spokeMaterial);
  spokes.rotation.x = 1.16;
  spokes.rotation.z = 0.2;
  spokes.userData.speed = -0.18;
  spokes.userData.baseOpacity = 0.12;
  lineMaterials.push(spokeMaterial);
  ringGroup.add(spokes);

  let target: JarvisStateTarget = { ...resolveStateTarget(initialState) };
  const current: JarvisStateTarget = { ...target };
  let intensityOverride: number | null = null;
  const pointerTarget = { x: 0, y: 0, active: 0 };
  const pointerCurrent = { x: 0, y: 0, active: 0 };
  const manualSpin = { x: 0, y: 0, velocityX: 0, velocityY: 0, active: 0 };
  let breathing = false;
  let breathingIntensity = 1;
  let pulseEnergy = 0.15;
  let paused = false;
  let disposed = false;
  let raf = 0;
  let last = performance.now();
  let lastPaint = last;
  const start = last;
  let idleTimer: number | null = null;
  let lastWidth = 0;
  let lastHeight = 0;
  let frameIndex = 0;

  function applyPalette(next: JarvisPalette) {
    const colors = resolvePalette(next);
    paletteValues = colors;

    coreMaterial.uniforms.uCore.value.setHex(colors.core);
    coreMaterial.uniforms.uPrimary.value.setHex(colors.primary);
    particleMaterial.uniforms.uPrimary.value.setHex(colors.primary);
    particleMaterial.uniforms.uAccent.value.setHex(colors.tertiary);
    dataPacketMaterial.uniforms.uCore.value.setHex(colors.core);
    dataPacketMaterial.uniforms.uPrimary.value.setHex(colors.primary);
    for (const material of flatRingMaterials) {
      material.uniforms.uColor.value.setHex(colors.primary);
    }
    innerMaterial.color.setHex(colors.core);
    haloMaterial.color.setHex(colors.primary);
    lineMaterials[0].color.setHex(colors.primary);
    for (let i = 1; i < lineMaterials.length - 1; i += 1) {
      lineMaterials[i].color.setHex(colors.secondary);
    }
    spokeMaterial.color.setHex(colors.tertiary);

    haloTexture.dispose();
    haloTexture = createHaloTexture(new THREE.Color(colors.primary));
    haloMaterial.map = haloTexture;
    haloMaterial.needsUpdate = true;
  }

  function resize() {
    // Use layout dimensions, not getBoundingClientRect(). The chat panel and
    // launcher animate with CSS transforms; transformed rects can be smaller
    // during mount and would leave WebGL rendering into a low-res buffer.
    const parent = canvas.parentElement;
    const width = Math.max(
      2,
      canvas.clientWidth || canvas.offsetWidth || parent?.clientWidth || preset.px,
    );
    const height = Math.max(
      2,
      canvas.clientHeight || canvas.offsetHeight || parent?.clientHeight || preset.px,
    );
    if (Math.abs(width - lastWidth) < 0.5 && Math.abs(height - lastHeight) < 0.5) return;

    lastWidth = width;
    lastHeight = height;

    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  function render(now: number) {
    raf = 0;
    if (paused || disposed) return;
    if (frameInterval > 0 && now - lastPaint < frameInterval - 1) {
      raf = requestAnimationFrame(render);
      return;
    }
    lastPaint = now;

    const elapsed = (now - start) / 1000;
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;

    const stateSpeed = 0.08;
    current.energy = lerp(current.energy, target.energy, stateSpeed);
    current.rotationSpeed = lerp(current.rotationSpeed, target.rotationSpeed, stateSpeed);
    current.particleSpeed = lerp(current.particleSpeed, target.particleSpeed, stateSpeed);
    current.shellRadius = lerp(current.shellRadius, target.shellRadius, stateSpeed);
    current.ringSpread = lerp(current.ringSpread, target.ringSpread, stateSpeed);
    current.filamentOpacity = lerp(current.filamentOpacity, target.filamentOpacity, stateSpeed);
    current.coreScale = lerp(current.coreScale, target.coreScale, stateSpeed);
    current.bloom = lerp(current.bloom, target.bloom, stateSpeed);

    pointerCurrent.x = lerp(pointerCurrent.x, pointerTarget.x, 0.14);
    pointerCurrent.y = lerp(pointerCurrent.y, pointerTarget.y, 0.14);
    pointerCurrent.active = lerp(pointerCurrent.active, pointerTarget.active, 0.12);
    manualSpin.x += manualSpin.velocityX;
    manualSpin.y += manualSpin.velocityY;
    manualSpin.velocityX *= manualSpin.active ? 0.72 : 0.94;
    manualSpin.velocityY *= manualSpin.active ? 0.72 : 0.94;
    manualSpin.x = Math.max(-TAU * 1.25, Math.min(TAU * 1.25, manualSpin.x));
    pulseEnergy *= 0.925;

    const hover = pointerCurrent.active;
    const pulse = Math.min(1.7, pulseEnergy);
    const energy = intensityOverride ?? current.energy;
    const breathAmount = breathing ? breathingIntensity : 0;
    const breathWave = Math.sin(elapsed * 1.55);
    const breathInhale = breathing ? 0.5 + breathWave * 0.5 : 0;
    const breathScale = 1 + breathWave * breathAmount * (compact ? 0.024 : 0.034);
    const shellRadius = current.shellRadius + pulse * 0.025 + hover * 0.018;
    const time = elapsed * current.particleSpeed;

    interactionGroup.rotation.x = manualSpin.x;
    interactionGroup.rotation.y = manualSpin.y;
    root.scale.setScalar(preset.sceneScale * breathScale);
    root.rotation.y += dt * current.rotationSpeed * 0.72;
    root.rotation.x = Math.sin(elapsed * 0.32) * 0.055 + pointerCurrent.y * 0.18;
    root.rotation.z = pointerCurrent.x * 0.09;
    particlePoints.rotation.y -= dt * (0.13 + current.rotationSpeed * 0.08);
    dataPackets.rotation.y += dt * (0.16 + current.rotationSpeed * 0.1);
    dataPackets.rotation.x = Math.sin(elapsed * 0.26) * 0.07 + pointerCurrent.y * 0.08;
    filaments.rotation.y += dt * (0.09 + current.rotationSpeed * 0.05);
    coreGroup.position.set(pointerCurrent.x * 0.035, pointerCurrent.y * 0.035, 0);
    coreGroup.scale.setScalar(current.coreScale + pulse * 0.08 + hover * 0.03 + breathWave * breathAmount * (compact ? 0.014 : 0.028));
    ringGroup.scale.setScalar(current.ringSpread + pulse * 0.035 + breathWave * breathAmount * (compact ? 0.008 : 0.016));
    halo.scale.setScalar((compact ? 1.75 : 2.6) + current.bloom * (compact ? 0.32 : 0.72) + pulse * (compact ? 0.16 : 0.42) + hover * (compact ? 0.08 : 0.18) + breathInhale * breathAmount * (compact ? 0.12 : 0.3));
    haloMaterial.opacity = (compact ? 0.12 : 0.28) + current.bloom * (compact ? 0.08 : 0.22) + pulse * (compact ? 0.04 : 0.12) + hover * (compact ? 0.03 : 0.08) + breathInhale * breathAmount * (compact ? 0.028 : 0.065);

    coreMaterial.uniforms.uTime.value = elapsed;
    coreMaterial.uniforms.uEnergy.value = energy;
    coreMaterial.uniforms.uPulse.value = pulse;
    particleMaterial.uniforms.uTime.value = time;
    particleMaterial.uniforms.uEnergy.value = energy;
    particleMaterial.uniforms.uPulse.value = pulse;
    dataPacketMaterial.uniforms.uTime.value = time;
    dataPacketMaterial.uniforms.uEnergy.value = energy;
    dataPacketMaterial.uniforms.uPulse.value = pulse;

    if (
      filamentFrameStride === 1 ||
      frameIndex % filamentFrameStride === 0 ||
      hover > 0.03 ||
      pulse > 0.18
    ) {
      updateFilaments(filamentData, time, shellRadius, pulse, pointerCurrent.x, pointerCurrent.y);
    }
    filamentMaterial.opacity = ((compact ? 0.035 : 0.07) + current.filamentOpacity * (compact ? 0.14 : 0.28) + pulse * (compact ? 0.025 : 0.06) + hover * (compact ? 0.012 : 0.025)) * clamp01(energy);
    innerMaterial.opacity = (compact ? 0.34 : 0.46) + current.bloom * (compact ? 0.08 : 0.2) + pulse * (compact ? 0.06 : 0.18);

    for (const child of ringGroup.children) {
      child.rotation.z += dt * ((child.userData.speed as number | undefined) ?? 0.25) * current.rotationSpeed;
      const material = (child as THREE.LineSegments<THREE.BufferGeometry, THREE.Material>).material;
      const baseOpacity = (child.userData.baseOpacity as number | undefined) ?? 0.25;
      const opacity = baseOpacity * (0.92 + current.bloom * 0.48 + pulse * 0.42 + hover * 0.18);
      if (material instanceof THREE.ShaderMaterial && material.uniforms.uOpacity) {
        material.uniforms.uOpacity.value = opacity;
        material.uniforms.uPulse.value = pulse;
        material.uniforms.uTime.value = elapsed;
      } else {
        material.opacity = opacity;
      }
    }

    spokes.rotation.z -= dt * (0.12 + current.rotationSpeed * 0.18);
    core.rotation.x += dt * (0.18 + current.rotationSpeed * 0.12);
    core.rotation.y -= dt * (0.22 + current.rotationSpeed * 0.18);

    renderer.render(scene, camera);
    frameIndex += 1;
    raf = requestAnimationFrame(render);
  }

  resize();
  updateFilaments(filamentData, 0, target.shellRadius, pulseEnergy, 0, 0);
  raf = requestAnimationFrame(render);

  return {
    setState(state) {
      const resolved = resolveStateTarget(state);
      // Applying the mood the orb already holds must not flare it. PetMark
      // passes an object, and the old fallthrough kick was the thinking one.
      if (sameStateTarget(target, resolved)) return;
      target = { ...resolved };

      const name: JarvisStateName | null = typeof state === "string" ? state : null;
      pulseEnergy = Math.max(pulseEnergy, stateChangeKick(state));

      if (idleTimer) window.clearTimeout(idleTimer);
      if (name === "success" || name === "alert") {
        idleTimer = window.setTimeout(() => {
          target = { ...STATE_TARGETS.idle };
          idleTimer = null;
        }, name === "success" ? 1450 : 1150);
      }
    },
    setPalette(next) {
      applyPalette(next);
    },
    setPointer(x, y, active) {
      pointerTarget.x = Math.max(-1, Math.min(1, x));
      pointerTarget.y = Math.max(-1, Math.min(1, y));
      pointerTarget.active = active ? 1 : 0;
    },
    setSpinActive(active) {
      manualSpin.active = active ? 1 : 0;
    },
    spinBy(deltaX, deltaY) {
      manualSpin.y += deltaX * 0.0065;
      manualSpin.x += deltaY * 0.0052;
      manualSpin.velocityY = deltaX * 0.0012;
      manualSpin.velocityX = deltaY * 0.00095;
      pulseEnergy = Math.max(pulseEnergy, 0.36);
    },
    setBreathing(enabled, intensity = 1) {
      breathing = enabled;
      breathingIntensity = Math.max(0.2, Math.min(2.4, intensity));
    },
    pulse(amount = 1) {
      pulseEnergy = Math.max(pulseEnergy, amount);
    },
    setIntensityOverride(value) {
      intensityOverride = value;
    },
    setPaused(nextPaused) {
      if (nextPaused === paused) return;
      paused = nextPaused;
      if (paused) {
        if (raf) cancelAnimationFrame(raf);
        raf = 0;
        return;
      }

      last = performance.now();
      lastPaint = last;
      if (!raf) raf = requestAnimationFrame(render);
    },
    resize,
    dispose() {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (idleTimer) window.clearTimeout(idleTimer);
      haloTexture.dispose();
      disposeScene(scene);
      // dispose() frees buffers, not the WebGL slot. loseContext hands it back.
      const lose = renderer.getContext().getExtension("WEBGL_lose_context") as {
        loseContext?: () => void;
      } | null;
      lose?.loseContext?.();
      renderer.dispose();
    },
  };
}
