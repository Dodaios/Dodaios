/**
 * The duel's secondary effects, all pooled and one draw call each:
 *
 * - `Puffs`: soft growing puffs (vent steam, impact dust, muzzle smoke), a
 *   points shader with a size and alpha per puff;
 * - `Debris`: small dark chips knocked off walls and floor, lit by the
 *   duel's lights, bouncing on the floor;
 * - `BodyFlash`: a body-sized energy shell that flares on a hit (the hit
 *   flash on a duellist, without touching their materials);
 * - `HeatHaze`: a faint rising shimmer over a hot barrel;
 * - `Shards`: glowing fragments of a shattered energy shield.
 *
 * Coordinates are world. Randomness is `Math.random` (looks only; the
 * match itself is deterministic in `combat/`).
 */
import {
  AdditiveBlending, BoxGeometry, BufferAttribute, BufferGeometry, CapsuleGeometry, Color, DoubleSide, DynamicDrawUsage,
  InstancedBufferAttribute, InstancedMesh, Matrix4, Mesh, MeshBasicMaterial, MeshStandardMaterial, NormalBlending, Object3D,
  PlaneGeometry, Points, Quaternion, ShaderMaterial, Vector3,
} from "three";

const PUFF_VERTEX = /* glsl */ `
attribute float aSize;
attribute float aAlpha;
attribute float aSeed;
uniform float viewportHeight;
varying float vAlpha;
varying float vSeed;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  float depth = max(0.05, -mv.z);
  gl_PointSize = aAlpha > 0.0 ? clamp(aSize * projectionMatrix[1][1] * viewportHeight * 0.5 / depth, 0.0, 512.0) : 0.0;
  // Puffs right in front of the lens fade out instead of filling the screen.
  vAlpha = aAlpha * smoothstep(0.5, 1.8, depth);
  vSeed = aSeed;
}`;

const PUFF_FRAGMENT = /* glsl */ `
uniform vec3 colour;
varying float vAlpha;
varying float vSeed;
void main() {
  vec2 p = gl_PointCoord - 0.5;
  float r = length(p) * 2.0;
  if (r > 1.0) discard;
  // A lumpy edge: a few lobes turned by the puff's seed.
  float ang = atan(p.y, p.x);
  float lump = 0.82 + 0.18 * sin(ang * 3.0 + vSeed * 6.28) * sin(ang * 5.0 - vSeed * 3.1);
  float a = smoothstep(lump, lump * 0.25, r) * clamp(vAlpha, 0.0, 1.0);
  gl_FragColor = vec4(colour, a);
}`;

/** Soft puffs that grow and fade: steam, dust, smoke. */
export class Puffs {
  readonly points: Points<BufferGeometry, ShaderMaterial>;
  private readonly pos: Float32Array;
  private readonly vel: Float32Array;
  private readonly size: Float32Array;
  private readonly alpha: Float32Array;
  private readonly seed: Float32Array;
  private readonly life: Float32Array;
  private readonly total: Float32Array;
  private readonly grow: Float32Array;
  private readonly peak: Float32Array;
  private next = 0;

  constructor(private readonly count: number, colour: Color, opacity = 1, private readonly lift = 0.8, private readonly drag = 1.6) {
    this.pos = new Float32Array(count * 3);
    this.vel = new Float32Array(count * 3);
    this.size = new Float32Array(count);
    this.alpha = new Float32Array(count);
    this.seed = new Float32Array(count);
    this.life = new Float32Array(count);
    this.total = new Float32Array(count).fill(1);
    this.grow = new Float32Array(count);
    this.peak = new Float32Array(count);
    const geo = new BufferGeometry();
    geo.setAttribute("position", new BufferAttribute(this.pos, 3).setUsage(DynamicDrawUsage));
    geo.setAttribute("aSize", new BufferAttribute(this.size, 1).setUsage(DynamicDrawUsage));
    geo.setAttribute("aAlpha", new BufferAttribute(this.alpha, 1).setUsage(DynamicDrawUsage));
    geo.setAttribute("aSeed", new BufferAttribute(this.seed, 1));
    const mat = new ShaderMaterial({
      uniforms: { colour: { value: colour.clone().multiplyScalar(opacity) }, viewportHeight: { value: 1080 } },
      vertexShader: PUFF_VERTEX,
      fragmentShader: PUFF_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: NormalBlending,
    });
    this.points = new Points(geo, mat);
    this.points.frustumCulled = false;
    this.points.renderOrder = 43;
  }

