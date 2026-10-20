/**
 * Name plates in a crowd. A plate is a good deal wider than the figure under
 * it, so a team huddled at its board would stack five plates into one
 * unreadable pile. Each frame every plate that wants to open reports where it
 * would sit on screen; the plates are then seated in order of importance, and
 * one that would cover a plate already seated stays a dot.
 *
 * Order: the agent the person selected or points at (always open), whoever is
 * speaking in a team round (its speech bubble gets room above the plate), a
 * plate that is already open (so the picture does not reshuffle while people
 * shift about), then whoever stands closest to the person. Pure and tested;
 * the small registry below only carries the reports from one frame to the
 * next.
 */

/** A plate's place on screen, in CSS pixels: centre and size. */
export interface PlateBox {
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Selected or pointed at: opens whatever it covers. */
  pinned: boolean;
  /** Speaking in a team round right now: ahead of the bystanders, with room for its bubble. */
  speaker: boolean;
  /** Open in the last frame. */
  shown: boolean;
  /** Metres to the person's character; the nearer one wins among equals. */
  distance: number;
}

export interface ScreenRect { x: number; y: number; w: number; h: number }

/** An open plate keeps its seat until something comes this close (px); a closed one needs this much clear space to open. */
export const PLATE_GAP = { keep: 2, open: 12 } as const;
/** A speaker's bubble sits above its plate: this much room (px) is kept free there. */
export const BUBBLE_ROOM = { w: 220, h: 84 } as const;

function overlaps(a: ScreenRect, b: ScreenRect, gap: number): boolean {
  return Math.abs(a.x - b.x) * 2 < a.w + b.w + gap * 2 && Math.abs(a.y - b.y) * 2 < a.h + b.h + gap * 2;
}

/** The space a plate claims: itself, plus the bubble above it while its agent speaks. */
function claim(box: PlateBox): ScreenRect {
  if (!box.speaker) return box;
  const h = box.h + BUBBLE_ROOM.h;
  return { x: box.x, y: box.y - BUBBLE_ROOM.h / 2, w: Math.max(box.w, BUBBLE_ROOM.w), h };
}

function rank(box: PlateBox): number {
  return box.pinned ? 0 : box.speaker ? 1 : box.shown ? 2 : 3;
}

/**
 * The plates that may open, given everyone who wants to. `taken` are places
 * that are occupied whatever happens (the person's own plate).
 */
export function arrangePlates(boxes: readonly PlateBox[], taken: readonly ScreenRect[] = []): Set<string> {
  const seated: ScreenRect[] = [...taken];
  const open = new Set<string>();
  const order = [...boxes].sort((a, b) => rank(a) - rank(b) || a.distance - b.distance || a.id.localeCompare(b.id));
  for (const box of order) {
    const space = claim(box);
    if (!box.pinned) {
      const gap = box.shown ? PLATE_GAP.keep : PLATE_GAP.open;
      // A bystander only has to keep its own plate clear of what is seated; a speaker also needs its bubble's room.
      if (seated.some((other) => overlaps(space, other, gap))) continue;
    }
    seated.push(space);
    open.add(box.id);
  }
  return open;
}

/**
 * One stage's seating: the reports of its running frame, and who was seated from the frame before. Every office
 * stage has its own (two can be awake at once: the Agents view and the IDE side panel's tab show the same agent
 * ids on different screens and clocks), keyed by the stage's scene.
 */
interface StageSeating { reports: Map<string, PlateBox>; seatedAt: number; open: Set<string>; plates: number }

const stages = new Map<object, StageSeating>();

function seatingOf(stage: object): StageSeating {
  let seating = stages.get(stage);
  if (!seating) {
    seating = { reports: new Map(), seatedAt: Number.NaN, open: new Set(), plates: 0 };
    stages.set(stage, seating);
  }
  return seating;
}

/**
 * A plate joins its stage's seating for as long as it is mounted. Returns the
 * leave function; when the stage's last plate has left, its seating is
 * released, so nothing of an unmounted stage is kept.
 */
export function joinPlates(stage: object): () => void {
  seatingOf(stage).plates += 1;
  let left = false;
  return () => {
    if (left) return;
    left = true;
    const seating = stages.get(stage);
    if (!seating) return;
    seating.plates -= 1;
    if (seating.plates <= 0) stages.delete(stage);
  };
}

/**
 * Who may be open on this stage this frame. The first plate that asks in a
 * frame seats everyone from the reports of the frame before; a plate that
 * stopped reporting (walked off, unmounted) drops out by itself.
 */
export function plateSeating(stage: object, frame: number, taken: () => readonly ScreenRect[]): ReadonlySet<string> {
  const seating = seatingOf(stage);
  if (frame !== seating.seatedAt) {
    seating.seatedAt = frame;
    seating.open = arrangePlates([...seating.reports.values()], taken());
    seating.reports.clear();
  }
  return seating.open;
}

/** A plate that wants to be open says where it would sit on its stage. */
export function reportPlate(stage: object, box: PlateBox): void {
  seatingOf(stage).reports.set(box.id, box);
}

/** How many stages hold a seating right now (for tests: an unmounted stage must leave none behind). */
export function plateStages(): number {
  return stages.size;
}

/** Forget everything (tests). */
export function resetPlateSeating(): void {
  stages.clear();
}
