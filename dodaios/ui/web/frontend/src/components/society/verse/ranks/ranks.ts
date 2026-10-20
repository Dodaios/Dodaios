/**
 * The fleet's rank ladder, mirrored from the rulebook
 * (dodaios/progression/rules.py `RANKS`; tests/unit/progression/test_frontend_parity.py
 * pins the two together), with what the Verse draws for each rank.
 *
 * Ranks are derived from the level here, never taken from the server's rank
 * id: a backend older than this build names other ranks, the level means the
 * same on both.
 *
 * The rank plate (art/verse/style-bible.md §7.2): a brushed-steel plate with
 * chamfered ends and six elongated-hexagon sockets in two rows of three. Slot
 * index, seen facing the wearer: top row 0 1 2, bottom row 3 4 5 (the
 * character's material slots `M_RankTile_1..6`).
 * Every rank lights its own left-right-symmetric pattern (written `top|bottom`,
 * 1 = tile), so no two ranks share a plate even without the tier's colour:
 * the deck ratings build from the bottom row, line officers from the top, the
 * command ranks and the flag officers take the shapes that are left, and the
 * fleet admiral wears the full plate.
 */

export const RANK_TIERS = ["deck", "line", "command", "flag"] as const;
export type RankTier = (typeof RANK_TIERS)[number];

export const RANK_IDS = [
  "recruit", "deckhand", "technician", "senior_technician",
  "ensign", "lieutenant", "senior_lieutenant", "commander", "captain",
  "line_captain", "commodore",
  "rear_admiral", "vice_admiral", "admiral", "fleet_admiral",
] as const;
export type RankId = (typeof RANK_IDS)[number];

export interface RankDef {
  id: RankId;
  /** The first level of the rank. */
  level: number;
  tier: RankTier;
  /** The plate's lit slots, `top|bottom`, three digits each. */
  plate: string;
}

export const RANKS: readonly RankDef[] = [
  { id: "recruit", level: 1, tier: "deck", plate: "000|010" },
  { id: "deckhand", level: 3, tier: "deck", plate: "000|101" },
  { id: "technician", level: 5, tier: "deck", plate: "000|111" },
  { id: "senior_technician", level: 8, tier: "deck", plate: "010|111" },
  { id: "ensign", level: 11, tier: "line", plate: "010|000" },
  { id: "lieutenant", level: 14, tier: "line", plate: "101|000" },
  { id: "senior_lieutenant", level: 17, tier: "line", plate: "111|000" },
  { id: "commander", level: 21, tier: "line", plate: "111|010" },
  { id: "captain", level: 25, tier: "line", plate: "111|101" },
  { id: "line_captain", level: 29, tier: "command", plate: "010|010" },
  { id: "commodore", level: 33, tier: "command", plate: "101|010" },
  { id: "rear_admiral", level: 37, tier: "flag", plate: "010|101" },
  { id: "vice_admiral", level: 41, tier: "flag", plate: "101|101" },
  { id: "admiral", level: 45, tier: "flag", plate: "101|111" },
  { id: "fleet_admiral", level: 50, tier: "flag", plate: "111|111" },
];

const BY_ID = new Map<string, RankDef>(RANKS.map((rank) => [rank.id, rank]));

/** The uniform each tier wears (the commander's quartermaster issues them as rewards). */
export type UniformId = RankTier;

export interface TierStyle {
  /** Tile colour on the rank plate. */
  tile: string;
  /** The uniform a figure of this tier wears. */
  uniform: UniformId;
}

/**
 * Pip colours are the style bible's (§7.2): satin enamel, never emissive, one
 * colour per plate. Deck ratings wear steel pips, line officers blue, command
 * red, flag officers gold (the only gold on any figure). Uniforms: deck =
 * charcoal work uniform, line = olive-grey tunic with cap, command = black
 * tunic with cap, flag = off-white tunic with cap.
 */
export const TIER_STYLE: Readonly<Record<RankTier, TierStyle>> = {
  deck: { tile: "#a9adb2", uniform: "deck" },
  line: { tile: "#4d86d9", uniform: "line" },
  command: { tile: "#e3242b", uniform: "command" },
  flag: { tile: "#c8a24a", uniform: "flag" },
};

/** Uniform cloth colours (style bible §7.1), for swatches and the figures. */
export const UNIFORM_CLOTH: Readonly<Record<UniformId, string>> = {
  deck: "#3b3f47",
  line: "#5e6253",
  command: "#17181a",
  flag: "#e4e1d8",
};

/** The brushed-steel plate, its edge and pin heads, and an empty socket. */
export const PLATE_STEEL = "#a9adb2";
export const PLATE_EDGE = "#5e6368";
export const PLATE_RECESS = "#2a2d31";

export function isRankId(value: unknown): value is RankId {
  return typeof value === "string" && BY_ID.has(value);
}

export function rankById(id: RankId): RankDef {
  return BY_ID.get(id) ?? RANKS[0];
}

/** The rank a subject at `level` holds. */
export function rankForLevel(level: number): RankDef {
  let held = RANKS[0];
  for (const rank of RANKS) if (level >= rank.level) held = rank;
  return held;
}

/** The rank above the one `level` holds; undefined at the top of the ladder. */
export function nextRank(level: number): RankDef | undefined {
  return RANKS.find((rank) => rank.level > level);
}

export function tierOf(id: RankId): RankTier {
  return rankById(id).tier;
}

export function ranksOfTier(tier: RankTier): RankDef[] {
  return RANKS.filter((rank) => rank.tier === tier);
}

/** The first level of a tier. */
export function tierStart(tier: RankTier): number {
  return ranksOfTier(tier)[0]?.level ?? 1;
}

export function uniformForTier(tier: RankTier): UniformId {
  return TIER_STYLE[tier].uniform;
}

export function uniformForLevel(level: number): UniformId {
  return uniformForTier(rankForLevel(level).tier);
}

/** True when a climb from `before` to `after` crossed into a new rank. */
export function isPromotion(before: number, after: number): boolean {
  return rankForLevel(after).id !== rankForLevel(before).id && after > before;
}

export interface PlateTiles {
  /** Six slots, top row 0..2 then bottom row 3..5, as seen facing the wearer. */
  lit: readonly boolean[];
  /** The tier's tile colour. */
  colour: string;
  tier: RankTier;
}

/** What the plate of `id` shows: which slots carry a tile and in what colour. */
export function plateTiles(id: RankId): PlateTiles {
  const rank = rankById(id);
  const lit = rank.plate.split("|").join("").split("").map((bit) => bit === "1");
  return { lit, colour: TIER_STYLE[rank.tier].tile, tier: rank.tier };
}

export interface RankBadge extends PlateTiles {
  id: RankId;
  level: number;
}

/** Everything a figure at `level` wears on its chest: the rank, its tier, the lit slots and their colour. */
export function rankBadge(level: number): RankBadge {
  const rank = rankForLevel(level);
  return { id: rank.id, level: rank.level, ...plateTiles(rank.id) };
}
