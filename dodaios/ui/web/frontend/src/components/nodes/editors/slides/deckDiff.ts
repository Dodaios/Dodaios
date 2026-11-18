/**
 * What an agent's revision changed in a deck, slide by slide.
 *
 * Slides carry no ids, so the old and the new deck are matched by content: a
 * slide that reads the same is the same slide (it may have moved), and a slide
 * that changed in place is the unmatched old slide at the same index. The live
 * build uses this to decide which slide the stage follows and what plays; the
 * editor uses it to keep the person's own slide under them.
 */
import type { Deck, Slide } from "./deckModel";
import type { SlideElement } from "./elementModel";

export type SlideChangeKind = "added" | "edited" | "moved";

export interface SlideChange {
  kind: SlideChangeKind;
  /** The slide's index in the new deck. */
  index: number;
  /** Its index in the old deck; null for an added slide. */
  from: number | null;
  slide: Slide;
  /** The slide before (edited), else null. */
  before: Slide | null;
}

export interface DeckDiff {
  changes: SlideChange[];
  /** For each old slide, its index in the new deck, or -1 when it is gone. */
  newIndexOf: number[];
  /** Slides were only put in another order. */
  reordered: boolean;
}

const same = (a: unknown, b: unknown): boolean => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

export function diffDecks(previous: Deck | null, next: Deck, ops: readonly { op?: string }[] | null = null): DeckDiff {
  const after = next.slides ?? [];
  if (!previous) {
    return {
      changes: after.map((slide, index) => ({ kind: "added" as const, index, from: null, slide, before: null })),
      newIndexOf: [],
      reordered: false,
    };
  }
  const before = previous.slides ?? [];
  const keyBefore = before.map((s) => JSON.stringify(s));
  const keyAfter = after.map((s) => JSON.stringify(s));
  const usedBefore = new Set<number>();
  const matched: (number | null)[] = after.map(() => null);
  // Same index first, so duplicated slides stay where they are.
  after.forEach((_, j) => {
    if (keyBefore[j] === keyAfter[j]) {
      matched[j] = j;
      usedBefore.add(j);
    }
  });
  after.forEach((_, j) => {
    if (matched[j] !== null) return;
    const i = keyBefore.findIndex((k, at) => !usedBefore.has(at) && k === keyAfter[j]);
    if (i >= 0) {
      matched[j] = i;
      usedBefore.add(i);
    }
  });
  const changes: SlideChange[] = [];
  const newIndexOf = before.map(() => -1);
  matched.forEach((i, j) => {
    if (i !== null) newIndexOf[i] = j;
  });
  after.forEach((slide, j) => {
    if (matched[j] !== null) return;
    if (j < before.length && !usedBefore.has(j)) {
      usedBefore.add(j);
      newIndexOf[j] = j;
      changes.push({ kind: "edited", index: j, from: j, slide, before: before[j] });
    } else {
      changes.push({ kind: "added", index: j, from: null, slide, before: null });
    }
  });
  const reordered =
    changes.length === 0 &&
    before.length === after.length &&
    (ops === null || ops.some((o) => o.op === "move")) &&
    matched.some((i, j) => i !== j);
  if (reordered) {
    matched.forEach((i, j) => {
      if (i !== null && i !== j) changes.push({ kind: "moved", index: j, from: i, slide: after[j], before: null });
    });
  }
  return { changes, newIndexOf, reordered };
}

/** Where the slide the person is on ends up after the revision. */
export function indexAfterRevision(diff: DeckDiff, current: number, count: number): number {
  const mapped = diff.newIndexOf[current];
  const at = mapped !== undefined && mapped >= 0 ? mapped : current;
  return Math.max(0, Math.min(at, count - 1));
}

/** The first slide an agent wrote to (added or edited), or null when it only moved slides. */
export function firstWritten(diff: DeckDiff): number | null {
  const written = diff.changes.filter((c) => c.kind !== "moved").map((c) => c.index);
  return written.length > 0 ? Math.min(...written) : null;
}

/** The keys that only place an element. */
const PLACE = ["x", "y", "w", "h", "rotate"] as const;

export type ElementChange = "added" | "moved" | "styled";

const bare = (e: SlideElement): Record<string, unknown> => {
  const copy: Record<string, unknown> = { ...e };
  delete copy.id;
  return copy;
};

/**
 * How the element at `index` of the new slide differs from the slide before, or null when it does not.
 * Elements are matched by id; without one (the editor invents ids on every load) by content, then by place.
 */
export function elementChange(before: readonly SlideElement[] | undefined, element: SlideElement, index: number): ElementChange | null {
  const list = before ?? [];
  const byId = element.id ? list.find((e) => e.id === element.id) : undefined;
  const old =
    byId ??
    list.find((e) => same(bare(e), bare(element))) ??
    (list[index] && list[index].type === element.type ? list[index] : undefined);
  if (!old) return "added";
  if (same(bare(old), bare(element))) return null;
  const strip = (e: SlideElement) => {
    const copy = bare(e);
    for (const key of PLACE) delete copy[key];
    return copy;
  };
  return same(strip(old), strip(element)) ? "moved" : "styled";
}

/** The element's geometry before, for the glide. */
export function elementBefore(before: readonly SlideElement[] | undefined, element: SlideElement, index: number): SlideElement | null {
  const list = before ?? [];
  return (
    (element.id ? list.find((e) => e.id === element.id) : undefined) ??
    (list[index] && list[index].type === element.type ? list[index] : null)
  );
}
