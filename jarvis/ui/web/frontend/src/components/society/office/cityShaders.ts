/**
 * The city's materials: every surface out there is a small shader instead of
 * a lit material, so the scene's sun never reaches the city and its light is
 * its own (windows, streets, traffic, the singularity). All of them share one
 * set of uniforms (time, the singularity's place, the palette), fade into the
 * same sky with their distance from the camera, and go through the renderer's
 * tone mapping like every other material, so the brightest cores roll off
 * softly instead of clipping.
 */
import { AdditiveBlending, BackSide, Color, DoubleSide, ShaderMaterial, Vector3 } from "three";
import { GROUND_Y } from "./cityPlan";

/** The palette, in sRGB hex (Color converts to linear light for the shaders). */
export const CITY_PALETTE = {
  /** The sky straight up, at the horizon, and the deep haze below it that far streets sink into. */
  zenith: "#03040b",
  horizon: "#241a46",
  below: "#0c0a1e",
  horizonGlow: "#33225f",
  /** The glow the singularity throws into the haze round it. */
  singularityGlow: "#ffb45e",
  /** Tower glass: the cladding and the sheen of the sky on it, cool away from the singularity and warm towards it. */
  cladding: "#06080f",
  sheenCool: "#2a3a6e",
  sheenWarm: "#6e5442",
  /** Lit windows. */
  windowCool: "#cfe2ff",
  windowWarm: "#ffbf7a",
  windowCyan: "#7fe9ff",
  /** Seams and crowns: cool white, cyan and gold. */
  accents: ["#e8f4ff", "#3fe6ff", "#ffc35a"],
  /** Low mist over the streets. */
  mist: "#16123a",
  /** Streets: the amber of the lamps, the cyan centre line of the avenues, headlights and tail lights. */
  amber: "#ff9d47",
  cyan: "#38d9ff",
  head: "#f2f6ff",
  tail: "#ff3b4e",
} as const;

export const colour = (hex: string): Color => new Color(hex);

export interface CityUniforms {
  uTime: { value: number };
  uSing: { value: Vector3 };
  uZenith: { value: Color };
  uHorizon: { value: Color };
  uBelow: { value: Color };
  uHorizonGlow: { value: Color };
  uSingGlow: { value: Color };
  /** Drawing-buffer height in px over 2·tan(fov/2): turns metres at a distance into pixels. */
  uPxScale: { value: number };
  [key: string]: { value: unknown };
}

export function cityUniforms(singularity: { x: number; y: number; z: number }): CityUniforms {
  return {
    uTime: { value: 0 },
    uSing: { value: new Vector3(singularity.x, singularity.y, singularity.z) },
    uZenith: { value: colour(CITY_PALETTE.zenith) },
    uHorizon: { value: colour(CITY_PALETTE.horizon) },
    uBelow: { value: colour(CITY_PALETTE.below) },
    uHorizonGlow: { value: colour(CITY_PALETTE.horizonGlow) },
    uSingGlow: { value: colour(CITY_PALETTE.singularityGlow) },
    uPxScale: { value: 800 },
  };
}

/** Shared GLSL: hashing, the sky in a direction, and the fade of anything at a distance into that sky. */
const COMMON = /* glsl */ `
uniform float uTime;
uniform vec3 uSing;
uniform vec3 uZenith;
uniform vec3 uHorizon;
uniform vec3 uBelow;
uniform vec3 uHorizonGlow;
uniform vec3 uSingGlow;
float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
float noise2(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), u.x), mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), u.x), u.y);
}
vec3 skyAt(vec3 dir) {
  float h = dir.y;
  vec3 col = h > 0.0 ? mix(uHorizon, uZenith, pow(min(h * 1.6, 1.0), 0.6)) : mix(uHorizon, uBelow, smoothstep(0.0, 0.32, -h));
  col += uHorizonGlow * exp(-abs(h) * 11.0) * 0.55;
  vec3 toSing = normalize(uSing - cameraPosition);
  float s = max(dot(dir, toSing), 0.0);
  col += uSingGlow * (pow(s, 6.0) * 0.025 + pow(s, 60.0) * 0.25);
  return col;
}
/** Anything far from the camera sinks into the sky behind it: clear for 150 m, then an exponential haze. */
vec3 aerial(vec3 col, vec3 world) {
  vec3 ray = world - cameraPosition;
  float f = 1.0 - exp(-max(length(ray) - 150.0, 0.0) / 560.0);
  return mix(col, skyAt(normalize(ray)), f);
}
float aerialFade(vec3 world) {
  return 1.0 - smoothstep(300.0, 950.0, length(world - cameraPosition));
}
`;