  /** `n` puffs at (x, y, z), drifting along (vx, vy, vz) ± `jitter`, growing from `size0` to `size1` metres over `seconds`. */
  emit(x: number, y: number, z: number, n: number, vx: number, vy: number, vz: number, jitter: number, size0: number, size1: number, seconds: number, alpha = 0.5): void {
    for (let k = 0; k < n; k++) {
      const i = this.next;
      this.next = (this.next + 1) % this.count;
      this.pos[i * 3] = x + (Math.random() - 0.5) * size0;
      this.pos[i * 3 + 1] = y + (Math.random() - 0.5) * size0;
      this.pos[i * 3 + 2] = z + (Math.random() - 0.5) * size0;
      this.vel[i * 3] = vx + (Math.random() * 2 - 1) * jitter;
      this.vel[i * 3 + 1] = vy + (Math.random() * 2 - 1) * jitter;
      this.vel[i * 3 + 2] = vz + (Math.random() * 2 - 1) * jitter;
      const t = seconds * (0.7 + Math.random() * 0.6);
      this.life[i] = this.total[i] = t;
      this.size[i] = size0;
      this.grow[i] = (size1 - size0) / t;
      this.peak[i] = alpha * (0.7 + Math.random() * 0.5);
      this.seed[i] = Math.random();
    }
    (this.points.geometry.attributes.aSeed as BufferAttribute).needsUpdate = true;
  }

  setViewportHeight(px: number): void {
    this.points.material.uniforms.viewportHeight.value = px;
  }

  update(dt: number): void {
    const drag = Math.exp(-dt * this.drag);
    for (let i = 0; i < this.count; i++) {
      if (this.life[i] <= 0) { this.alpha[i] = 0; continue; }
      this.life[i] -= dt;
      if (this.life[i] <= 0) { this.alpha[i] = 0; continue; }
      this.vel[i * 3] *= drag;
      this.vel[i * 3 + 1] = this.vel[i * 3 + 1] * drag + this.lift * dt;
      this.vel[i * 3 + 2] *= drag;
      this.pos[i * 3] += this.vel[i * 3] * dt;
      this.pos[i * 3 + 1] += this.vel[i * 3 + 1] * dt;
      this.pos[i * 3 + 2] += this.vel[i * 3 + 2] * dt;
      this.size[i] += this.grow[i] * dt;
      const k = 1 - this.life[i] / this.total[i];
      // Quick in, slow out.
      this.alpha[i] = this.peak[i] * Math.min(1, k * 8) * (1 - k) * (1 - k);
    }
    const a = this.points.geometry.attributes;
    a.position.needsUpdate = true;
    a.aSize.needsUpdate = true;
    a.aAlpha.needsUpdate = true;
  }

  clear(): void {
    this.life.fill(0);
    this.alpha.fill(0);
    this.points.geometry.attributes.aAlpha.needsUpdate = true;
  }

  dispose(): void {
    this.points.geometry.dispose();
    this.points.material.dispose();
  }
}

/** Small chips knocked off a surface: lit, tumbling, bouncing on the floor. */
export class Debris {
  readonly mesh: InstancedMesh<BoxGeometry, MeshStandardMaterial>;
  private readonly pos: Float32Array;
  private readonly vel: Float32Array;
  private readonly spin: Float32Array;
  private readonly rot: Float32Array;
  private readonly scale: Float32Array;
  private readonly life: Float32Array;
  private next = 0;
  private readonly m = new Matrix4();
  private readonly q = new Quaternion();
  private readonly p = new Vector3();
  private readonly s = new Vector3();
  private readonly axis = new Vector3();

