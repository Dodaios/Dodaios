/**
 * The duel blaster, built procedurally: a compact, sleek energy carbine in
 * graphite and brushed gold with glowing energy cells along the receiver,
 * heat vents on the shroud and an emitter ring at the muzzle.
 *
 * Local frame: +Z is the barrel's direction, +Y up, the origin is the
 * right hand's grip. `muzzle` and `fore` (where the left hand holds the
 * shroud) are fixed points in that frame. `setHeat` drives the cells and
 * vents from cool blue-white through amber to an overheated red, and pulses
 * them while venting.
 */
import {
  BoxGeometry, Color, CylinderGeometry, Group, Mesh, MeshStandardMaterial, TorusGeometry, Vector3, type BufferGeometry, type Material,
} from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

export interface Blaster {
  group: Group;
  /** Muzzle point and the left hand's hold point, local. */
  muzzle: Vector3;
  fore: Vector3;
  /** The centre of the holographic sight's window, local (aiming down the sights puts it on the eye line). */
  sight: Vector3;
  /** The sight's glowing pane (the first-person view swaps it for a see-through reticle). */
  sightGlass: Mesh;
  /** The stock's parts (the first-person view leaves them out: they would hide the right hand). */
  stock: Mesh[];
  materials: Material[];
  /** Heat 0..1; `venting` pulses the vents; `overheated` turns them red. */
  setHeat(heat: number, venting: boolean, overheated: boolean, timeS: number): void;
  dispose(): void;
}

/** Bolt colours (linear, before the HDR gain): the person's and the opponent's. */
export const BOLT_COLOURS = {
  own: new Color(1.0, 0.62, 0.16),
  foe: new Color(1.0, 0.13, 0.08),
  parry: new Color(1.0, 0.92, 0.7),
} as const;

const COOL = new Color(0.35, 0.75, 1.0);
const BLASTER_SCALE = 1.3;
const WARM = new Color(1.0, 0.55, 0.12);
const HOT = new Color(1.0, 0.12, 0.04);

export interface BlasterOptions {
  /**
   * Chamfer the boxes' edges so they catch the light (the first-person view, a hand's breadth from the eye).
   * The duellists' blasters, seen from metres away, keep plain boxes.
   */
  bevel?: boolean;
}