const OUTPUT = /* glsl */ `
  #include <tonemapping_fragment>
  #include <colorspace_fragment>
`;

function material(uniforms: CityUniforms, own: Record<string, { value: unknown }>, vertexShader: string, fragmentShader: string, extra: Partial<ShaderMaterial> = {}): ShaderMaterial {
  const m = new ShaderMaterial({ uniforms: { ...uniforms, ...own }, vertexShader, fragmentShader: COMMON + fragmentShader });
  m.fog = false;
  Object.assign(m, extra);
  return m;
}

const INSTANCED_WORLD = /* glsl */ `
  mat4 m = modelMatrix;
  #ifdef USE_INSTANCING
  m = m * instanceMatrix;
  #endif
`;

/**
 * Towers. Windows are drawn in world metres on every face (every tower shows windows of the same size, whatever
 * its scale), lit by a hash per window and re-rolled now and then so the city lives. Up close a window is a pane
 * in a frame; once a window is smaller than a pixel or two the face shows the lit share's average instead, so a
 * far tower never shimmers. Glass picks up the sky's sheen at grazing angles, warmer on faces turned to the
 * singularity. Some towers carry light seams on their corners with pulses running up them, some a lit crown;
 * roofs get a lit parapet, a landing ring or rooftop plant. Mist lies over the street level.
 */
