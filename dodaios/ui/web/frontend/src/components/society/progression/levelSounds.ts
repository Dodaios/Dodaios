/**
 * Promotion sounds, synthesised with Web Audio: no files to ship, nothing to
 * load. The ship's bell: two pairs of strikes for the commander's or the
 * companion drone's promotion, one quiet pair for an officer's, a short
 * console blip for "+XP". The listener can switch them off in the service
 * record. A browser without Web Audio, or one that refuses to start it,
 * plays nothing.
 */
import { create } from "zustand";

const SOUND_KEY = "jarvis.verse.level.sound.v1";

function readSoundOn(): boolean {
  try {
    return typeof localStorage === "undefined" || localStorage.getItem(SOUND_KEY) !== "off";
  } catch (error) {
    console.debug("Verse sound setting unavailable", error);
    return true;
  }
}

export const useLevelSound = create<{ on: boolean; set: (on: boolean) => void }>((set) => ({
  on: readSoundOn(),
  set: (on) => {
    set({ on });
    try { localStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch (error) { console.debug("Verse sound setting not saved", error); }
  },
}));

let context: AudioContext | null = null;

function audio(): AudioContext | null {
  if (!useLevelSound.getState().on) return null;
  try {
    const Ctor = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctor) return null;
    context ??= new Ctor();
    if (context.state === "suspended") void context.resume().catch(() => undefined);
    return context;
  } catch (error) {
    console.debug("Web Audio unavailable", error);
    return null;
  }
}

function tone(ctx: AudioContext, freq: number, start: number, length: number, gain: number, type: OscillatorType = "sine"): void {
  const osc = ctx.createOscillator();
  const amp = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(freq, start);
  amp.gain.setValueAtTime(0.0001, start);
  amp.gain.exponentialRampToValueAtTime(gain, start + 0.004);
  amp.gain.exponentialRampToValueAtTime(0.0001, start + length);
  osc.connect(amp).connect(ctx.destination);
  osc.start(start);
  osc.stop(start + length + 0.02);
}

/** Partials of a small bronze bell (ratio to the strike tone, relative gain, decay in s). */
const BELL: readonly (readonly [number, number, number])[] = [[1, 1, 1.4], [2.02, 0.45, 0.9], [2.76, 0.3, 0.6], [5.4, 0.12, 0.25]];
const STRIKE_HZ = 932.33;

function strike(ctx: AudioContext, at: number, gain: number): void {
  for (const [ratio, weight, decay] of BELL) tone(ctx, STRIKE_HZ * ratio, at, decay, gain * weight);
}

/** The ship's bell: two strikes close together, a pause, two more for a big moment. */
export function playLevelUp(big: boolean): void {
  const ctx = audio();
  if (!ctx) return;
  const t = ctx.currentTime + 0.02;
  const pairs = big ? [0, 0.62] : [0];
  const gain = big ? 0.05 : 0.03;
  for (const pair of pairs) {
    strike(ctx, t + pair, gain);
    strike(ctx, t + pair + 0.2, gain);
  }
}

/** A short, low console blip. */
export function playXpTick(): void {
  const ctx = audio();
  if (!ctx) return;
  const t = ctx.currentTime + 0.01;
  tone(ctx, 660, t, 0.06, 0.02, "square");
}
