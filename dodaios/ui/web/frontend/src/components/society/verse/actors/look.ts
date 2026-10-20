/**
 * Dressing a body: uniform by rank tier, the agent's own accent colour, the
 * lit tiles of the chest rank plate, the cap for the tiers that wear one
 * (BRIEF §8). Material names are the character contract's.
 */
import { Color, type Material, type MeshStandardMaterial } from "three";
import { TIER_STYLE, rankForLevel, type RankTier } from "../ranks";
import type { CharacterContract, CharacterInstance } from "./characters";

export interface Look {
  tier: RankTier;
  /** The agent's personal colour (CSS colour); null leaves the authored accent. */
  accent: string | null;
  /** Lit plate slots, `top|bottom` as the rank ladder writes them. */
  plate: string;
}

export function lookForLevel(level: number, accent: string | null): Look {
  const rank = rankForLevel(level);
  return { tier: rank.tier, accent, plate: rank.plate };
}

/** Plate slots 0–5 (top row left to right, then the bottom row) that are lit. Pure. */
export function litSlots(plate: string): number[] {
  const bits = plate.split("|").join("");
  const out: number[] = [];
  for (let i = 0; i < bits.length && i < 6; i++) if (bits[i] === "1") out.push(i);
  return out;
}

function standard(materials: readonly Material[] | undefined): MeshStandardMaterial[] {
  return (materials ?? []).filter((m): m is MeshStandardMaterial => (m as MeshStandardMaterial).isMeshStandardMaterial === true);
}

const UNLIT = new Color(0, 0, 0);

export function applyLook(instance: CharacterInstance, contract: CharacterContract, look: Look): void {
  const tier = contract.tiers[look.tier];
  const paint = (name: string, colour: string) => {
    for (const m of standard(instance.materials.get(name))) m.color.set(colour);
  };
  paint("M_Uniform", tier.M_Uniform);
  paint("M_Trousers", tier.M_Trousers ?? tier.M_Uniform);
  paint("M_Trim", tier.M_Trim);
  paint("M_Cap", tier.M_Cap);
  if (look.accent) paint("M_Accent", look.accent);
  const lit = new Set(litSlots(look.plate));
  const tile = new Color(TIER_STYLE[look.tier].tile);
  for (let slot = 0; slot < 6; slot++) {
    for (const m of standard(instance.materials.get(`M_RankTile_${slot + 1}`))) {
      // Enamel on steel: lit tiles carry the tier colour, a hint of emission keeps them legible at deck scale.
      if (lit.has(slot)) { m.color.copy(tile); m.emissive.copy(tile); m.emissiveIntensity = 0.35; }
      else { m.color.set(contract.tileUnlit ?? "#2a2d31"); m.emissive.copy(UNLIT); m.emissiveIntensity = 0; }
    }
  }
  const cap = instance.root.getObjectByName("Cap");
  if (cap) cap.visible = tier.cap;
}