export function towerMaterial(uniforms: CityUniforms): ShaderMaterial {
  return material(uniforms, {
    uClad: { value: colour(CITY_PALETTE.cladding) },
    uSheenCool: { value: colour(CITY_PALETTE.sheenCool) },
    uSheenWarm: { value: colour(CITY_PALETTE.sheenWarm) },
    uWinCool: { value: colour(CITY_PALETTE.windowCool) },
    uWinWarm: { value: colour(CITY_PALETTE.windowWarm) },
    uWinCyan: { value: colour(CITY_PALETTE.windowCyan) },
    uAccents: { value: CITY_PALETTE.accents.map(colour) },
    uMist: { value: colour(CITY_PALETTE.mist) },
    uGround: { value: GROUND_Y },
  }, /* glsl */ `
    attribute vec4 aLook;   // seed, lit share, seams (0/1), crown (0/1)
    attribute vec4 aTier;   // this tier's half width and depth and its top (unit tower), corners usable (0/1)
    attribute float aAccent;
    varying vec3 vWorld;
    varying vec3 vNormalW;
    varying vec3 vLocal;
    flat varying vec3 vScale;
    flat varying vec4 vLook;
    flat varying vec4 vTier;
    flat varying float vAccent;
    void main() {
      ${INSTANCED_WORLD}
      vScale = vec3(length(m[0].xyz), length(m[1].xyz), length(m[2].xyz));
      vec4 world = m * vec4(position, 1.0);
      vWorld = world.xyz;
      // Inverse-transpose for a rotation times a scale.
      vNormalW = normalize(mat3(m) * (normal / (vScale * vScale)));
      vLocal = position;
      vLook = aLook;
      vTier = aTier;
      vAccent = aAccent;
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    uniform vec3 uClad, uSheenCool, uSheenWarm, uWinCool, uWinWarm, uWinCyan, uMist;
    uniform vec3 uAccents[3];
    uniform float uGround;
    varying vec3 vWorld;
    varying vec3 vNormalW;
    varying vec3 vLocal;
    flat varying vec3 vScale;
    flat varying vec4 vLook;
    flat varying vec4 vTier;
    flat varying float vAccent;
    void main() {
      vec3 n = normalize(vNormalW);
      vec3 V = normalize(cameraPosition - vWorld);
      float seed = vLook.x, lit = vLook.y;
      vec3 accent = vAccent < 0.5 ? uAccents[0] : (vAccent < 1.5 ? uAccents[1] : uAccents[2]);
      float heightM = vScale.y;
      float above = vLocal.y * heightM;
      // The window grid and its screen-space size are taken before the roof/face branch: derivatives inside
      // non-uniform control flow are undefined, and would shimmer along every roof edge.
      float u = dot(vWorld.xz, vec2(-n.z, n.x));
      vec2 cellSize = vec2(1.4 + floor(fract(seed * 3.7) * 3.0) * 0.3, 3.6);
      vec2 c = vec2(u, vWorld.y) / cellSize;
      vec2 fw = max(fwidth(c), vec2(1e-4));
      vec3 col;
      if (n.y > 0.55) {
        // A roof: dark membrane, a lit parapet on some, a landing ring on a few, plant boxes on the rest.
        vec2 q = vLocal.xz / max(vTier.xy, vec2(1e-3));
        vec2 half_ = vTier.xy * vScale.xz;
        vec2 toEdge = (1.0 - abs(q)) * half_;
        float edge = min(toEdge.x, toEdge.y);
        col = uClad * 0.55;
        float rim = (1.0 - smoothstep(0.35, 0.8, edge)) * step(0.45, fract(seed * 7.13));
        col += accent * rim * 1.4;
        float r = length(q);
        float pad = (1.0 - smoothstep(0.0, 0.05, abs(r - 0.5))) * step(0.8, fract(seed * 29.7));
        col += uWinWarm * pad * 1.2;
        vec2 cellR = floor(vLocal.xz * vScale.xz / 2.4);
        float plant = step(0.86, hash12(cellR + seed * 51.0)) * step(1.6, edge);
        col += uWinCool * plant * 0.08;
      } else {
        // A face: glass, windows, seams, crown.
        vec2 id = floor(c);
        vec2 f = fract(c);
        // Light comes in offices: a run of windows on one storey lit together, a few dark desks in it, strays elsewhere.
        vec2 office = vec2(floor(id.x / 6.0), id.y);
        float h = hash12(office + seed * 57.0);
        float on = step(h, lit * 1.25) * step(hash12(id + seed * 173.0), 0.82);
        on = max(on, step(hash12(id * 2.3 + seed * 5.0), lit * 0.12));
        // Now and then an office switches.
        float swap = hash12(office * 1.7 + floor(uTime * 0.1 + h * 9.0) + seed * 11.0);
        on = swap > 0.994 ? 1.0 - on : on;
        float pick = hash12(office + 7.1 + seed * 31.0);
        vec3 wc = pick < 0.58 ? uWinCool : (pick < 0.93 ? uWinWarm : uWinCyan);
        float bright = (0.4 + 0.6 * hash12(office + 3.3)) * (0.85 + 0.15 * hash12(id + 1.9)) * (0.75 + 0.25 * f.y);
        // Storey-high glazing: slim mullions, a spandrel band between storeys.
        vec2 lo = vec2(0.08, 0.12), hi = vec2(0.92, 0.94);
        vec2 pane = smoothstep(lo, lo + fw, f) * (1.0 - smoothstep(hi - fw, hi, f));
        float px = max(fw.x, fw.y);
        float far = smoothstep(0.14, 0.42, px);
        float win = mix(pane.x * pane.y * on * bright, lit * 0.55, far);
        vec3 winCol = mix(wc, mix(uWinCool, uWinWarm, 0.32), far);
        float fres = pow(1.0 - max(dot(n, V), 0.0), 3.0);
        vec2 toSing = normalize(uSing.xz - vWorld.xz);
        float facing = max(dot(normalize(n.xz + 1e-4), toSing), 0.0);
        vec3 sheen = mix(uSheenCool, uSheenWarm, facing * facing * 0.45);
        float rise = clamp(above / max(heightM, 1.0), 0.0, 1.0);
        col = uClad * (0.5 + 0.4 * rise) + sheen * (0.025 + fres * 0.16);
        // Dark panes mirror a little of the sky; a faint line between storeys catches the light.
        col += sheen * 0.1 * pane.x * pane.y * (1.0 - on) * (1.0 - far);
        col += sheen * 0.05 * (1.0 - smoothstep(0.0, 0.06 + fw.y, f.y)) * (1.0 - far);
        col += winCol * win * 1.15;
        // Corner seams, pulses running up them.
        vec2 toSide = (vTier.xy - abs(vLocal.xz)) * vScale.xz;
        float corner = max(toSide.x, toSide.y);
        float seam = (1.0 - smoothstep(0.12, 0.4, corner)) * vLook.z * vTier.w;
        float pulse = 0.45 + 0.55 * pow(0.5 + 0.5 * sin(vWorld.y * 0.06 - uTime * 1.8 + seed * 40.0), 3.0);
        col += accent * seam * pulse * 1.3;
        // A lit crown band under the top of the tier.
        float top = vTier.z * heightM - above;
        col += accent * vLook.w * (1.0 - smoothstep(0.6, 1.4, abs(top - 2.4))) * 1.6;
      }
      // Mist over the streets.
      float low = exp(-max(vWorld.y - uGround, 0.0) / 48.0);
      col = mix(col, uMist, low * 0.7);
      col = aerial(col, vWorld);
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `);
}

