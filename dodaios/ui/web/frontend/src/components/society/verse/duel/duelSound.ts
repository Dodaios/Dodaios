/**
 * The duel's sound effects, synthesised with WebAudio (no recorded assets):
 * the blaster shot, impacts and body hits, the shield's block and parry,
 * overheat alarm, vent hiss and its perfect/missed chimes, roll whoosh,
 * countdown ticks, the round start and the match's end.
 *
 * Sounds from the opponent's side are panned and attenuated by where they
 * happen relative to the camera. The AudioContext is made on the first
 * sound after a user gesture (starting the duel is one); without WebAudio
 * (tests, old browsers) everything is silent.
 */
import type { CombatEvent } from "../combat/types";

type Ctx = AudioContext;

/** Listener for positional sounds: the camera's position and heading (yaw 0 faces +Z). */
export interface Listener { x: number; z: number; yaw: number }

export class DuelSound {
  private ctx: Ctx | null = null;
  private master: GainNode | null = null;
  private noise: AudioBuffer | null = null;
  private failed = false;
  volume = 0.55;

  private audio(): Ctx | null {
    if (this.ctx || this.failed) return this.ctx;
    try {
      const AC = (window as unknown as { AudioContext?: typeof AudioContext; webkitAudioContext?: typeof AudioContext }).AudioContext
        ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) { this.failed = true; return null; }
      const ctx = new AC();
      const master = ctx.createGain();
      master.gain.value = this.volume;
      // A gentle limiter keeps a burst of shots and impacts from clipping.
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -14;
      comp.ratio.value = 6;
      comp.attack.value = 0.003;
      comp.release.value = 0.12;
      master.connect(comp).connect(ctx.destination);
      const len = Math.floor(ctx.sampleRate * 1.2);
      const buf = ctx.createBuffer(1, len, ctx.sampleRate);
      const data = buf.getChannelData(0);
      let seed = 12345;
      for (let i = 0; i < len; i++) {
        seed = (seed * 1103515245 + 12345) & 0x7fffffff;
        data[i] = (seed / 0x7fffffff) * 2 - 1;
      }
      this.ctx = ctx;
      this.master = master;
      this.noise = buf;
    } catch {
      this.failed = true;
    }
    return this.ctx;
  }

  /** Wake the audio (call from a user gesture). */
  resume(): void {
    const ctx = this.audio();
    if (ctx && ctx.state === "suspended") void ctx.resume().catch(() => undefined);
  }

  dispose(): void {
    if (this.ctx) void this.ctx.close().catch(() => undefined);
    this.ctx = null;
    this.master = null;
  }

  /** An output for a sound at (x, z) heard from the listener; null for a sound at the listener. */
  private out(ctx: Ctx, gain: number, at?: { x: number; z: number } | null, l?: Listener | null): AudioNode {
    const g = ctx.createGain();
    let level = gain;
    if (at && l) {
      const dx = at.x - l.x;
      const dz = at.z - l.z;
      const d = Math.hypot(dx, dz);
      level *= 1 / (1 + Math.max(0, d - 2) / 9);
      if (d > 0.5) {
        const rel = Math.atan2(dx, dz) - l.yaw;
        // Right of the heading is negative rel (yaw grows to the left), so the pan is -sin(rel).
        const pan = ctx.createStereoPanner?.();
        if (pan) {
          pan.pan.value = Math.max(-0.85, Math.min(0.85, -Math.sin(rel)));
          g.connect(pan).connect(this.master as GainNode);
          g.gain.value = level;
          return g;
        }
      }
    }
    g.gain.value = level;
    g.connect(this.master as GainNode);
    return g;
  }

  private env(ctx: Ctx, node: AudioNode, t: number, attack: number, peak: number, decay: number): GainNode {
    const g = ctx.createGain();
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), t + attack);
    g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
    node.connect(g);
    return g;
  }

  private tone(ctx: Ctx, out: AudioNode, type: OscillatorType, f0: number, f1: number, t: number, attack: number, peak: number, decay: number): void {
    const o = ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(f0, t);
    if (f1 !== f0) o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + attack + decay);
    this.env(ctx, o, t, attack, peak, decay).connect(out);
    o.start(t);
    o.stop(t + attack + decay + 0.05);
  }

  private hiss(ctx: Ctx, out: AudioNode, kind: BiquadFilterType, f0: number, f1: number, q: number, t: number, attack: number, peak: number, decay: number): void {
    const src = ctx.createBufferSource();
    src.buffer = this.noise;
    src.loop = true;
    const f = ctx.createBiquadFilter();
    f.type = kind;
    f.Q.value = q;
    f.frequency.setValueAtTime(f0, t);
    if (f1 !== f0) f.frequency.exponentialRampToValueAtTime(Math.max(20, f1), t + attack + decay);
    src.connect(f);
    this.env(ctx, f, t, attack, peak, decay).connect(out);
    src.start(t, Math.random() * 0.8);
    src.stop(t + attack + decay + 0.05);
  }

  /** The blaster: a bright descending zap over a short noise crack and a low thump. */
  shot(local: boolean, at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, local ? 0.8 : 0.6, local ? null : at, l);
    const pitch = 0.94 + Math.random() * 0.12;
    this.tone(ctx, out, "sawtooth", 2400 * pitch, 260 * pitch, t, 0.002, 0.22, 0.14);
    this.tone(ctx, out, "square", 1300 * pitch, 180 * pitch, t, 0.002, 0.12, 0.11);
    this.hiss(ctx, out, "bandpass", 5200, 1800, 1.4, t, 0.001, 0.5, 0.06);
    this.tone(ctx, out, "sine", 150, 48, t, 0.003, local ? 0.6 : 0.35, 0.12);
  }

  /** A bolt meets a wall or the floor: crack and sizzle. */
  impact(at: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.55, at, l);
    this.hiss(ctx, out, "lowpass", 3200, 500, 0.8, t, 0.001, 0.7, 0.16);
    this.hiss(ctx, out, "highpass", 6000, 6000, 0.7, t + 0.01, 0.01, 0.12, 0.3);
    this.tone(ctx, out, "triangle", 420, 90, t, 0.001, 0.25, 0.08);
  }

  /** A bolt hits a body: a dull thud with a burn; the shooter hears a crisp marker tick. */
  bodyHit(local: boolean, headshot: boolean, at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, local ? 0.75 : 0.5, local ? null : at, l);
    this.tone(ctx, out, "sine", 210, 60, t, 0.002, 0.7, 0.14);
    this.hiss(ctx, out, "bandpass", 1800, 700, 1.2, t, 0.002, 0.45, 0.18);
    if (headshot) this.tone(ctx, out, "triangle", 900, 500, t, 0.002, 0.3, 0.12);
  }

  /** The shooter's hit confirmation. */
  marker(kind: "hit" | "head" | "kill"): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.35);
    if (kind === "kill") {
      this.tone(ctx, out, "triangle", 880, 880, t, 0.002, 0.5, 0.18);
      this.tone(ctx, out, "triangle", 1320, 1320, t + 0.07, 0.002, 0.45, 0.32);
      return;
    }
    this.tone(ctx, out, "sine", kind === "head" ? 2600 : 2100, kind === "head" ? 2600 : 2100, t, 0.001, 0.4, 0.05);
    if (kind === "head") this.tone(ctx, out, "sine", 3300, 3300, t + 0.045, 0.001, 0.35, 0.06);
  }

  /** The shield absorbs a bolt: an electric crackle with a hum. */
  block(at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.6, at, l);
    this.tone(ctx, out, "square", 180, 140, t, 0.002, 0.25, 0.2);
    this.hiss(ctx, out, "bandpass", 2600, 1200, 3, t, 0.002, 0.6, 0.2);
    this.tone(ctx, out, "sawtooth", 620, 380, t, 0.002, 0.12, 0.16);
  }

  /** A deflection glances off with a whine. */
  deflect(at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.55, at, l);
    this.tone(ctx, out, "triangle", 900, 2600, t, 0.002, 0.3, 0.22);
    this.hiss(ctx, out, "bandpass", 3500, 3500, 2, t, 0.002, 0.3, 0.12);
  }

  /** A perfect parry: a bright bell ring and a rising zing. */
  parry(at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.75, at, l);
    this.tone(ctx, out, "sine", 1320, 1320, t, 0.002, 0.55, 0.7);
    this.tone(ctx, out, "sine", 1980, 1980, t, 0.002, 0.35, 0.55);
    this.tone(ctx, out, "triangle", 2640, 2700, t, 0.002, 0.2, 0.4);
    this.tone(ctx, out, "sawtooth", 600, 3200, t, 0.002, 0.12, 0.18);
    this.hiss(ctx, out, "highpass", 5000, 8000, 1, t, 0.001, 0.3, 0.1);
  }

  shieldUp(local: boolean): void {
    const ctx = this.audio();
    if (!ctx || !local) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.3);
    this.tone(ctx, out, "sawtooth", 110, 220, t, 0.03, 0.25, 0.18);
    this.tone(ctx, out, "sine", 440, 660, t, 0.02, 0.12, 0.15);
  }

  shieldDown(local: boolean): void {
    const ctx = this.audio();
    if (!ctx || !local) return;
    const t = ctx.currentTime;
    this.tone(ctx, this.out(ctx, 0.22), "sawtooth", 220, 90, t, 0.01, 0.2, 0.14);
  }

  shieldBreak(at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.6, at, l);
    this.hiss(ctx, out, "bandpass", 4000, 400, 1.5, t, 0.002, 0.8, 0.45);
    this.tone(ctx, out, "square", 300, 60, t, 0.002, 0.3, 0.4);
  }

  /** Overheat: a falling two-tone alarm over a hiss. */
  overheat(): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.4);
    for (let i = 0; i < 3; i++) {
      this.tone(ctx, out, "square", 980, 980, t + i * 0.16, 0.004, 0.28, 0.06);
      this.tone(ctx, out, "square", 735, 735, t + i * 0.16 + 0.075, 0.004, 0.28, 0.06);
    }
    this.hiss(ctx, out, "highpass", 3000, 1500, 0.7, t, 0.02, 0.35, 0.7);
  }

  vent(seconds: number): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    this.hiss(ctx, this.out(ctx, 0.35), "bandpass", 5000, 1400, 0.9, t, 0.03, 0.5, Math.max(0.3, seconds));
  }

  ventPerfect(): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.35);
    this.tone(ctx, out, "triangle", 1046, 1046, t, 0.002, 0.4, 0.15);
    this.tone(ctx, out, "triangle", 1568, 1568, t + 0.06, 0.002, 0.4, 0.3);
  }

  ventMiss(): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    this.tone(ctx, this.out(ctx, 0.3), "square", 140, 120, t, 0.004, 0.3, 0.18);
  }

  dodge(local: boolean, at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    this.hiss(ctx, this.out(ctx, local ? 0.45 : 0.3, local ? null : at, l), "bandpass", 600, 2400, 1.6, t, 0.06, 0.6, 0.22);
  }

  death(at?: { x: number; z: number }, l?: Listener | null): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.6, at, l);
    this.tone(ctx, out, "sine", 120, 35, t, 0.005, 0.8, 0.6);
    this.hiss(ctx, out, "lowpass", 900, 120, 0.7, t, 0.005, 0.5, 0.5);
  }

  /** One countdown second. */
  tick(last: boolean): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    this.tone(ctx, this.out(ctx, 0.3), "sine", last ? 880 : 660, last ? 880 : 660, t, 0.003, 0.4, 0.12);
  }

  /** The round starts: a rising sweep into a bright chord. */
  roundStart(): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.4);
    this.tone(ctx, out, "sawtooth", 220, 880, t, 0.02, 0.18, 0.25);
    for (const f of [523, 659, 784]) this.tone(ctx, out, "triangle", f, f, t + 0.2, 0.01, 0.22, 0.5);
  }

  roundEnd(won: boolean): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.35);
    const chord = won ? [523, 659, 784, 1046] : [440, 523, 622];
    chord.forEach((f, i) => this.tone(ctx, out, "triangle", f, f, t + i * 0.07, 0.01, 0.22, 0.6));
  }

  surge(): void {
    const ctx = this.audio();
    if (!ctx) return;
    const t = ctx.currentTime;
    const out = this.out(ctx, 0.35);
    for (let i = 0; i < 2; i++) this.tone(ctx, out, "sawtooth", 160, 320, t + i * 0.45, 0.05, 0.25, 0.3);
  }

  /** Play whatever a frame's events call for. `slot` is the person's. */
  play(events: readonly CombatEvent[], slot: number, l: Listener | null): void {
    if (events.length === 0) return;
    for (const e of events) {
      switch (e.type) {
        case "shot": this.shot(e.player === slot, e, l); break;
        case "impact": this.impact(e, l); break;
        case "hit":
          this.bodyHit(e.target === slot, e.headshot, e, l);
          if (e.owner === slot && e.target !== slot) this.marker(e.health <= 0 ? "kill" : e.headshot ? "head" : "hit");
          break;
        case "block": this.block(e, l); break;
        case "deflect": this.deflect(e, l); break;
        case "parry": this.parry(e, l); break;
        case "shield_up": this.shieldUp(e.player === slot); break;
        case "shield_down": this.shieldDown(e.player === slot); break;
        case "shield_break": this.shieldBreak(undefined, l); break;
        case "overheat": if (e.player === slot) this.overheat(); break;
        case "vent_start": if (e.player === slot) this.vent((e.end - e.tick) / 60); break;
        case "vent_perfect": if (e.player === slot) this.ventPerfect(); break;
        case "vent_miss": if (e.player === slot) this.ventMiss(); break;
        case "dodge": this.dodge(e.player === slot); break;
        case "death": this.death(undefined, l); break;
        case "round_start": this.roundStart(); break;
        case "round_end": this.roundEnd(e.winner === slot); break;
        case "surge": this.surge(); break;
        default: break;
      }
    }
  }
}
