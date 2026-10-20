/**
 * Keeps the Verse's level state in step with the server while the Verse is
 * open, and reports the world actions only the visit itself knows about.
 *
 * - First read on mount (with the level-ups missed while the Verse was
 *   closed), then a slow jittered re-read as a safety net (AP-33); live awards
 *   arrive as `ProgressionAwarded` pushes over the existing WebSocket.
 * - The day's first visit and each deck discovered are reported once each;
 *   the server decides whether they pay. Simulator rounds, team briefings,
 *   inspections and walks with the companion drone are reported by whatever
 *   sees them, through `reportWorldAction`.
 */
import { useEffect, useRef } from "react";
import { useEventStore } from "@/store/events";
import { useCompanionPet } from "../companion/companionPetStore";
import { DECK_IDS } from "../verse/decks";
import { isPromotion } from "../verse/ranks/ranks";
import { fetchProgression, parseAwardEvent, reportWorldAction } from "./progressionApi";
import { awayCelebrations, readSeenSeq, useProgression, writeSeenSeq } from "./progressionStore";
import { playLevelUp, playXpTick } from "./levelSounds";

const RESYNC_MS = 60_000;
const RESYNC_JITTER_MS = 15_000;
/** Ticks for "+XP" closer together than this are one sound. */
const TICK_GAP_MS = 400;
/**
 * The decks the server pays a first visit for (`VERSE_DECKS` in dodaios/progression/rules.py).
 * `verseDecks.test.ts` holds this list and the server's together.
 */
export const METERED_DECKS: ReadonlySet<string> = new Set<string>(DECK_IDS);

/** `deck`: the deck the commander is on; a value that is not a deck id is simply not reported. */
export function useProgressionSync(awake: boolean, deck: string): void {
  const seen = useRef<number>(0);

  // First read, then the slow safety net while the ship is on screen.
  useEffect(() => {
    if (!awake) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async (first: boolean) => {
      let next = false;
      try {
        const snapshot = await fetchProgression();
        if (cancelled) return;
        const marker = readSeenSeq();
        useProgression.getState().hydrate(snapshot, first ? awayCelebrations(snapshot, marker) : []);
        seen.current = Math.max(seen.current, snapshot.latestSeq);
        writeSeenSeq(seen.current);
      } catch (error) {
        // The Verse runs on without levels; the next read tries again (and is still the first that tells what happened away).
        console.debug("Verse levels unavailable", error);
        next = first;
      }
      if (!cancelled) timer = setTimeout(() => void load(next), RESYNC_MS + Math.random() * RESYNC_JITTER_MS);
    };
    void load(true);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [awake]);

  // Live awards from the bus.
  useEffect(() => {
    let lastId: string | null = useEventStore.getState().events[0]?.id ?? null;
    let lastTick = 0;
    return useEventStore.subscribe((state) => {
      const fresh = [];
      for (const event of state.events) {
        if (event.id === lastId) break;
        fresh.push(event);
      }
      lastId = state.events[0]?.id ?? lastId;
      for (const event of fresh.reverse()) {
        if (event.name !== "ProgressionAwarded") continue;
        const award = parseAwardEvent(event.payload);
        if (!award) continue;
        useProgression.getState().apply(award);
        if (award.seq > seen.current) { seen.current = award.seq; writeSeenSeq(award.seq); }
        // The full bell for the commander's and the drone's new rank; a quiet pair for any other level-up.
        if (award.level > award.previousLevel) playLevelUp(award.kind !== "agent" && isPromotion(award.previousLevel, award.level));
        else if (award.kind !== "agent" && performance.now() - lastTick > TICK_GAP_MS) { lastTick = performance.now(); playXpTick(); }
      }
    });
  }, []);

  // The pet that earns is the one in My Pets right now.
  const petId = useCompanionPet((s) => s.pet.id);
  useEffect(() => { useProgression.getState().setPetId(petId); }, [petId]);

  // The day's first visit and every deck discovered.
  useEffect(() => { if (awake) void reportWorldAction("daily_visit"); }, [awake]);
  useEffect(() => { if (awake && METERED_DECKS.has(deck)) void reportWorldAction("deck_discovered", deck); }, [awake, deck]);
}
