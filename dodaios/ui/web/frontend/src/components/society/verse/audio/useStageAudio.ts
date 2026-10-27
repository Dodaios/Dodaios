/**
 * The ship around the commander: each deck's air handling and machinery as a
 * quiet loop, the turbolift's doors and ride, and a click when a HUD panel
 * opens or closes. Loaded once the Verse is on screen; the loops stop while
 * it is hidden. The level follows the Verse volume setting.
 */
import { useEffect, useRef, useState } from "react";
import type { DeckId } from "../decks";
import { useViewSettings } from "../engine/realtime/viewSettings";
import { verseAudio, type SoundName, type Voice } from "./verseAudio";

const AMBIENCE: Record<DeckId, SoundName> = {
  bridge: "amb_bridge",
  ops: "amb_ops",
  engineering: "amb_engineering",
  hangar: "amb_hangar",
};

const STAGE_SOUNDS: readonly SoundName[] = ["door_open", "door_close", "lift_ride", "ui_click", "ui_close"];

const AMBIENCE_LEVEL = 0.32;
/** The ambience steps back while a duel is fought. */
const AMBIENCE_DUEL = 0.16;

interface StageAudio {
  /** The Verse is on screen. */
  awake: boolean;
  deckId: DeckId;
  /** The deck the lift rides to while its doors are shut, else null. */
  doors: DeckId | null;
  /** The HUD panel that is open, else null. */
  panel: string | null;
  dueling: boolean;
}

export function useStageAudio({ awake, deckId, doors, panel, dueling }: StageAudio): void {
  const volume = useViewSettings((s) => s.volume);
  useEffect(() => { verseAudio().setVolume(volume); }, [volume]);

  // Load the deck's sounds once the Verse is on screen; browsers start audio only after a gesture, so the first click wakes it.
  /** The deck whose ambience has loaded. */
  const [ambienceReady, setAmbienceReady] = useState<DeckId | null>(null);
  useEffect(() => {
    if (!awake) return;
    const audio = verseAudio();
    let live = true;
    void audio.preload([...STAGE_SOUNDS, AMBIENCE[deckId]]).then(() => { if (live) setAmbienceReady(deckId); });
    const wake = () => audio.resume();
    window.addEventListener("pointerdown", wake, true);
    window.addEventListener("keydown", wake, true);
    return () => {
      live = false;
      window.removeEventListener("pointerdown", wake, true);
      window.removeEventListener("keydown", wake, true);
    };
  }, [awake, deckId, setAmbienceReady]);

  // The deck's ambience: one loop, crossfaded on a deck change, stopped while the Verse is hidden.
  const loop = useRef<{ deck: DeckId; voice: Voice } | null>(null);
  useEffect(() => {
    const current = loop.current;
    if (!awake) {
      current?.voice.stop(0.4);
      loop.current = null;
      return;
    }
    if (current?.deck === deckId) {
      current.voice.setGain(dueling ? AMBIENCE_DUEL : AMBIENCE_LEVEL, 0.6);
      return;
    }
    if (ambienceReady !== deckId) return;
    current?.voice.stop(0.8);
    const voice = verseAudio().play(AMBIENCE[deckId], {
      gain: dueling ? AMBIENCE_DUEL : AMBIENCE_LEVEL, loop: true, fadeIn: 1.2, pitchJitter: 0, gainJitter: 0,
    });
    loop.current = voice ? { deck: deckId, voice } : null;
  }, [awake, deckId, dueling, ambienceReady]);
  useEffect(() => () => { loop.current?.voice.stop(0.2); loop.current = null; }, []);

  // The turbolift: the doors shut, the car rides while they stay shut, the doors open on the new deck.
  const ride = useRef<Voice | null>(null);
  const wasShut = useRef(false);
  useEffect(() => {
    const audio = verseAudio();
    if (doors && !wasShut.current) {
      wasShut.current = true;
      audio.play("door_close", { gain: 0.6 });
      ride.current?.stop(0.1);
      ride.current = audio.play("lift_ride", { gain: 0.5, loop: true, fadeIn: 0.35, delay: 0.25, pitchJitter: 0.02 });
    } else if (!doors && wasShut.current) {
      wasShut.current = false;
      ride.current?.stop(0.3);
      ride.current = null;
      audio.play("door_open", { gain: 0.6 });
    }
  }, [doors]);
  useEffect(() => () => { ride.current?.stop(0.1); ride.current = null; }, []);

  // A HUD panel opening or closing.
  const lastPanel = useRef<string | null>(null);
  useEffect(() => {
    const before = lastPanel.current;
    lastPanel.current = panel;
    if (panel === before) return;
    verseAudio().play(panel ? "ui_click" : "ui_close", { gain: 0.45, rate: panel ? 1 : 0.85, pitchJitter: 0.03 });
  }, [panel]);
}