/**
 * Street level: dark blocks with the dots of low roofs, amber streets, avenues with a cyan centre line and the
 * light of traffic running along them in both directions, and the lit rings of the plaza round the building's
 * foot. Lines thinner than a pixel turn into their average glow instead of shimmering.
 */
export function groundMaterial(uniforms: CityUniforms, centre: { x: number; z: number }, cell: number, avenueEvery: number, plazaRadius: number): ShaderMaterial {
  return material(uniforms, {
    uCentre: { value: [centre.x, centre.z] },
    uCell: { value: cell },
    uAvenue: { value: cell * avenueEvery },
    uPlaza: { value: plazaRadius },
    uAmber: { value: colour(CITY_PALETTE.amber) },
    uCyan: { value: colour(CITY_PALETTE.cyan) },
    uHead: { value: colour(CITY_PALETTE.head) },
    uTail: { value: colour(CITY_PALETTE.tail) },
    uMist: { value: colour(CITY_PALETTE.mist) },
  }, /* glsl */ `
    varying vec3 vWorld;
    void main() {
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    uniform vec2 uCentre;
    uniform float uCell, uAvenue, uPlaza;
    uniform vec3 uAmber, uCyan, uHead, uTail, uMist;
    varying vec3 vWorld;
    float line(float d, float halfW, float fw) { return 1.0 - smoothstep(halfW, halfW + fw, d); }
    void main() {
      // The grid runs on absolute multiples of the cell, like the plan's lots; the plaza rings round the building.
      vec2 p = vWorld.xz;
      float fw = max(fwidth(p.x), fwidth(p.y));
      vec2 ds = abs(fract(p / uCell + 0.5) - 0.5) * uCell;
      vec2 da = abs(fract(p / uAvenue + 0.5) - 0.5) * uAvenue;
      float streetX = line(ds.x, 2.6, fw), streetZ = line(ds.y, 2.6, fw);
      float aveX = line(da.x, 4.6, fw), aveZ = line(da.y, 4.6, fw);
      float street = max(streetX, streetZ), avenue = max(aveX, aveZ);
      // Blocks: dark, with the scattered lights of low roofs.
      vec2 lotCell = floor(p / 3.0);
      float dots = step(0.96, hash12(lotCell)) * (0.35 + 0.65 * hash12(lotCell + 9.0));
      vec3 col = uMist * 0.12 + uAmber * dots * 0.1 * (1.0 - street);
      // Roads are dark asphalt with a row of lamps along each kerb; an avenue has a cyan centre line and traffic both ways.
      col = mix(col, uAmber * 0.035, street);
      float kerbs = max(line(abs(ds.x - 2.2), 0.35, fw) * streetX, line(abs(ds.y - 2.2), 0.35, fw) * streetZ);
      float aveKerbs = max(line(abs(da.x - 4.2), 0.4, fw) * aveX, line(abs(da.y - 4.2), 0.4, fw) * aveZ);
      col += uAmber * kerbs * 0.2 + uHead * aveKerbs * 0.3;
      float centreLine = max(line(da.x, 0.3, fw) * aveX, line(da.y, 0.3, fw) * aveZ);
      col += uCyan * centreLine * 0.55;
      // Traffic: a car is a short bright dash on its side of the centre line.
      vec2 lineId = floor(p / uAvenue + 0.5);
      float sideX = sign(fract(p.x / uAvenue + 0.5) - 0.5), sideZ = sign(fract(p.y / uAvenue + 0.5) - 0.5);
      float runZ = fract(p.y / 21.0 - uTime * 0.55 * sideX + hash12(vec2(lineId.x, 3.0)));
      float runX = fract(p.x / 21.0 - uTime * 0.55 * sideZ + hash12(vec2(lineId.y, 7.0)));
      float laneX = line(abs(da.x - 2.2), 0.7, fw) * aveX, laneZ = line(abs(da.y - 2.2), 0.7, fw) * aveZ;
      float carsX = laneX * smoothstep(0.82, 0.97, runZ);
      float carsZ = laneZ * smoothstep(0.82, 0.97, runX);
      col += mix(uTail, uHead, step(0.0, sideX)) * carsX * 1.2;
      col += mix(uTail, uHead, step(0.0, sideZ)) * carsZ * 1.2;
      // From afar the lines are their average glow.
      float far = smoothstep(1.2, 5.0, fw);
      vec3 average = uMist * 0.14 + uAmber * 0.035 + uHead * 0.02 + uCyan * 0.015;
      col = mix(col, average, far);
      // The plaza round the building's foot: dark stone, lit rings.
      float r = length(vWorld.xz - uCentre);
      float plaza = 1.0 - smoothstep(uPlaza - 4.0, uPlaza, r);
      float rings = line(abs(fract(r / 9.0) - 0.5) * 9.0, 0.25, fw) * plaza;
      col = mix(col, uMist * 0.12, plaza);
      col += uCyan * rings * 0.25 * (0.6 + 0.4 * sin(r * 0.2 - uTime * 0.8));
      col = aerial(col, vWorld);
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `);
}

