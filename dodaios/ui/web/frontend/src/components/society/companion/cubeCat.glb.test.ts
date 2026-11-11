// @vitest-environment node
/**
 * The cube cat's run clip has to turn a front leg. The file carries a
 * texture, so this reads the clip directly instead of asking the glTF
 * loader to decode an image in Node.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { CUBE_CLIPS } from "./cubeCat";

const FILE = resolve(__dirname, "../../../assets/pets/cube-cat.glb");

interface Gltf {
  nodes: { name?: string }[];
  animations: {
    name: string;
    channels: { sampler: number; target: { node: number; path: string } }[];
    samplers: { output: number }[];
  }[];
  accessors: { bufferView?: number; byteOffset?: number; count: number; type: string }[];
  bufferViews: { byteOffset?: number; byteLength: number }[];
}

function document(): { doc: Gltf; bin: Buffer } {
  const data = readFileSync(FILE);
  const jsonLength = data.readUInt32LE(12);
  const doc = JSON.parse(data.subarray(20, 20 + jsonLength).toString("utf8")) as Gltf;
  const binHeader = 20 + jsonLength;
  const binLength = data.readUInt32LE(binHeader);
  return { doc, bin: data.subarray(binHeader + 8, binHeader + 8 + binLength) };
}

function quaternions(doc: Gltf, bin: Buffer, accessorIndex: number): number[][] {
  const accessor = doc.accessors[accessorIndex];
  const view = doc.bufferViews[accessor.bufferView ?? 0];
  const start = (view.byteOffset ?? 0) + (accessor.byteOffset ?? 0);
  const out: number[][] = [];
  for (let i = 0; i < accessor.count; i++) {
    const at = start + i * 16;
    out.push([bin.readFloatLE(at), bin.readFloatLE(at + 4), bin.readFloatLE(at + 8), bin.readFloatLE(at + 12)]);
  }
  return out;
}

describe("cube cat glb", () => {
  it("ships the eight clips and the run turns a front leg", () => {
    const { doc, bin } = document();
    expect(doc.animations.map((clip) => clip.name).sort()).toEqual([...CUBE_CLIPS].sort());
    const run = doc.animations.find((clip) => clip.name === "run");
    const leg = doc.nodes.findIndex((node) => node.name === "leg-front-left");
    expect(run).toBeTruthy();
    expect(leg).toBeGreaterThanOrEqual(0);
    const channel = run!.channels.find((item) => item.target.node === leg && item.target.path === "rotation");
    expect(channel).toBeTruthy();
    const keys = quaternions(doc, bin, run!.samplers[channel!.sampler].output);
    expect(keys.length).toBeGreaterThan(2);
    const first = keys[0];
    const moved = keys.some((key) => key.some((value, index) => Math.abs(value - first[index]) > 0.05));
    expect(moved).toBe(true);
  });
});
