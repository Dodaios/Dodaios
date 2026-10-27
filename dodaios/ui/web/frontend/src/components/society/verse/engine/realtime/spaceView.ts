/**
 * Outside the hull (docs/verse/realtime.md): the Earth in low orbit, the sun
 * and the stars, drawn behind the deck in the eye-level view. The deck's own
 * star cards are hidden (realtimeScene), so every viewport looks into this.
 *
 * The space has its own camera at the origin that turns with the deck camera
 * but never moves: the planet is thousands of kilometres away, so walking
 * past a window changes the angle, never the parallax, as it would for real.
 * Lengths are in Earth radii.
 *
 * The Earth sits below and ahead of the deck's viewports (`outward`, from the
 * deck), turned so a chosen place faces the windows, and turns under the ship
 * at about orbital speed.
 */
import {
  AdditiveBlending, AlwaysDepth, BufferAttribute, BufferGeometry, CustomBlending, DataTexture, EqualStencilFunc, KeepStencilOp,
  LessEqualDepth, LinearFilter, LinearMipmapLinearFilter, Matrix3, Matrix4, Mesh, OneFactor, OneMinusDstAlphaFactor,
  OneMinusSrcAlphaFactor, PerspectiveCamera, Points, Quaternion, RedFormat, RepeatWrapping, ClampToEdgeWrapping, RGBAFormat,
  Scene, ShaderMaterial, SRGBColorSpace, NoColorSpace, Texture, Vector3, type Material, type WebGLRenderer,
} from "three";
import { fetchImageBitmap } from "../imageFetch";
import { SPACE_FRAGMENT, SPACE_VERTEX } from "./spaceShader";

/** The look of the view; QA runs override it through `window.__verseSpace`. */
export interface SpaceLook {
  /** Height of the orbit above the ground, km. */
  altitudeKm: number;
  /** How far below the horizon the Earth's centre lies, degrees (0: straight ahead). */
  centreDownDeg: number;
  /** Tilt of the horizon, degrees. */
  rollDeg: number;
  /** The place under the windows at the start, degrees. */
  latDeg: number;
  lonDeg: number;
  /** Sun direction relative to the windows: azimuth (right +), elevation, degrees. */
  sunAzimuthDeg: number;
  sunElevationDeg: number;
  sunRadiance: number;
  nightGain: number;
  hazeGain: number;
  starGain: number;
  /** Ground speed as a multiple of the real one (7.7 km/s). */
  orbitSpeed: number;
  /** QA: 0 leaves the planet pass out. */
  planet: number;
  /** QA: the windows' direction [x, z] instead of the deck's. */
  outward?: readonly [number, number];
}

export const SPACE_LOOK: SpaceLook = {
  altitudeKm: 900,
  centreDownDeg: 56,
  rollDeg: -9,
  // Looking north-west over the Atlantic towards North America.
  latDeg: 40,
  lonDeg: -68,
  // Sun ahead and high: its glint runs down the ocean towards the windows.
  sunAzimuthDeg: 15,
  sunElevationDeg: 32,
  sunRadiance: 8,
  nightGain: 3.0,
  hazeGain: 0.6,
  starGain: 1.0,
  orbitSpeed: 2.0,
  planet: 1,
};

const EARTH_KM = 6371;
const ORBIT_RAD_PER_S = 7.7 / EARTH_KM;
const STAR_COUNT = 9000;
const STAR_RADIUS = 50;

export interface SpaceTextures {
  day: string;
  night: string;
  clouds: string;
  relief: string;
}

export function spaceTextureUrls(base: string): SpaceTextures {
  const root = `${base}verse/space/`;
  return {
    day: `${root}earth_day.webp`,
    night: `${root}earth_night.webp`,
    clouds: `${root}earth_clouds.webp`,
    relief: `${root}earth_relief.webp`,
  };
}

function look(): SpaceLook {
  const override = (window as unknown as { __verseSpace?: Partial<SpaceLook> }).__verseSpace;
  return override ? { ...SPACE_LOOK, ...override } : SPACE_LOOK;
}