/** Slow, drifting mist between the rooftops: a soft additive sheet, clear over the plaza and gone at the edge. */
export function mistMaterial(uniforms: CityUniforms, centre: { x: number; z: number }, plazaRadius: number, strength: number, drift: number): ShaderMaterial {
  return material(uniforms, {
    uCentre: { value: [centre.x, centre.z] },
    uPlaza: { value: plazaRadius },
    uStrength: { value: strength },
    uDrift: { value: drift },
    uMist: { value: colour(CITY_PALETTE.mist) },
    uCyan: { value: colour(CITY_PALETTE.cyan) },
  }, /* glsl */ `
    varying vec3 vWorld;
    void main() {
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    uniform vec2 uCentre;
    uniform float uPlaza, uStrength, uDrift;
    uniform vec3 uMist, uCyan;
    varying vec3 vWorld;
    void main() {
      vec2 p = (vWorld.xz - uCentre) * 0.0065 + vec2(uTime * 0.004 * uDrift, uTime * 0.0025);
      float n = noise2(p) * 0.6 + noise2(p * 2.3 + 4.1) * 0.3 + noise2(p * 5.1 - 2.7) * 0.1;
      n = smoothstep(0.35, 0.85, n);
      float r = length(vWorld.xz - uCentre);
      float clear = smoothstep(uPlaza, uPlaza + 60.0, r);
      // Lit warm near the singularity, but never over its crater: mist there would veil the core.
      float toSing = length(uSing.xz - vWorld.xz);
      float lit = exp(-toSing / 260.0);
      vec3 col = mix(uMist, uSingGlow * 0.45, lit) + uCyan * 0.05;
      float a = n * clear * smoothstep(110.0, 220.0, toSing) * uStrength * aerialFade(vWorld);
      gl_FragColor = vec4(col * a, 1.0);
      ${OUTPUT}
    }
  `, { transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide });
}

/**
 * Flying traffic: every car is a camera-facing streak along its lane, computed on the GPU from its lane and the
 * time, so thousands of cars cost one draw call and no work per frame. A far streak is kept at least about a
 * pixel and a half wide and dimmed to match, so it neither vanishes nor flickers.
 */
