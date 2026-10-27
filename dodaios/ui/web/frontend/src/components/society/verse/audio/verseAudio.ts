/**
 * The Verse's sound: recorded effects (public/verse/audio, credits in its
 * CREDITS.md) played through one shared WebAudio context.
 *
 * Nothing is fetched until something asks for a sound: `preload` starts the
 * download of a group (the duel's, the deck's), `play` plays a loaded sound
 * and quietly skips one that is not there yet, failed to load, or when the
 * browser has no WebAudio. Every play gets a small random pitch and level
 * change and steps through a sound's recorded variants, so a burst of shots
 * or footsteps never repeats the same take twice in a row. A sound placed in
 * the world is panned and attenuated by where the listener stands.
 *
 * The level follows the person's Verse volume setting; UI sounds switched
 * off for the app (`jarvis.ui.sound` = "off") silence the Verse too.
 */

/** Every sound and its recorded takes (files under public/verse/audio). */
export const SOUND_FILES = {
  shot: ["shot_1.ogg", "shot_2.ogg", "shot_3.ogg", "shot_4.ogg"],
  impact: ["impact_metal_1.ogg", "impact_metal_2.ogg", "impact_metal_3.ogg"],
  body_hit: ["body_hit_1.ogg", "body_hit_2.ogg", "body_hit_3.ogg"],
  marker: ["marker.ogg"],
  block: ["shield_block_1.ogg", "shield_block_2.ogg"],
  deflect: ["deflect.ogg"],
  parry: ["parry.ogg"],
  shield_hum: ["shield_hum.ogg"],
  shield_up: ["shield_up.ogg"],
  shield_break: ["shield_break.ogg"],
  overheat: ["overheat.ogg"],
  vent: ["vent.ogg"],
  vent_perfect: ["vent_perfect.ogg"],
  vent_miss: ["vent_miss.ogg"],
  dodge: ["dodge_1.ogg", "dodge_2.ogg"],
  step: ["step_1.ogg", "step_2.ogg", "step_3.ogg", "step_4.ogg", "step_5.ogg", "step_6.ogg"],
  death: ["knockout.ogg"],
  beep: ["beep.ogg"],
  round_start: ["round_start.ogg"],
  round_end: ["round_end.ogg"],
  surge: ["surge.ogg"],
  ui_click: ["ui_click.ogg"],
  ui_close: ["ui_click.ogg"],
  door_open: ["door_open.ogg"],
  door_close: ["door_close.ogg"],
  lift_ride: ["lift_ride.ogg"],
  amb_bridge: ["amb_bridge.ogg"],
  amb_engineering: ["amb_engineering.ogg"],
  amb_hangar: ["amb_hangar.ogg"],
  amb_ops: ["amb_ops.ogg"],
} as const satisfies Record<string, readonly string[]>;

export type SoundName = keyof typeof SOUND_FILES;

/** The sounds a duel uses (loaded when one starts). */
export const DUEL_SOUNDS: readonly SoundName[] = [
  "shot", "impact", "body_hit", "marker", "block", "deflect", "parry", "shield_hum", "shield_up", "shield_break",
  "overheat", "vent", "vent_perfect", "vent_miss", "dodge", "step", "death", "beep", "round_start", "round_end", "surge",
];

/** Where the listener is: the camera's position and heading (yaw 0 faces +Z). */
export interface Listener { x: number; z: number; yaw: number }

export interface PlayOptions {
  /** Linear level before the master volume (1 = as recorded). */
  gain?: number;
  /** Playback rate (1 = as recorded); the random variation is applied on top. */
  rate?: number;
  /** Random pitch spread, ± fraction of the rate (default 0.04). */
  pitchJitter?: number;
  /** Random level spread, ± fraction of the gain (default 0.1). */
  gainJitter?: number;
  /** Where the sound happens; with a listener it is panned and attenuated. */
  at?: { x: number; z: number } | null;
  listener?: Listener | null;
  /** Loop the buffer until the voice is stopped. */
  loop?: boolean;
  /** Seconds of fade-in. */
  fadeIn?: number;
  /** Stop after this many seconds (with a short fade). */
  duration?: number;
  /** Seconds from now to start. */
  delay?: number;
}

/** A sound that is playing; `stop` fades it out. */
export interface Voice {
  stop(fade?: number): void;
  setGain(gain: number, ramp?: number): void;
  setRate(rate: number, ramp?: number): void;
}

const UI_SOUND_KEY = "jarvis.ui.sound";
const MASTER_LEVEL = 0.9;