/** A small deterministic generator, so the sky is the same on every visit. */
function random(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Stars over the whole sky, crowded along a tilted galactic band; brightness falls off like real magnitudes. */
export function starField(count: number, seed = 7): { positions: Float32Array; colours: Float32Array; sizes: Float32Array } {
  const rand = random(seed);
  const positions = new Float32Array(count * 3);
  const colours = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const pole = new Vector3(0.35, 0.82, -0.45).normalize();
  const v = new Vector3();
  const temps = [
    [0.62, 0.72, 1.0], [0.8, 0.86, 1.0], [1.0, 1.0, 1.0], [1.0, 0.95, 0.82], [1.0, 0.82, 0.6], [1.0, 0.7, 0.5],
  ];
  for (let i = 0; i < count; i++) {
    // Half the stars hug the band: pull them towards the plane perpendicular to the pole.
    for (;;) {
      const z = rand() * 2 - 1;
      const a = rand() * Math.PI * 2;
      const r = Math.sqrt(1 - z * z);
      v.set(r * Math.cos(a), z, r * Math.sin(a));
      const band = Math.abs(v.dot(pole));
      if (i % 2 === 0 || rand() > band * 1.6) break;
    }
    positions.set([v.x * STAR_RADIUS, v.y * STAR_RADIUS, v.z * STAR_RADIUS], i * 3);
    // Magnitudes: many faint, few bright.
    const m = Math.pow(rand(), 5.5);
    const brightness = 0.06 + m * 3.5;
    const t = temps[Math.min(temps.length - 1, Math.floor(Math.pow(rand(), 0.8) * temps.length))];
    colours.set([t[0] * brightness, t[1] * brightness, t[2] * brightness], i * 3);
    sizes[i] = 1.0 + m * 2.2;
  }
  return { positions, colours, sizes };
}

const STAR_VERTEX = /* glsl */ `
attribute vec3 colour;
attribute float size;
uniform float pixelRatio;
uniform float gain;
varying vec3 vColour;
void main() {
  vColour = colour * gain;
  gl_PointSize = size * pixelRatio;
  gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
  // On the far plane, like the planet: drawn behind the deck, only where it left the depth empty.
  gl_Position.z = gl_Position.w;
}
`;

const STAR_FRAGMENT = /* glsl */ `
varying vec3 vColour;
void main() {
  vec2 c = gl_PointCoord * 2.0 - 1.0;
  float f = max( 1.0 - dot( c, c ), 0.0 );
  gl_FragColor = vec4( vColour * f * f, 1.0 );
}
`;

function placeholder(format: typeof RGBAFormat | typeof RedFormat, value: number): DataTexture {
  const data = new Uint8Array(format === RedFormat ? [value] : [value, value, value, 255]);
  const t = new DataTexture(data, 1, 1, format);
  t.needsUpdate = true;
  return t;
}

async function loadTexture(gl: WebGLRenderer, url: string, signal: AbortSignal, srgb: boolean, red: boolean): Promise<Texture> {
  let bitmap = await fetchImageBitmap(url, signal, "none");
  const max = gl.capabilities.maxTextureSize;
  if (bitmap.width > max) {
    const smaller = await createImageBitmap(bitmap, { resizeWidth: max, resizeHeight: Math.round((bitmap.height * max) / bitmap.width), resizeQuality: "high" });
    bitmap.close();
    bitmap = smaller;
  }
  const texture = new Texture(bitmap);
  texture.flipY = false;
  texture.colorSpace = srgb ? SRGBColorSpace : NoColorSpace;
  texture.format = red ? RedFormat : RGBAFormat;
  texture.wrapS = RepeatWrapping;
  texture.wrapT = ClampToEdgeWrapping;
  texture.generateMipmaps = true;
  texture.minFilter = LinearMipmapLinearFilter;
  texture.magFilter = LinearFilter;
  texture.anisotropy = Math.min(8, gl.capabilities.getMaxAnisotropy());
  texture.needsUpdate = true;
  return texture;
}

export class SpaceView {
  readonly scene = new Scene();
  readonly camera = new PerspectiveCamera(50, 1, 0.01, 200);
  private readonly planet: ShaderMaterial;
  private readonly planetMesh: Mesh;
  private readonly starPoints: Points;
  /** For QA runs: whether the textures arrived, and where the windows look. */
  readonly state = { ready: false, error: "", outward: [0, 0, 1] };
  private readonly stars: ShaderMaterial;
  private readonly owned: Texture[] = [];
  private readonly outward = new Vector3(0, 0, 1);
  private elapsed = 0;
  private readonly m3 = new Matrix3();
  private readonly m4 = new Matrix4();
  private readonly q = new Quaternion();
  private readonly v = Array.from({ length: 10 }, () => new Vector3());
  private readonly local = new Matrix3();

  constructor(steps: number) {
    const placeholders = [placeholder(RGBAFormat, 0), placeholder(RGBAFormat, 0), placeholder(RedFormat, 0), placeholder(RGBAFormat, 128)];
    this.owned.push(...placeholders);
    this.planet = new ShaderMaterial({
      vertexShader: SPACE_VERTEX,
      fragmentShader: SPACE_FRAGMENT,
      defines: { VIEW_STEPS: steps },
      uniforms: {
        verseInvViewProj: { value: new Matrix4() },
        earthCentre: { value: new Vector3() },
        worldToEarth: { value: new Matrix3() },
        spin: { value: 0 },
        cloudSpin: { value: 0 },
        sunDir: { value: new Vector3(0, 1, 0) },
        sunRadiance: { value: 1 },
        nightGain: { value: 1 },
        hazeGain: { value: 1 },
        ready: { value: 0 },
        dayMap: { value: placeholders[0] },
        nightMap: { value: placeholders[1] },
        cloudMap: { value: placeholders[2] },
        reliefMap: { value: placeholders[3] },
      },
      depthTest: false,
      depthWrite: false,
      transparent: true,
      blending: CustomBlending,
      blendSrc: OneFactor,
      blendDst: OneMinusSrcAlphaFactor,
      premultipliedAlpha: true,
    });
    const tri = new BufferGeometry();
    tri.setAttribute("position", new BufferAttribute(new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), 3));
    const quad = new Mesh(tri, this.planet);
    quad.frustumCulled = false;
    quad.renderOrder = 2;
    this.planetMesh = quad;

    const field = starField(STAR_COUNT);
    const starGeometry = new BufferGeometry();
    starGeometry.setAttribute("position", new BufferAttribute(field.positions, 3));
    starGeometry.setAttribute("colour", new BufferAttribute(field.colours, 3));
    starGeometry.setAttribute("size", new BufferAttribute(field.sizes, 1));
    this.stars = new ShaderMaterial({
      vertexShader: STAR_VERTEX,
      fragmentShader: STAR_FRAGMENT,
      uniforms: { pixelRatio: { value: 1 }, gain: { value: 1 } },
      depthTest: false,
      depthWrite: false,
      transparent: true,
      blending: AdditiveBlending,
    });
    const points = new Points(starGeometry, this.stars);
    points.frustumCulled = false;
    points.renderOrder = 1;
    this.starPoints = points;
    this.scene.add(points, quad);
  }

  /** Loads the Earth's textures; until then only the stars and the sun show. */
  async load(gl: WebGLRenderer, urls: SpaceTextures, signal: AbortSignal): Promise<void> {
    const [day, night, clouds, relief] = await Promise.all([
      loadTexture(gl, urls.day, signal, true, false),
      loadTexture(gl, urls.night, signal, true, false),
      loadTexture(gl, urls.clouds, signal, false, true),
      loadTexture(gl, urls.relief, signal, false, false),
    ]);
    if (signal.aborted) {
      for (const t of [day, night, clouds, relief]) t.dispose();
      signal.throwIfAborted();
    }
    this.owned.push(day, night, clouds, relief);
    const u = this.planet.uniforms;
    u.dayMap.value = day;
    u.nightMap.value = night;
    u.cloudMap.value = clouds;
    u.reliefMap.value = relief;
    u.ready.value = 1;
    this.state.ready = true;
  }

  /** The direction the deck's viewports look out of (world, horizontal). */
  setOutward(direction: Vector3): void {
    this.outward.set(direction.x, 0, direction.z);
    if (this.outward.lengthSq() < 1e-6) this.outward.set(0, 0, 1);
    this.outward.normalize();
    this.state.outward = this.outward.toArray();
  }

  update(deckCamera: PerspectiveCamera, dt: number, pixelRatio: number): void {
    const l = look();
    this.elapsed += dt;
    const cam = this.camera;
    cam.fov = deckCamera.fov;
    cam.aspect = deckCamera.aspect;
    cam.updateProjectionMatrix();
    deckCamera.getWorldQuaternion(this.q);
    cam.quaternion.copy(this.q);
    cam.position.set(0, 0, 0);
    cam.updateMatrixWorld();

    const [out, up, side, centre, target, tmp, north, pL, eL, nL] = this.v;
    const rad = Math.PI / 180;
    if (l.outward) out.set(l.outward[0], 0, l.outward[1]).normalize();
    else out.copy(this.outward);
    up.set(0, 1, 0);
    side.crossVectors(out, up).normalize(); // to the right when looking out
    // Horizon tilt: the whole frame turns about the outward axis.
    up.applyAxisAngle(out, l.rollDeg * rad);
    side.applyAxisAngle(out, l.rollDeg * rad);

    const distance = 1 + l.altitudeKm / EARTH_KM;
    const down = l.centreDownDeg * rad;
    centre.copy(out).multiplyScalar(Math.cos(down)).addScaledVector(up, -Math.sin(down)).multiplyScalar(distance);
    // The ground point facing the windows: where the outward ray meets the sphere, else the limb.
    const b = centre.dot(out);
    const h = b * b - (centre.lengthSq() - 1);
    target.copy(out).multiplyScalar(h > 0 ? b - Math.sqrt(h) : b).sub(centre).normalize();
    // World basis at that point: normal, east (right), north (up the view).
    const nW = target;
    const eW = tmp.copy(side).addScaledVector(nW, -side.dot(nW)).normalize();
    north.crossVectors(nW, eW);
    // Local basis of the chosen place (texture space: y north, longitude 0 at +x, east towards -z).
    const lat = l.latDeg * rad;
    const lon = l.lonDeg * rad;
    pL.set(Math.cos(lat) * Math.cos(lon), Math.sin(lat), -Math.cos(lat) * Math.sin(lon));
    eL.set(-Math.sin(lon), 0, -Math.cos(lon));
    nL.crossVectors(pL, eL);
    // worldToEarth = L * W^T (columns east, north, normal).
    const L = this.local.set(eL.x, nL.x, pL.x, eL.y, nL.y, pL.y, eL.z, nL.z, pL.z);
    const W = this.m3.set(eW.x, north.x, nW.x, eW.y, north.y, nW.y, eW.z, north.z, nW.z).transpose();
    const u = this.planet.uniforms;
    (u.worldToEarth.value as Matrix3).multiplyMatrices(L, W);
    (u.earthCentre.value as Vector3).copy(centre);
    // Ground moving under the ship towards the right of the windows.
    const turn = this.elapsed * ORBIT_RAD_PER_S * l.orbitSpeed;
    u.spin.value = -turn;
    u.cloudSpin.value = -turn * 1.04 + 0.35;
    const az = l.sunAzimuthDeg * rad;
    const el = l.sunElevationDeg * rad;
    (u.sunDir.value as Vector3)
      .copy(out).multiplyScalar(Math.cos(el) * Math.cos(az))
      .addScaledVector(side, Math.cos(el) * Math.sin(az))
      .addScaledVector(up, Math.sin(el))
      .normalize();
    this.planetMesh.visible = l.planet !== 0;
    u.sunRadiance.value = l.sunRadiance;
    u.nightGain.value = l.nightGain;
    u.hazeGain.value = l.hazeGain;
    this.stars.uniforms.pixelRatio.value = pixelRatio;
    this.stars.uniforms.gain.value = l.starGain;
    this.m4.multiplyMatrices(cam.matrixWorld, cam.projectionMatrixInverse);
    (u.verseInvViewProj.value as Matrix4).copy(this.m4);
  }

  /**
   * Behind a deck already drawn into the bound target (alpha cleared to 0, its
   * glass marked 1 in the stencil): space goes only where the deck left the
   * depth empty and glass covers, composited under what is there (front to
   * back: the planet, then the stars it dims). The full-screen planet shader
   * then runs on window pixels alone.
   */
  renderBehind(gl: WebGLRenderer): void {
    const autoClear = gl.autoClear;
    gl.autoClear = false;
    this.planetMesh.renderOrder = 1;
    this.starPoints.renderOrder = 2;
    for (const m of [this.planet, this.stars]) behind(m, true);
    gl.render(this.scene, this.camera);
    for (const m of [this.planet, this.stars]) behind(m, false);
    this.planet.blending = CustomBlending;
    this.stars.blending = AdditiveBlending;
    this.planetMesh.renderOrder = 2;
    this.starPoints.renderOrder = 1;
    gl.autoClear = autoClear;
  }

  /** Clears the bound target and draws space into it, then clears depth for the deck (the path without a stencil). */
  render(gl: WebGLRenderer): void {
    const autoClear = gl.autoClear;
    gl.autoClear = true;
    gl.render(this.scene, this.camera);
    gl.autoClear = autoClear;
    gl.clearDepth();
  }

  dispose(): void {
    this.planet.dispose();
    this.stars.dispose();
    for (const t of this.owned) t.dispose();
    this.scene.traverse((o) => (o as Mesh).geometry?.dispose());
  }
}

/** A material's state for drawing under the deck (`renderBehind`), or back to over-black. */
function behind(m: Material, on: boolean): void {
  m.depthTest = on;
  m.depthFunc = on ? LessEqualDepth : AlwaysDepth;
  m.stencilWrite = on; // three runs the stencil test only for materials that "write" it
  m.stencilFunc = EqualStencilFunc;
  m.stencilRef = 1;
  m.stencilWriteMask = 0;
  m.stencilFail = KeepStencilOp;
  m.stencilZFail = KeepStencilOp;
  m.stencilZPass = KeepStencilOp;
  if (on) {
    m.blending = CustomBlending;
    m.blendSrc = OneMinusDstAlphaFactor;
    m.blendDst = OneFactor;
    m.blendSrcAlpha = OneMinusDstAlphaFactor;
    m.blendDstAlpha = OneFactor;
  } else {
    m.blendSrc = OneFactor;
    m.blendDst = OneMinusSrcAlphaFactor;
    m.blendSrcAlpha = null;
    m.blendDstAlpha = null;
  }
}
