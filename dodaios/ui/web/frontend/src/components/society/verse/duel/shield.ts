/**
 * The energy shield as it reads on screen: a translucent curved panel
 * 0.8 m in front of the body, ±60° around the aim and 2 m high (the combat
 * core's coverage, docs/verse/combat.md), drawn additively with a fine hex
 * lattice, bright edges and a slow scan line. Its strength follows the
 * shield's energy; the parry window shows as a hot rim; a blocked bolt
 * ripples out from where it struck (blue-white), a parry flashes the whole
 * panel gold-white, a break shatters it into a red flicker.
 */
import { AdditiveBlending, Color, CylinderGeometry, DoubleSide, Mesh, ShaderMaterial, Vector3 } from "three";
import type { PlayerView } from "../combat/view";

const VERTEX = /* glsl */ `
varying vec2 vUv;
varying vec3 vWorld;
void main() {
  vUv = uv;
  vec4 w = modelMatrix * vec4(position, 1.0);
  vWorld = w.xyz;
  gl_Position = projectionMatrix * viewMatrix * w;
}`;

const FRAGMENT = /* glsl */ `
uniform vec3 colour;
uniform vec3 flashColour;
uniform float strength;
uniform float flash;
uniform float rim;
uniform float time;
uniform vec3 hitPoint;
uniform float hitAge;
varying vec2 vUv;
varying vec3 vWorld;

float hexEdge(vec2 p) {
  p *= vec2(1.0, 1.1547);
  vec2 a = mod(p, vec2(1.0, 1.732)) - vec2(0.5, 0.866);
  vec2 b = mod(p + vec2(0.5, 0.866), vec2(1.0, 1.732)) - vec2(0.5, 0.866);
  vec2 g = dot(a, a) < dot(b, b) ? a : b;
  vec2 q = abs(g);
  float d = max(q.x * 0.866 + q.y * 0.5, q.y);
  return smoothstep(0.40, 0.47, d);
}

void main() {
  // Edges of the panel glow, the middle stays clear.
  float side = min(vUv.x, 1.0 - vUv.x);
  float vert = min(vUv.y, 1.0 - vUv.y);
  float edge = smoothstep(0.08, 0.0, side) + smoothstep(0.06, 0.0, vert) * 0.7;
  float body = smoothstep(0.0, 0.05, side) * smoothstep(0.0, 0.06, vert);
  float hex = hexEdge(vec2(vUv.x * 16.0, vUv.y * 13.0));
  float scan = smoothstep(0.03, 0.0, abs(fract(vUv.y - time * 0.35) - 0.5));
  float ripple = 0.0;
  if (hitAge < 0.6) {
    float d = distance(vWorld, hitPoint);
    float r = hitAge * 3.2;
    ripple = smoothstep(0.12, 0.0, abs(d - r)) * (1.0 - hitAge / 0.6) + smoothstep(0.35, 0.0, d) * (1.0 - hitAge / 0.6) * 1.5;
  }
  float a = strength * (0.035 * body + 0.1 * hex * body + 0.5 * edge + 0.12 * scan * body) + rim * edge * 1.5 + ripple * 2.0;
  vec3 c = colour * a + flashColour * flash * (0.25 * body + 0.8 * edge + 0.3 * hex * body);
  float alpha = clamp(a + flash * 0.5, 0.0, 1.0);
  gl_FragColor = vec4(max(c, vec3(0.0)), alpha);
}`;

const BLUE = new Color(0.35, 0.75, 1.6);
const PARRY = new Color(2.4, 1.9, 0.9);
const BREAK = new Color(2.2, 0.25, 0.12);

export class ShieldMesh {
  readonly mesh: Mesh<CylinderGeometry, ShaderMaterial>;
  private flash = 0;
  private hitAge = 10;
  private breakT = 0;
  private time = 0;
  private shown = 0;

  constructor(colour: Color) {
    // ±60° around +Z (three's cylinder starts its angle at +Z), 0.8 m out, 2 m high from the floor.
    const geo = new CylinderGeometry(0.8, 0.8, 2, 40, 1, true, -Math.PI / 3, (2 * Math.PI) / 3).translate(0, 1, 0);
    const mat = new ShaderMaterial({
      uniforms: {
        colour: { value: colour.clone().multiplyScalar(1.2).add(BLUE).multiplyScalar(0.5) },
        flashColour: { value: PARRY.clone() },
        strength: { value: 1 },
        flash: { value: 0 },
        rim: { value: 0 },
        time: { value: 0 },
        hitPoint: { value: new Vector3() },
        hitAge: { value: 10 },
      },
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: AdditiveBlending,
      side: DoubleSide,
    });
    this.mesh = new Mesh(geo, mat);
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 45;
    this.mesh.visible = false;
  }

  /** A bolt absorbed at (x, y, z) world. */
  block(x: number, y: number, z: number): void {
    this.mesh.material.uniforms.hitPoint.value.set(x, y, z);
    this.hitAge = 0;
    this.flash = Math.max(this.flash, 0.25);
    this.mesh.material.uniforms.flashColour.value.copy(BLUE);
  }

  parry(x: number, y: number, z: number): void {
    this.mesh.material.uniforms.hitPoint.value.set(x, y, z);
    this.hitAge = 0;
    this.flash = 1.4;
    this.mesh.material.uniforms.flashColour.value.copy(PARRY);
  }

  shatter(): void {
    this.breakT = 0.5;
    this.mesh.material.uniforms.flashColour.value.copy(BREAK);
    this.flash = 1;
  }

  update(dt: number, p: PlayerView, floorY: number): void {
    this.time += dt;
    this.hitAge += dt;
    this.flash = Math.max(0, this.flash - dt * 3.2);
    this.breakT = Math.max(0, this.breakT - dt);
    const want = p.alive && p.shieldUp ? 1 : 0;
    this.shown += (want - this.shown) * Math.min(1, dt * (want ? 30 : 14));
    const u = this.mesh.material.uniforms;
    const flicker = this.breakT > 0 ? (Math.sin(this.time * 90) > 0 ? 1 : 0.2) : 1;
    u.strength.value = this.shown * (0.35 + 0.65 * p.shieldEnergy) * flicker;
    u.flash.value = this.flash;
    u.rim.value = p.parrying ? 1 : 0;
    u.time.value = this.time;
    u.hitAge.value = this.hitAge;
    this.mesh.visible = this.shown > 0.02 || this.flash > 0.02 || this.breakT > 0;
    this.mesh.position.set(p.x, floorY, p.z);
    this.mesh.rotation.set(0, p.aimYaw, 0);
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
  }
}