  constructor(private readonly count = 96) {
    const mat = new MeshStandardMaterial({ color: 0x2a2b2d, roughness: 0.55, metalness: 0.7 });
    this.mesh = new InstancedMesh(new BoxGeometry(1, 1, 1), mat, count);
    this.mesh.instanceMatrix.setUsage(DynamicDrawUsage);
    this.mesh.frustumCulled = false;
    this.mesh.count = count;
    this.pos = new Float32Array(count * 3);
    this.vel = new Float32Array(count * 3);
    this.spin = new Float32Array(count * 3);
    this.rot = new Float32Array(count);
    this.scale = new Float32Array(count);
    this.life = new Float32Array(count);
    for (let i = 0; i < count; i++) this.hide(i);
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  private hide(i: number): void {
    this.m.makeScale(0, 0, 0);
    this.mesh.setMatrixAt(i, this.m);
  }

  burst(x: number, y: number, z: number, nx: number, ny: number, nz: number, n: number, speed = 3.2): void {
    for (let k = 0; k < n; k++) {
      const i = this.next;
      this.next = (this.next + 1) % this.count;
      let vx = nx + (Math.random() * 2 - 1) * 0.9;
      let vy = ny + Math.random() * 0.9 + 0.2;
      let vz = nz + (Math.random() * 2 - 1) * 0.9;
      const l = Math.hypot(vx, vy, vz) || 1;
      const sp = speed * (0.4 + Math.random() * 0.8);
      vx = (vx / l) * sp; vy = (vy / l) * sp; vz = (vz / l) * sp;
      this.pos.set([x + nx * 0.03, y + ny * 0.03, z + nz * 0.03], i * 3);
      this.vel.set([vx, vy, vz], i * 3);
      this.spin.set([Math.random() - 0.5, Math.random() - 0.5, Math.random() - 0.5], i * 3);
      this.rot[i] = Math.random() * 6;
      this.scale[i] = 0.012 + Math.random() * 0.028;
      this.life[i] = 1.4 + Math.random() * 1.2;
    }
  }

  update(dt: number, floorY: number): void {
    for (let i = 0; i < this.count; i++) {
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt;
      if (this.life[i] <= 0) { this.hide(i); continue; }
      const o = i * 3;
      this.vel[o + 1] -= 9.8 * dt;
      this.pos[o] += this.vel[o] * dt;
      this.pos[o + 1] += this.vel[o + 1] * dt;
      this.pos[o + 2] += this.vel[o + 2] * dt;
      const ground = floorY + this.scale[i] * 0.5;
      if (this.pos[o + 1] < ground) {
        this.pos[o + 1] = ground;
        this.vel[o + 1] = Math.abs(this.vel[o + 1]) * 0.3;
        this.vel[o] *= 0.55;
        this.vel[o + 2] *= 0.55;
        if (this.vel[o + 1] < 0.25) this.vel[o + 1] = 0;
      }
      const moving = Math.hypot(this.vel[o], this.vel[o + 1], this.vel[o + 2]);
      this.rot[i] += dt * moving * 4;
      this.axis.set(this.spin[o], this.spin[o + 1], this.spin[o + 2]).normalize();
      this.q.setFromAxisAngle(this.axis, this.rot[i]);
      const sc = this.scale[i] * Math.min(1, this.life[i] / 0.3);
      this.s.set(sc, sc * 0.6, sc * 1.3);
      this.p.set(this.pos[o], this.pos[o + 1], this.pos[o + 2]);
      this.m.compose(this.p, this.q, this.s);
      this.mesh.setMatrixAt(i, this.m);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  clear(): void {
    this.life.fill(0);
    for (let i = 0; i < this.count; i++) this.hide(i);
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
    this.mesh.dispose();
  }
}

const SHELL_VERTEX = /* glsl */ `
varying vec3 vNormal;
varying vec3 vView;
varying float vHeight;
void main() {
  vec4 w = modelMatrix * vec4(position, 1.0);
  vNormal = normalize(mat3(modelMatrix) * normal);
  vView = normalize(cameraPosition - w.xyz);
  vHeight = position.y;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const SHELL_FRAGMENT = /* glsl */ `
uniform vec3 colour;
uniform float level;
uniform float time;
varying vec3 vNormal;
varying vec3 vView;
varying float vHeight;
void main() {
  float f = 1.0 - abs(dot(normalize(vNormal), normalize(vView)));
  float rim = pow(clamp(f, 0.0, 1.0), 3.0);
  // Crackle: thin bands running over the shell.
  float band = smoothstep(0.92, 1.0, sin(vHeight * 38.0 - time * 60.0) * 0.5 + 0.5);
  float a = level * (rim * 1.1 + band * rim * 1.4 + 0.05);
  gl_FragColor = vec4(colour * a, a);
}`;

/** A duellist's hit flash: an energy shell over the body that flares and fades. */
export class BodyFlash {
  readonly mesh: Mesh<CapsuleGeometry, ShaderMaterial>;
  private level = 0;
  private time = 0;

  constructor() {
    // A body-sized capsule: 0.36 m radius, about 1.75 m tall, standing on y 0.
    const geo = new CapsuleGeometry(0.36, 1.0, 6, 14).translate(0, 0.88, 0);
    this.mesh = new Mesh(geo, new ShaderMaterial({
      uniforms: { colour: { value: new Color() }, level: { value: 0 }, time: { value: 0 } },
      vertexShader: SHELL_VERTEX,
      fragmentShader: SHELL_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: AdditiveBlending,
      side: DoubleSide,
    }));
    this.mesh.frustumCulled = false;
    this.mesh.visible = false;
    this.mesh.renderOrder = 44;
  }

  hit(colour: Color, gain: number): void {
    this.mesh.material.uniforms.colour.value.copy(colour).multiplyScalar(gain);
    this.level = 1;
  }

  update(dt: number, x: number, y: number, z: number, alive: boolean): void {
    this.time += dt;
    this.level = Math.max(0, this.level - dt / 0.13);
    this.mesh.visible = this.level > 0.01 && alive;
    this.mesh.position.set(x, y, z);
    const u = this.mesh.material.uniforms;
    u.level.value = this.level * this.level;
    u.time.value = this.time;
  }

  clear(): void {
    this.level = 0;
    this.mesh.visible = false;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
  }
}

const HAZE_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  // Camera-facing in x, upright in y.
  vec4 c = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  vec3 sx = vec3(length(modelMatrix[0].xyz), length(modelMatrix[1].xyz), 1.0);
  c.xy += position.xy * sx.xy;
  gl_Position = projectionMatrix * c;
}`;

const HAZE_FRAGMENT = /* glsl */ `
uniform float level;
uniform float time;
uniform vec3 colour;
varying vec2 vUv;
float n(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p); vec2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(n(i), n(i + vec2(1.0, 0.0)), f.x), mix(n(i + vec2(0.0, 1.0)), n(i + vec2(1.0, 1.0)), f.x), f.y);
}
void main() {
  vec2 p = vUv;
  float x = p.x + (noise(vec2(p.y * 6.0 - time * 3.0, time)) - 0.5) * 0.25;
  float column = smoothstep(0.5, 0.0, abs(x - 0.5));
  float rise = smoothstep(0.0, 0.15, p.y) * smoothstep(1.0, 0.35, p.y);
  float streak = noise(vec2(x * 14.0, p.y * 4.0 - time * 5.0));
  float a = level * column * rise * (0.25 + 0.75 * streak) * 0.22;
  gl_FragColor = vec4(colour * a, a);
}`;

/** A faint rising shimmer over a hot barrel. */
export class HeatHaze {
  readonly mesh: Mesh<PlaneGeometry, ShaderMaterial>;
  private time = 0;

  constructor() {
    this.mesh = new Mesh(new PlaneGeometry(1, 1).translate(0, 0.5, 0), new ShaderMaterial({
      uniforms: { level: { value: 0 }, time: { value: 0 }, colour: { value: new Color(1.0, 0.55, 0.25) } },
      vertexShader: HAZE_VERTEX,
      fragmentShader: HAZE_FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: AdditiveBlending,
    }));
    this.mesh.scale.set(0.16, 0.45, 1);
    this.mesh.frustumCulled = false;
    this.mesh.visible = false;
    this.mesh.renderOrder = 46;
  }

  /** `heat` 0..1; shows from 0.55 up, strongest when overheated or venting. */
  update(dt: number, at: Vector3 | null, heat: number, hot: boolean): void {
    this.time += dt;
    const level = at ? Math.max(hot ? 1 : 0, (heat - 0.55) / 0.45) : 0;
    this.mesh.visible = level > 0.02;
    if (!this.mesh.visible || !at) return;
    this.mesh.position.copy(at);
    const u = this.mesh.material.uniforms;
    u.level.value = Math.min(1, level);
    u.time.value = this.time;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
  }
}

/** A shattered shield's fragments: glowing triangles flung outward, spinning and falling. */
export class Shards {
  readonly mesh: InstancedMesh<BufferGeometry, MeshBasicMaterial>;
  private readonly pos: Float32Array;
  private readonly vel: Float32Array;
  private readonly spin: Float32Array;
  private readonly life: Float32Array;
  private readonly size: Float32Array;
  private readonly tint: Color[] = [];
  private next = 0;
  private readonly dummy = new Object3D();
  private readonly colour = new Color();

  constructor(private readonly count = 72) {
    const geo = new BufferGeometry();
    geo.setAttribute("position", new BufferAttribute(new Float32Array([0, 0.6, 0, -0.5, -0.4, 0, 0.55, -0.3, 0]), 3));
    const mat = new MeshBasicMaterial({ color: 0xffffff, transparent: true, depthWrite: false, blending: AdditiveBlending, side: DoubleSide, toneMapped: true });
    this.mesh = new InstancedMesh(geo, mat, count);
    this.mesh.instanceMatrix.setUsage(DynamicDrawUsage);
    this.mesh.instanceColor = new InstancedBufferAttribute(new Float32Array(count * 3), 3);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 47;
    this.pos = new Float32Array(count * 3);
    this.vel = new Float32Array(count * 3);
    this.spin = new Float32Array(count * 3);
    this.life = new Float32Array(count);
    this.size = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      this.tint.push(new Color());
      this.dummy.scale.setScalar(0);
      this.dummy.updateMatrix();
      this.mesh.setMatrixAt(i, this.dummy.matrix);
    }
  }

  /** Break a shield panel at (x, floorY, z) facing `yaw`: fragments over its ±60° arc, 0.8 m out, 2 m high. */
  shatter(x: number, floorY: number, z: number, yaw: number, colour: Color, n = 48): void {
    for (let k = 0; k < n; k++) {
      const i = this.next;
      this.next = (this.next + 1) % this.count;
      const a = yaw + (Math.random() * 2 - 1) * (Math.PI / 3);
      const h = 0.1 + Math.random() * 1.8;
      const ox = Math.sin(a), oz = Math.cos(a);
      this.pos.set([x + ox * 0.8, floorY + h, z + oz * 0.8], i * 3);
      const sp = 1.2 + Math.random() * 2.6;
      this.vel.set([ox * sp + (Math.random() - 0.5), (Math.random() - 0.2) * 2, oz * sp + (Math.random() - 0.5)], i * 3);
      this.spin.set([Math.random() * 12 - 6, Math.random() * 12 - 6, Math.random() * 12 - 6], i * 3);
      this.life[i] = 0.5 + Math.random() * 0.5;
      this.size[i] = 0.05 + Math.random() * 0.09;
      this.tint[i].copy(colour);
    }
  }

  update(dt: number, floorY: number): void {
    for (let i = 0; i < this.count; i++) {
      const d = this.dummy;
      if (this.life[i] <= 0) continue;
      this.life[i] -= dt;
      const o = i * 3;
      if (this.life[i] <= 0) {
        d.scale.setScalar(0);
      } else {
        this.vel[o + 1] -= 6 * dt;
        this.pos[o] += this.vel[o] * dt;
        this.pos[o + 1] = Math.max(floorY + 0.01, this.pos[o + 1] + this.vel[o + 1] * dt);
        this.pos[o + 2] += this.vel[o + 2] * dt;
        d.position.set(this.pos[o], this.pos[o + 1], this.pos[o + 2]);
        d.rotation.set(d.rotation.x + this.spin[o] * dt, d.rotation.y + this.spin[o + 1] * dt, d.rotation.z + this.spin[o + 2] * dt);
        d.scale.setScalar(this.size[i]);
        const k = Math.min(1, this.life[i] / 0.6);
        this.mesh.setColorAt(i, this.colour.copy(this.tint[i]).multiplyScalar(k * k));
      }
      d.updateMatrix();
      this.mesh.setMatrixAt(i, d.matrix);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
  }

  clear(): void {
    this.life.fill(0);
    for (let i = 0; i < this.count; i++) {
      this.dummy.scale.setScalar(0);
      this.dummy.updateMatrix();
      this.mesh.setMatrixAt(i, this.dummy.matrix);
    }
    this.mesh.instanceMatrix.needsUpdate = true;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
    this.mesh.dispose();
  }
}