export function buildBlaster(accent: Color, options: BlasterOptions = {}): Blaster {
  const group = new Group();
  group.name = "DuelBlaster";
  // Built at true size, drawn a little larger so it reads at shoulder-camera distance.
  const parts = new Group();
  parts.scale.setScalar(BLASTER_SCALE);
  group.add(parts);
  const graphite = new MeshStandardMaterial({ name: "M_Blaster_Body", color: 0x16191d, metalness: 0.8, roughness: 0.3 });
  const steel = new MeshStandardMaterial({ name: "M_Blaster_Steel", color: 0x4a5058, metalness: 0.9, roughness: 0.26 });
  const gold = new MeshStandardMaterial({ name: "M_Blaster_Trim", color: 0xc9a24a, metalness: 1, roughness: 0.28 });
  const grip = new MeshStandardMaterial({ name: "M_Blaster_Grip", color: 0x0d0e10, metalness: 0.1, roughness: 0.75 });
  const cells = new MeshStandardMaterial({ name: "M_Blaster_Cells", color: 0x050505, emissive: accent.clone(), emissiveIntensity: 3, roughness: 0.4 });
  const vents = new MeshStandardMaterial({ name: "M_Blaster_Vents", color: 0x050505, emissive: COOL.clone(), emissiveIntensity: 0.6, roughness: 0.5 });
  const emitter = new MeshStandardMaterial({ name: "M_Blaster_Emitter", color: 0x050505, emissive: accent.clone(), emissiveIntensity: 5, roughness: 0.3 });
  const materials: Material[] = [graphite, steel, gold, grip, cells, vents, emitter];
  const geometries: BufferGeometry[] = [];

  const add = (geo: BufferGeometry, mat: MeshStandardMaterial, x: number, y: number, z: number, rx = 0, ry = 0, rz = 0): Mesh => {
    geometries.push(geo);
    const m = new Mesh(geo, mat);
    m.position.set(x, y, z);
    m.rotation.set(rx, ry, rz);
    m.castShadow = false;
    parts.add(m);
    return m;
  };
  const box = (w: number, h: number, d: number): BufferGeometry =>
    options.bevel ? new RoundedBoxGeometry(w, h, d, 1, Math.min(w, h, d) * 0.22) : new BoxGeometry(w, h, d);
  const alongZ = (geo: BufferGeometry) => geo.rotateX(Math.PI / 2);

  // Receiver: a long, slightly tapered block, a gold spine on top.
  add(box(0.056, 0.078, 0.32), graphite, 0, 0.012, 0.06);
  add(box(0.06, 0.03, 0.2), steel, 0, -0.03, 0.03);
  add(box(0.012, 0.008, 0.26), gold, 0, 0.055, 0.07);
  // Energy cells along both sides.
  add(box(0.004, 0.016, 0.17), cells, 0.0295, 0.016, 0.07);
  add(box(0.004, 0.016, 0.17), cells, -0.0295, 0.016, 0.07);
  // Shroud and barrel: an octagonal sleeve with vents, a slim barrel inside.
  add(alongZ(new CylinderGeometry(0.026, 0.03, 0.22, 8)), graphite, 0, 0.012, 0.31);
  add(alongZ(new CylinderGeometry(0.012, 0.012, 0.3, 10)), steel, 0, 0.012, 0.34);
  for (let i = 0; i < 3; i++) add(box(0.03, 0.006, 0.022), vents, 0, 0.04, 0.25 + i * 0.045);
  add(box(0.006, 0.022, 0.16), gold, 0, -0.018, 0.31);
  // Emitter ring and muzzle.
  add(new TorusGeometry(0.022, 0.005, 6, 16), emitter, 0, 0.012, 0.43);
  add(alongZ(new CylinderGeometry(0.02, 0.016, 0.04, 10)), steel, 0, 0.012, 0.47);
  // Optic: a low rail and a small holographic sight.
  add(box(0.028, 0.012, 0.08), steel, 0, 0.058, 0.0);
  // The sight's frame is open (four bars), so the first-person view can look through it.
  add(box(0.03, 0.004, 0.006), gold, 0, 0.091, 0.035);
  add(box(0.03, 0.004, 0.006), gold, 0, 0.066, 0.035);
  add(box(0.004, 0.03, 0.006), gold, 0.013, 0.0785, 0.035);
  add(box(0.004, 0.03, 0.006), gold, -0.013, 0.0785, 0.035);
  const sightGlass = add(new BoxGeometry(0.022, 0.021, 0.002), emitter, 0, 0.0785, 0.034);
  // Grip, trigger guard, a short angular stock.
  add(box(0.034, 0.105, 0.042), grip, 0, -0.06, -0.01, -0.28);
  add(box(0.008, 0.008, 0.07), steel, 0, -0.06, 0.04);
  const stock = [
    add(box(0.04, 0.06, 0.13), graphite, 0, -0.005, -0.15, 0.12),
    add(box(0.044, 0.07, 0.014), gold, 0, -0.01, -0.22, 0.12),
  ];

  const base = { cells: accent.clone() };
  const tmp = new Color();
  return {
    group,
    muzzle: new Vector3(0, 0.012, 0.49).multiplyScalar(BLASTER_SCALE),
    fore: new Vector3(0, -0.02, 0.29).multiplyScalar(BLASTER_SCALE),
    sight: new Vector3(0, 0.0785, 0.034).multiplyScalar(BLASTER_SCALE),
    sightGlass,
    stock,
    materials,
    setHeat(heat, venting, overheated, timeS) {
      const h = Math.max(0, Math.min(1, heat));
      if (overheated) tmp.copy(HOT);
      else if (h < 0.5) tmp.copy(COOL).lerp(WARM, h / 0.5);
      else tmp.copy(WARM).lerp(HOT, (h - 0.5) / 0.5);
      vents.emissive.copy(tmp);
      const pulse = venting ? 0.6 + 0.4 * Math.sin(timeS * 22) : 1;
      vents.emissiveIntensity = (0.4 + h * h * 9 + (overheated ? 6 : 0)) * pulse;
      cells.emissive.copy(base.cells).lerp(HOT, overheated ? 0.8 : h * 0.4);
      cells.emissiveIntensity = venting ? 2 : 6 + h * 4;
      emitter.emissiveIntensity = venting ? 1.2 : 4 + h * 4;
    },
    dispose() {
      for (const g of geometries) g.dispose();
      for (const m of materials) m.dispose();
    },
  };
}