function uiSoundOn(): boolean {
  try {
    return typeof localStorage === "undefined" || localStorage.getItem(UI_SOUND_KEY) !== "off";
  } catch {
    return true;
  }
}

/** Level and pan for a sound at `at` heard by `l`: quieter with distance, panned to its side. Pure. */
export function spatial(at: { x: number; z: number }, l: Listener): { level: number; pan: number } {
  const dx = at.x - l.x;
  const dz = at.z - l.z;
  const d = Math.hypot(dx, dz);
  const level = 1 / (1 + Math.max(0, d - 2) / 9);
  if (d <= 0.5) return { level, pan: 0 };
  // Right of the heading is negative rel (yaw grows to the left), so the pan is -sin(rel).
  const rel = Math.atan2(dx, dz) - l.yaw;
  return { level, pan: Math.max(-0.85, Math.min(0.85, -Math.sin(rel))) };
}

export function audioBase(): string {
  const base = (import.meta.env?.BASE_URL as string | undefined) ?? "/";
  return `${base.endsWith("/") ? base : `${base}/`}verse/audio/`;
}

type Ctor = typeof AudioContext;

export class VerseAudio {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private failed = false;
  private volume = 0.7;
  private readonly buffers = new Map<SoundName, AudioBuffer[]>();
  private readonly loading = new Map<SoundName, Promise<void>>();
  private readonly turn = new Map<SoundName, number>();

  constructor(private readonly fetcher: (url: string) => Promise<ArrayBuffer> = defaultFetch) {}

  /** The context, made on first use; null without WebAudio. */
  context(): AudioContext | null {
    if (this.ctx || this.failed) return this.ctx;
    try {
      const w = window as unknown as { AudioContext?: Ctor; webkitAudioContext?: Ctor };
      const AC = w.AudioContext ?? w.webkitAudioContext;
      if (!AC) { this.failed = true; return null; }
      const ctx = new AC();
      const master = ctx.createGain();
      master.gain.value = this.level();
      // A gentle limiter keeps a burst of shots and impacts from clipping.
      const comp = ctx.createDynamicsCompressor?.();
      if (comp) {
        comp.threshold.value = -10;
        comp.ratio.value = 4;
        comp.attack.value = 0.003;
        comp.release.value = 0.15;
        master.connect(comp).connect(ctx.destination);
      } else {
        master.connect(ctx.destination);
      }
      this.ctx = ctx;
      this.master = master;
    } catch {
      this.failed = true;
    }
    return this.ctx;
  }

  private level(): number {
    return uiSoundOn() ? this.volume * MASTER_LEVEL : 0;
  }

  /** The person's Verse volume, 0..1. */
  setVolume(volume: number): void {
    this.volume = Math.max(0, Math.min(1, Number.isFinite(volume) ? volume : 0.7));
    const ctx = this.ctx;
    if (ctx && this.master) this.master.gain.setTargetAtTime(this.level(), ctx.currentTime, 0.05);
  }

  /** Wake the audio (call from a user gesture). */
  resume(): void {
    const ctx = this.context();
    if (ctx && ctx.state === "suspended") void ctx.resume().catch(() => undefined);
  }

  /** Let the audio hardware rest while nothing in the Verse plays. */
  suspend(): void {
    if (this.ctx && this.ctx.state === "running") void this.ctx.suspend().catch(() => undefined);
  }

  loaded(name: SoundName): boolean {
    return (this.buffers.get(name)?.length ?? 0) > 0;
  }

  /** Start fetching and decoding these sounds (each once); resolves when all have settled. */
  preload(names: readonly SoundName[]): Promise<void> {
    const ctx = this.context();
    if (!ctx) return Promise.resolve();
    return Promise.all(names.map((name) => {
      let pending = this.loading.get(name);
      if (!pending) {
        pending = this.load(ctx, name);
        this.loading.set(name, pending);
      }
      return pending;
    })).then(() => undefined);
  }

  private async load(ctx: AudioContext, name: SoundName): Promise<void> {
    const base = audioBase();
    const takes = await Promise.all(SOUND_FILES[name].map(async (file) => {
      try {
        const data = await this.fetcher(base + file);
        return await decode(ctx, data);
      } catch (error) {
        console.debug(`Verse sound ${file} unavailable`, error);
        return null;
      }
    }));
    const ok = takes.filter((b): b is AudioBuffer => b !== null);
    if (ok.length > 0) this.buffers.set(name, ok);
  }

