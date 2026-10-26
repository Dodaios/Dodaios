// Meshopt encoding for the Verse realtime export (run by scripts/verse/package_realtime.py).
//
//   node scripts/verse/meshopt_pack.mjs <in.json> <in.bin> <out.json> <out.bin>
//
// in.json: { primitives: [{ vertexCount, indexOffset, indexCount, streams: [{ offset, stride }] }] }
// in.bin:  the raw (already quantised) vertex streams and uint32 indices the offsets point at.
//
// For every primitive the vertices are reordered for the GPU vertex cache and
// vertex fetch (meshopt_optimizeVertexCache + optimizeVertexFetchRemap), the
// indices narrowed to 16 bit when they fit, and every stream encoded with the
// EXT_meshopt_compression codecs (vertex codec version 0, which every
// decoder reads). out.json lists the encoded byte ranges in out.bin.
//
// The encoder is the meshoptimizer npm package the frontend already ships
// (dodaios/ui/web/frontend/node_modules/meshoptimizer), so cooks need no
// extra install.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const encoderPath = join(here, "..", "..", "dodaios", "ui", "web", "frontend", "node_modules", "meshoptimizer", "meshopt_encoder.js");
const { MeshoptEncoder } = await import(pathToFileURL(encoderPath).href);
await MeshoptEncoder.ready;

const [inJson, inBin, outJson, outBin] = process.argv.slice(2);
if (!outBin) {
  console.error("usage: meshopt_pack.mjs <in.json> <in.bin> <out.json> <out.bin>");
  process.exit(2);
}
const spec = JSON.parse(readFileSync(inJson, "utf8"));
const raw = readFileSync(inBin);
const source = new Uint8Array(raw.buffer, raw.byteOffset, raw.byteLength);

const parts = [];
let offset = 0;
const push = (bytes) => {
  const at = offset;
  parts.push(bytes);
  offset += bytes.byteLength;
  const pad = (4 - (offset % 4)) % 4;
  if (pad) {
    parts.push(new Uint8Array(pad));
    offset += pad;
  }
  return { offset: at, length: bytes.byteLength };
};

const out = [];
for (const prim of spec.primitives) {
  const indices = new Uint32Array(prim.indexCount);
  new Uint8Array(indices.buffer).set(source.subarray(prim.indexOffset, prim.indexOffset + prim.indexCount * 4));
  const [remap, unique] = MeshoptEncoder.reorderMesh(indices, true, false);
  const streams = prim.streams.map((s) => {
    const reordered = new Uint8Array(unique * s.stride);
    for (let v = 0; v < prim.vertexCount; v++) {
      const to = remap[v];
      if (to === 0xffffffff) continue;
      reordered.set(source.subarray(s.offset + v * s.stride, s.offset + (v + 1) * s.stride), to * s.stride);
    }
    const encoded = MeshoptEncoder.encodeGltfBuffer(reordered, unique, s.stride, "ATTRIBUTES");
    return { stride: s.stride, ...push(encoded) };
  });
  const indexSize = unique <= 65536 ? 2 : 4;
  const indexBytes = indexSize === 2 ? new Uint8Array(Uint16Array.from(indices).buffer) : new Uint8Array(indices.buffer);
  const index = push(MeshoptEncoder.encodeGltfBuffer(indexBytes, indices.length, indexSize, "TRIANGLES"));
  out.push({
    vertexCount: unique,
    indexCount: indices.length,
    indexSize,
    streams,
    index,
  });
}

const total = new Uint8Array(offset);
let at = 0;
for (const part of parts) {
  total.set(part, at);
  at += part.byteLength;
}
writeFileSync(outBin, total);
writeFileSync(outJson, JSON.stringify({ primitives: out }));