export function trafficMaterial(uniforms: CityUniforms): ShaderMaterial {
  return material(uniforms, {}, /* glsl */ `
    uniform float uTime;
    uniform float uPxScale;
    attribute vec4 aOrbit;   // centre x, centre z, radius x, radius z
    attribute vec4 aMotion;  // height, phase, angular speed (signed), bob
    attribute vec4 aLook;    // colour, streak length
    varying vec2 vQuad;
    varying vec3 vColour;
    varying vec3 vWorld;
    varying float vDim;
    void main() {
      float ang = aMotion.y + uTime * aMotion.z;
      vec3 c = vec3(aOrbit.x + cos(ang) * aOrbit.z, aMotion.x + sin(ang * 2.0 + aMotion.y * 3.0) * aMotion.w, aOrbit.y + sin(ang) * aOrbit.w);
      vec3 tangent = normalize(vec3(-sin(ang) * aOrbit.z, 0.0, cos(ang) * aOrbit.w)) * sign(aMotion.z);
      vec3 toCam = cameraPosition - c;
      float dist = length(toCam);
      vec3 side = normalize(cross(tangent, toCam / dist));
      float minWidth = dist * 1.4 / uPxScale;
      float width = max(0.5, minWidth);
      vDim = 0.5 / width;
      vec3 p = c + tangent * position.x * aLook.w + side * position.y * width;
      vQuad = position.xy * 2.0;
      vColour = aLook.rgb;
      vWorld = p;
      gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
    }
  `, /* glsl */ `
    varying vec2 vQuad;
    varying vec3 vColour;
    varying vec3 vWorld;
    varying float vDim;
    void main() {
      float along = smoothstep(-1.0, 0.75, vQuad.x) * (1.0 - smoothstep(0.75, 1.0, vQuad.x));
      float across = 1.0 - vQuad.y * vQuad.y;
      float head = exp(-pow((vQuad.x - 0.82) * 6.0, 2.0)) * across;
      vec3 col = vColour * (along * pow(across, 2.0) * 0.9 + head * 2.2) * vDim;
      col *= aerialFade(vWorld);
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `, { transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide });
}

/** Aviation lights: points on the tall roofs, red ones breathing slowly, a few white strobes. */
export function beaconMaterial(uniforms: CityUniforms): ShaderMaterial {
  return material(uniforms, {
    uRed: { value: colour(CITY_PALETTE.tail) },
    uWhite: { value: colour(CITY_PALETTE.head) },
  }, /* glsl */ `
    uniform float uTime;
    uniform float uPxScale;
    attribute vec2 aBeacon;  // kind, phase
    varying float vKind;
    varying float vOn;
    varying vec3 vWorld;
    void main() {
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      vec4 mv = viewMatrix * world;
      vKind = aBeacon.x;
      float t = uTime + aBeacon.y * 10.0;
      vOn = aBeacon.x < 0.5 ? 0.25 + 0.75 * pow(0.5 + 0.5 * sin(t * 1.6), 4.0) : step(0.93, fract(t * 0.7));
      gl_PointSize = clamp(3.2 * uPxScale / -mv.z, 2.0, 18.0);
      gl_Position = projectionMatrix * mv;
    }
  `, /* glsl */ `
    uniform vec3 uRed, uWhite;
    varying float vKind;
    varying float vOn;
    varying vec3 vWorld;
    void main() {
      vec2 q = gl_PointCoord * 2.0 - 1.0;
      float r = dot(q, q);
      float glow = exp(-r * 5.0) + exp(-r * 40.0) * 2.0;
      vec3 col = (vKind < 0.5 ? uRed : uWhite) * glow * vOn * aerialFade(vWorld);
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `, { transparent: true, depthWrite: false, blending: AdditiveBlending });
}

/** A light beam: an open cylinder, brightest on its axis and at its foot, with pulses climbing it. */
export function beamMaterial(uniforms: CityUniforms): ShaderMaterial {
  return material(uniforms, {}, /* glsl */ `
    varying vec3 vWorld;
    varying vec3 vNormalW;
    varying float vRise;
    varying vec3 vColour;
    void main() {
      ${INSTANCED_WORLD}
      vec4 world = m * vec4(position, 1.0);
      vWorld = world.xyz;
      vNormalW = normalize(mat3(m) * vec3(normal.x, 0.0, normal.z));
      vRise = position.y;
      #ifdef USE_INSTANCING_COLOR
      vColour = instanceColor;
      #else
      vColour = vec3(1.0);
      #endif
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    varying vec3 vWorld;
    varying vec3 vNormalW;
    varying float vRise;
    varying vec3 vColour;
    void main() {
      vec3 V = normalize(cameraPosition - vWorld);
      float axis = pow(abs(dot(normalize(vNormalW), V)), 2.5);
      float fade = pow(1.0 - clamp(vRise, 0.0, 1.0), 1.6);
      float pulse = 0.7 + 0.3 * sin(vRise * 60.0 - uTime * 2.4);
      vec3 col = vColour * axis * fade * pulse * 1.4 * aerialFade(vWorld);
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `, { transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide });
}

