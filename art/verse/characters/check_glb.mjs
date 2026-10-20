// Verify the cooked crew glb files the way the runtime sees them (three.js GLTFLoader).
//
//   node art/verse/characters/check_glb.mjs
//
// Checks per model: skinned meshes, triangle count, material names, bone names,
// bounding box, facing (+Z), and that every clip track of the matching
// A_Human_<skeleton>.glb binds to a bone. For A_Walk it measures how far the planted
// foot moves while the root travels at the manifest walk speed (foot slide).
import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "../../..");
const front = join(repo, "dodaios/ui/web/frontend");
const out = join(front, "public/verse/characters");
const THREE = await import(pathToFileURL(join(front, "node_modules/three/build/three.module.js")));
const { GLTFLoader } = await import(
  pathToFileURL(join(front, "node_modules/three/examples/jsm/loaders/GLTFLoader.js"))
);

function load(file) {
  const buf = readFileSync(join(out, file));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new Promise((ok, fail) => new GLTFLoader().parse(ab, "", ok, fail));
}

const manifest = JSON.parse(readFileSync(join(out, "characters.json"), "utf8"));
let failures = 0;
const fail = (msg) => {
  failures += 1;
  console.log(`  FAIL ${msg}`);
};

const clipSets = {};
for (const [variant, sk] of Object.entries(manifest.skeletons)) {
  const g = await load(`A_Human_${variant}.glb`);
  clipSets[variant] = g.animations;
  console.log(`A_Human_${variant}: ${g.animations.map((a) => `${a.name}(${a.duration.toFixed(2)}s)`).join(" ")}`);
}

for (const m of manifest.models) {
  if (!m.skeleton) continue; // drones carry their own rig and clips
  const g = await load(`${m.id}.glb`);
  const root = g.scene;
  root.updateMatrixWorld(true);
  let tris = 0;
  const mats = new Set();
  const bones = new Set();
  let skinned = 0;
  root.traverse((o) => {
    if (o.isBone) bones.add(o.name);
    if (o.isSkinnedMesh) {
      skinned += 1;
      const idx = o.geometry.index;
      tris += (idx ? idx.count : o.geometry.attributes.position.count) / 3;
      mats.add(o.material.name);
    }
  });
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  // facing: the head's forward axis. Eyes sit in front of the Head bone.
  const head = root.getObjectByName("Head");
  const hp = head.getWorldPosition(new THREE.Vector3());
  let face = null;
  root.traverse((o) => {
    if (!o.isSkinnedMesh || !["M_Skin", "M_Visor"].includes(o.material.name)) return;
    const p = o.geometry.attributes.position;
    let sz = 0;
    let n = 0;
    for (let i = 0; i < p.count; i += 1) {
      if (p.getY(i) > hp.y - 0.02 && p.getY(i) < hp.y + 0.12) {
        sz += p.getZ(i);
        n += 1;
      }
    }
    if (n) face = (face ?? 0) + sz / n - hp.z;
  });
  console.log(
    `${m.id}: ${skinned} skinned meshes, ${tris} tris, ${bones.size} bones, size ` +
      `${size.x.toFixed(2)} x ${size.y.toFixed(2)} x ${size.z.toFixed(2)} m, ` +
      `min y ${box.min.y.toFixed(3)}, face dz ${face?.toFixed(3)}`,
  );
  console.log(`  materials: ${[...mats].join(", ")}`);
  if (tris > 15000) fail(`${m.id} has ${tris} triangles (> 15000)`);
  if (!(face > 0)) fail(`${m.id} does not face +Z`);
  if (Math.abs(box.min.y) > 0.03) fail(`${m.id} feet not on the floor (min y ${box.min.y})`);
  for (const b of manifest.skeletons[m.skeleton].bones) {
    if (!bones.has(b)) fail(`${m.id} misses bone ${b}`);
  }
  const clips = clipSets[m.skeleton];
  for (const clip of clips) {
    for (const t of clip.tracks) {
      const node = t.name.split(".")[0];
      if (!root.getObjectByName(node)) fail(`${m.id}: track ${t.name} of ${clip.name} unbound`);
    }
  }
  // foot slide in A_Walk: planted foot world z with the root moving at walkSpeed
  const walk = clips.find((c) => c.name === "A_Walk");
  if (walk) {
    const speed = manifest.skeletons[m.skeleton].walkSpeed;
    const mixer = new THREE.AnimationMixer(root);
    mixer.clipAction(walk).play();
    const foot = root.getObjectByName("Foot_L");
    const toe = root.getObjectByName("Toe_L");
    const samples = [];
    const steps = 60;
    for (let i = 0; i <= steps; i += 1) {
      const t = (walk.duration * i) / steps;
      mixer.setTime(t);
      root.position.set(0, 0, speed * t);
      root.updateMatrixWorld(true);
      const p = foot.getWorldPosition(new THREE.Vector3());
      const q = toe.getWorldPosition(new THREE.Vector3());
      samples.push({ t, y: p.y, z: p.z, ty: q.y, tz: q.z });
    }
    const planted = samples.filter((s) => s.y < 0.09 && s.ty < 0.04);
    const zs = planted.map((s) => s.z);
    const slide = zs.length ? Math.max(...zs) - Math.min(...zs) : NaN;
    console.log(`  A_Walk @ ${speed} m/s: flat-foot frames ${planted.length}, slide ${(slide * 100).toFixed(1)} cm`);
    if (!(slide < 0.05)) fail(`${m.id} foot slides ${slide} m in A_Walk`);
    root.position.set(0, 0, 0);
    // sitting height
    const sit = clips.find((c) => c.name === "A_Sit_Type");
    mixer.stopAllAction();
    mixer.clipAction(sit).play();
    mixer.setTime(0.5);
    root.updateMatrixWorld(true);
    const hips = root.getObjectByName("Hips").getWorldPosition(new THREE.Vector3());
    console.log(`  A_Sit_Type: hips at y ${hips.y.toFixed(3)} (seat ${manifest.seatHeight})`);
  }
}
console.log(failures ? `${failures} failure(s)` : "all checks passed");
process.exit(failures ? 1 : 0);
