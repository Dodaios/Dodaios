import { describe, expect, it } from "vitest";
import { Group, MeshStandardMaterial } from "three";
import { applyLook } from "./look";
import type { CharacterContract, CharacterInstance, TierColours } from "./characters";

function tier(uniform: string, trousers?: string): TierColours {
  return { M_Uniform: uniform, M_Trousers: trousers, M_Trim: "#101010", M_Cap: uniform, tile: "#c8a24a", cap: true };
}

function body(): { instance: CharacterInstance; tunic: MeshStandardMaterial; breeches: MeshStandardMaterial } {
  const tunic = new MeshStandardMaterial();
  const breeches = new MeshStandardMaterial();
  const instance = {
    root: new Group(),
    clips: new Map(),
    materials: new Map([["M_Uniform", [tunic]], ["M_Trousers", [breeches]]]),
    meshes: [],
  } as unknown as CharacterInstance;
  return { instance, tunic, breeches };
}

const contract = {
  tiers: { deck: tier("#3b3f47"), line: tier("#5e6253", "#5e6253"), command: tier("#17181a", "#17181a"), flag: tier("#e4e1d8", "#17181a") },
} as unknown as CharacterContract;

describe("uniform tint", () => {
  it("dresses the breeches in the tier's own colour", () => {
    const { instance, tunic, breeches } = body();
    applyLook(instance, contract, { tier: "flag", accent: null, plate: "111|111" });
    expect(tunic.color.getHexString()).toBe("e4e1d8");
    expect(breeches.color.getHexString()).toBe("17181a");
  });

  it("falls back to the tunic colour when a manifest has no breeches colour", () => {
    const { instance, breeches } = body();
    applyLook(instance, contract, { tier: "deck", accent: null, plate: "100|000" });
    expect(breeches.color.getHexString()).toBe("3b3f47");
  });
});