/** The sky: a sphere round the camera, drawn first and behind everything; below the horizon the deep haze. */
export function skyMaterial(uniforms: CityUniforms): ShaderMaterial {
  return material(uniforms, {}, /* glsl */ `
    varying vec3 vWorld;
    void main() {
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    varying vec3 vWorld;
    void main() {
      vec3 dir = normalize(vWorld - cameraPosition);
      vec3 col = skyAt(dir);
      // Faint stars above the horizon only.
      // A star is a small dot inside some of the cells of a grid over the sky, never the whole cell.
      vec2 sky = vec2(atan(dir.z, dir.x) * 220.0, dir.y * 220.0);
      vec2 cellS = floor(sky);
      vec2 inCell = fract(sky) - 0.5 - (vec2(hash12(cellS + 3.1), hash12(cellS + 7.7)) - 0.5) * 0.6;
      float dot_ = 1.0 - smoothstep(0.04, 0.12, length(inCell));
      float star = step(0.9965, hash12(cellS)) * dot_ * smoothstep(0.02, 0.2, dir.y) * (0.4 + 0.6 * hash12(cellS + 1.3));
      col += vec3(star) * 0.9;
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `, { side: BackSide, depthWrite: false, depthTest: false });
}

// ---------------------------------------------------------------------------
// The singularity
// ---------------------------------------------------------------------------

/** The core: black, with a thin photon ring where the eye grazes it. */
export function coreMaterial(uniforms: CityUniforms): ShaderMaterial {
  return material(uniforms, { uRim: { value: colour("#ffe2b0") } }, /* glsl */ `
    varying vec3 vWorld;
    varying vec3 vNormalW;
    void main() {
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      vNormalW = normalize(mat3(modelMatrix) * normal);
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    uniform vec3 uRim;
    varying vec3 vWorld;
    varying vec3 vNormalW;
    void main() {
      vec3 V = normalize(cameraPosition - vWorld);
      float graze = 1.0 - max(dot(normalize(vNormalW), V), 0.0);
      vec3 col = uRim * pow(graze, 6.0) * 2.5;
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `);
}

/**
 * The accretion disc: white-hot at its inner edge through gold to violet at its rim, spiral arms turning
 * inwards, finer streams racing round, and the side coming towards the viewer brighter than the side going away.
 */
export function discMaterial(uniforms: CityUniforms, inner: number, outer: number): ShaderMaterial {
  return material(uniforms, {
    uInner: { value: inner },
    uOuter: { value: outer },
    uHot: { value: colour("#fff4e2") },
    uWarm: { value: colour("#ffaa52") },
    uCool: { value: colour("#6a4cff") },
    uRimC: { value: colour("#2ad4ff") },
  }, /* glsl */ `
    varying vec3 vLocal;
    varying vec3 vWorld;
    void main() {
      vLocal = position;
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    uniform float uInner, uOuter;
    uniform vec3 uHot, uWarm, uCool, uRimC;
    varying vec3 vLocal;
    varying vec3 vWorld;
    void main() {
      float r = length(vLocal.xy);
      float t = clamp((r - uInner) / (uOuter - uInner), 0.0, 1.0);
      float ang = atan(vLocal.y, vLocal.x);
      float spin = uTime * (0.9 / (0.25 + t));
      float arms = 0.5 + 0.5 * sin(ang * 3.0 + log(r) * 9.0 - spin);
      float streams = 0.5 + 0.5 * sin(ang * 23.0 + r * 0.35 - spin * 2.3);
      float grain = noise2(vec2(ang * 12.0 - spin, r * 0.18));
      vec3 col = mix(uHot * 1.7, uWarm * 0.95, smoothstep(0.0, 0.3, t));
      col = mix(col, uCool * 0.75, smoothstep(0.3, 0.85, t));
      col += uRimC * 0.25 * smoothstep(0.7, 0.95, t);
      float body = smoothstep(0.0, 0.025, t) * (1.0 - smoothstep(0.55, 1.0, t));
      float a = body * (0.3 + 0.45 * arms + 0.25 * streams) * (0.6 + 0.6 * grain);
      // Doppler beaming: the approaching side shines brighter.
      vec3 toCam = normalize(cameraPosition - uSing);
      vec3 tangent = normalize(vec3(-sin(ang), 0.0, cos(ang)));
      a *= 0.7 + 0.45 * dot(tangent, toCam);
      gl_FragColor = vec4(col * a, 1.0);
      ${OUTPUT}
    }
  `, { transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide });
}

