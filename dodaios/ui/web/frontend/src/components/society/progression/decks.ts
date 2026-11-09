/**
 * The capital ship's decks, top to bottom. The ids are a contract with the
 * cook (`art/verse/decks/<id>/`), the cooked content
 * (`public/verse/decks/<id>/manifest.json`) and the progression backend
 * (`deck_discovered` refs).
 */
export const DECK_IDS = ["bridge", "ops", "engineering", "hangar"] as const;

export type DeckId = (typeof DECK_IDS)[number];

export function isDeckId(value: unknown): value is DeckId {
  return typeof value === "string" && (DECK_IDS as readonly string[]).includes(value);
}

/** One-based deck number as shown on the turbolift panel. */
export function deckNumber(id: DeckId): number {
  return DECK_IDS.indexOf(id) + 1;
}