  /** The next take of a sound: round robin from a random start, never the same take twice running. */
  private take(name: SoundName): AudioBuffer | null {
    const list = this.buffers.get(name);
    if (!list || list.length === 0) return null;
    if (list.length === 1) return list[0];
    const last = this.turn.get(name);
    let next = last === undefined ? Math.floor(Math.random() * list.length) : (last + 1 + Math.floor(Math.random() * (list.length - 1))) % list.length;
    if (next === last) next = (next + 1) % list.length;
    this.turn.set(name, next);
    return list[next];
  }

  /** Play a loaded sound; null when it cannot be heard (not loaded, no WebAudio, silenced). */
  play(name: SoundName, o: PlayOptions = {}): Voice | null {
    const ctx = this.ctx;
    const master = this.master;
    if (!ctx || !master) return null;
    const buffer = this.take(name);
    if (!buffer) return null;
    try {
      const t = ctx.currentTime + (o.delay ?? 0);
      const src = ctx.createBufferSource();
      src.buffer = buffer;
      src.loop = !!o.loop;
      const pj = o.pitchJitter ?? 0.04;
      const gj = o.gainJitter ?? 0.1;
      const rate = (o.rate ?? 1) * (1 + (Math.random() * 2 - 1) * pj);
      src.playbackRate.value = rate;
      let level = (o.gain ?? 1) * (1 + (Math.random() * 2 - 1) * gj);
      let pan = 0;
      if (o.at && o.listener) {
        const s = spatial(o.at, o.listener);
        level *= s.level;
        pan = s.pan;
      }
      const g = ctx.createGain();
      if (o.fadeIn && o.fadeIn > 0) {
        g.gain.setValueAtTime(0.0001, t);
        g.gain.linearRampToValueAtTime(level, t + o.fadeIn);
      } else {
        g.gain.setValueAtTime(level, t);
      }
      src.connect(g);
      const panner = pan !== 0 ? ctx.createStereoPanner?.() : undefined;
      if (panner) {
        panner.pan.value = pan;
        g.connect(panner).connect(master);
      } else {
        g.connect(master);
      }
      src.start(t);
      let stopped = false;
      const stop = (fade = 0.08): void => {
        if (stopped) return;
        stopped = true;
        try {
          const now = ctx.currentTime;
          g.gain.cancelScheduledValues(now);
          g.gain.setValueAtTime(g.gain.value, now);
          g.gain.linearRampToValueAtTime(0.0001, now + Math.max(0.005, fade));
          src.stop(now + Math.max(0.005, fade) + 0.02);
        } catch {
          /* already stopped */
        }
      };
      if (o.duration !== undefined) {
        const end = t + Math.max(0.02, o.duration);
        g.gain.setValueAtTime(level, Math.max(t, end - 0.06));
        g.gain.linearRampToValueAtTime(0.0001, end);
        src.stop(end + 0.02);
        stopped = true;
      }
      src.onended = () => { try { g.disconnect(); panner?.disconnect(); } catch { /* gone */ } };
      return {
        stop,
        setGain: (gain, ramp = 0.1) => {
          if (stopped) return;
          g.gain.setTargetAtTime(Math.max(0.0001, gain), ctx.currentTime, ramp / 3);
        },
        setRate: (r, ramp = 0.1) => {
          if (stopped) return;
          src.playbackRate.setTargetAtTime(r, ctx.currentTime, ramp / 3);
        },
      };
    } catch (error) {
      console.debug(`Verse sound ${name} did not play`, error);
      return null;
    }
  }

  /** Close the context (the page is going away). */
  dispose(): void {
    if (this.ctx) void this.ctx.close().catch(() => undefined);
    this.ctx = null;
    this.master = null;
    this.buffers.clear();
    this.loading.clear();
  }
}

async function defaultFetch(url: string): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${res.status} ${url}`);
  return res.arrayBuffer();
}

function decode(ctx: AudioContext, data: ArrayBuffer): Promise<AudioBuffer> {
  // Older WebKit only has the callback form.
  return new Promise((resolve, reject) => {
    const p = ctx.decodeAudioData(data, resolve, reject) as Promise<AudioBuffer> | undefined;
    if (p && typeof p.then === "function") p.then(resolve, reject);
  });
}

let shared: VerseAudio | null = null;

/** The one audio engine every part of the Verse plays through. */
export function verseAudio(): VerseAudio {
  shared ??= new VerseAudio();
  return shared;
}
