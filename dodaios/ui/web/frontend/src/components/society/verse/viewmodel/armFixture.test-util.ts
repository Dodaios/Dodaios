/**
 * Test-only: the commander's body (SK_Officer_M.glb) parsed from disk with its
 * atlas images stripped (jsdom cannot decode them), as the skinned meshes the
 * arm cut reads.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { SkinnedMesh } from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const CHARACTERS = join(__dirname, "../../../../../public/verse/characters");

function stripImages(buf: Buffer): ArrayBuffer {
  const len = buf.readUInt32LE(12);
  const json = JSON.parse(buf.subarray(20, 20 + len).toString("utf8"));
  for (const m of json.materials ?? []) {
    if (m.pbrMetallicRoughness) {
      delete m.pbrMetallicRoughness.baseColorTexture;
      delete m.pbrMetallicRoughness.metallicRoughnessTexture;
    }
    delete m.normalTexture;
    delete m.occlusionTexture;
    delete m.emissiveTexture;
  }
  delete json.textures;
  delete json.images;
  delete json.samplers;
  json.extensionsRequired = (json.extensionsRequired ?? []).filter((e: string) => e !== "EXT_texture_webp");
  let text = Buffer.from(JSON.stringify(json), "utf8");
  text = Buffer.concat([text, Buffer.alloc((4 - (text.length % 4)) % 4, 0x20)]);
  const rest = buf.subarray(20 + len);
  const head = Buffer.alloc(20);
  head.writeUInt32LE(0x46546c67, 0);
  head.writeUInt32LE(2, 4);
  head.writeUInt32LE(20 + text.length + rest.length, 8);
  head.writeUInt32LE(text.length, 12);
  head.writeUInt32LE(0x4e4f534a, 16);
  const out = Buffer.concat([head, text, rest]);
  // A buffer of the test's own realm (jsdom's ArrayBuffer is not Node's).
  const ab = new ArrayBuffer(out.byteLength);
  new Uint8Array(ab).set(out);
  return ab;
}

export async function loadBody(file = "SK_Officer_M.glb"): Promise<SkinnedMesh[]> {
  const data = stripImages(readFileSync(join(CHARACTERS, file)));
  const gltf = await new GLTFLoader().parseAsync(data, "");
  gltf.scene.updateMatrixWorld(true);
  const meshes: SkinnedMesh[] = [];
  gltf.scene.traverse((o) => { if ((o as SkinnedMesh).isSkinnedMesh) meshes.push(o as SkinnedMesh); });
  return meshes;
}