/**
 * The lens: a camera-facing sheet round the core with the bright Einstein ring hugging its edge, a fainter
 * second ring and the wide glow the singularity throws into the night.
 */
export function lensMaterial(uniforms: CityUniforms, core: number, size: number): ShaderMaterial {
  return material(uniforms, {
    uSize: { value: size },
    /** The core's radius as a share of the sheet's half width. */
    uCore: { value: core / (size / 2) },
    uRing: { value: colour("#ffe7c0") },
    uViolet: { value: colour("#6d3bff") },
  }, /* glsl */ `
    uniform float uSize;
    varying vec2 vQ;
    varying vec3 vWorld;
    void main() {
      // -1..1 across the sheet.
      vQ = position.xy / (uSize * 0.5);
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    uniform float uCore;
    uniform vec3 uRing, uViolet;
    varying vec2 vQ;
    varying vec3 vWorld;
    void main() {
      float r = length(vQ) / uCore;
      float ring = exp(-pow((r - 1.06) / 0.035, 2.0)) * 3.0 + exp(-pow((r - 1.22) / 0.12, 2.0)) * 0.55;
      float shimmer = 0.85 + 0.15 * sin(atan(vQ.y, vQ.x) * 7.0 + uTime * 1.3);
      float halo = exp(-(r - 1.0) * 0.7) * 0.22;
      float edge = 1.0 - smoothstep(0.7, 1.0, length(vQ));
      vec3 col = (uRing * ring * shimmer + mix(uSingGlow, uViolet, smoothstep(1.0, 6.0, r)) * halo) * edge * step(1.0, r);
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `, { transparent: true, depthWrite: false, blending: AdditiveBlending });
}

/** The orbital rings round the singularity: thin gold filaments, pulses running round them. */
export function orbitalRingMaterial(uniforms: CityUniforms, direction: number): ShaderMaterial {
  return material(uniforms, {
    uGold: { value: colour("#ffc35a") },
    uDir: { value: direction },
    uMetal: { value: colour("#151829") },
  }, /* glsl */ `
    varying vec2 vUv;
    varying vec3 vWorld;
    varying vec3 vNormalW;
    void main() {
      vUv = uv;
      vec4 world = modelMatrix * vec4(position, 1.0);
      vWorld = world.xyz;
      vNormalW = normalize(mat3(modelMatrix) * normal);
      gl_Position = projectionMatrix * viewMatrix * world;
    }
  `, /* glsl */ `
    uniform vec3 uGold, uMetal;
    uniform float uDir;
    varying vec2 vUv;
    varying vec3 vWorld;
    varying vec3 vNormalW;
    void main() {
      vec3 V = normalize(cameraPosition - vWorld);
      float fres = pow(1.0 - abs(dot(normalize(vNormalW), V)), 2.0);
      float core = pow(1.0 - fres, 2.0);
      float run = pow(0.5 + 0.5 * sin(vUv.x * 6.2832 * 4.0 - uTime * 0.5 * uDir), 6.0);
      float ticks = smoothstep(0.9, 0.97, fract(vUv.x * 96.0)) * 0.6;
      vec3 col = uGold * core * (0.35 + ticks + 1.8 * run) + uMetal * 0.2;
      col *= aerialFade(vWorld);
      gl_FragColor = vec4(col, 1.0);
      ${OUTPUT}
    }
  `, { transparent: true, depthWrite: false, blending: AdditiveBlending });
}
