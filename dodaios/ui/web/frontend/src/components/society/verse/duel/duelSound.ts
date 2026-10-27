/**
 * The duel's sound effects: recorded takes (verse/audio, see its CREDITS.md)
 * for the blaster shot, impacts and body hits, the shield's hum, block and
 * parry, the overheat alarm and vent hiss, the roll, footsteps on the deck
 * plating, the countdown beeps, the round start and the match's end.
 *
 * Sounds from the opponent's side are panned and attenuated by where they
 * happen relative to the camera. The takes load when a duel starts (a user
 * gesture, so the AudioContext may start too); until they have arrived, or
 * without WebAudio (tests, old browsers), everything is silent.
 */
import type { CombatEvent } from "../combat/types";
import type { PlayerView } from "../combat/view";
import { DUEL_SOUNDS, verseAudio, type Listener, type VerseAudio, type Voice } from "../audio/verseAudio";

export type { Listener } from "../audio/verseAudio";

type At = { x: number; z: number } | undefined;

/** Metres between footfalls walking and sprinting. */
const STRIDE_WALK = 1.45;
const STRIDE_RUN = 2.1;

export class DuelSound {
  private readonly audio: VerseAudio;
  private hum: Voice | null = null;
  private vent: Voice | null = null;
  /** Distance each player has covered since their last footfall, and where they were last frame. */
  private readonly walked = new Map<number, { x: number; z: number; d: number }>();

  constructor(audio: VerseAudio = verseAudio()) {
    this.audio = audio;
  }

  /** Wake the audio and fetch the duel's sounds (call from a user gesture: starting the duel is one). */
  resume(): void {
    this.audio.resume();
    void this.audio.preload(DUEL_SOUNDS);
  }

  /** Stop what is still sounding (the shield's hum, a vent): the match paused or ended. */
  silence(): void {
    this.dispose();
  }

  dispose(): void {
    this.hum?.stop(0.05);
    this.hum = null;
    this.vent?.stop(0.05);
    this.vent = null;
    this.walked.clear();
  }

  private remote(local: boolean, at: At, l?: Listener | null) {
    return local ? {} : { at: at ?? null, listener: l ?? null };
  }

  shot(local: boolean, at?: At, l?: Listener | null): void {
    this.audio.play("shot", { gain: local ? 0.9 : 0.75, pitchJitter: 0.05, ...this.remote(local, at, l) });
  }

  impact(at: { x: number; z: number }, l?: Listener | null): void {
    this.audio.play("impact", { gain: 0.6, pitchJitter: 0.08, at, listener: l ?? null });
  }

  bodyHit(local: boolean, at?: At, l?: Listener | null): void {
    this.audio.play("body_hit", { gain: local ? 1 : 0.7, ...this.remote(local, at, l) });
  }

  /** The shooter's hit confirmation: a short tick, higher for a headshot, doubled for the kill. */
  marker(kind: "hit" | "head" | "kill"): void {
    this.audio.play("marker", { gain: 0.5, rate: kind === "head" ? 1.25 : 1, pitchJitter: 0.01 });
    if (kind === "kill") this.audio.play("marker", { gain: 0.5, rate: 1.5, pitchJitter: 0.01, delay: 0.08 });
  }

  block(at?: At, l?: Listener | null): void {
    this.audio.play("block", { gain: 0.75, at: at ?? null, listener: l ?? null });
  }

  deflect(at?: At, l?: Listener | null): void {
    this.audio.play("deflect", { gain: 0.7, pitchJitter: 0.08, at: at ?? null, listener: l ?? null });
  }

  parry(at?: At, l?: Listener | null): void {
    this.audio.play("parry", { gain: 0.9, pitchJitter: 0.02, at: at ?? null, listener: l ?? null });
    this.audio.play("block", { gain: 0.45, rate: 1.3, at: at ?? null, listener: l ?? null });
  }

  /** The person's shield comes up: a power-on thump and a hum that lasts while it is raised. */
  shieldUp(local: boolean): void {
    if (!local) return;
    this.audio.play("shield_up", { gain: 0.55 });
    this.hum?.stop(0.05);
    this.hum = this.audio.play("shield_hum", { gain: 0.28, loop: true, fadeIn: 0.12, pitchJitter: 0 });
  }

  shieldDown(local: boolean): void {
    if (!local) return;
    if (this.hum) {
      this.hum.setRate(0.8, 0.15);
      this.hum.stop(0.18);
      this.hum = null;
    }
  }

  shieldBreak(at?: At, l?: Listener | null): void {
    this.hum?.stop(0.05);
    this.hum = null;
    this.audio.play("shield_break", { gain: 0.8, at: at ?? null, listener: l ?? null });
  }

  overheat(): void {
    this.audio.play("overheat", { gain: 0.5, pitchJitter: 0 });
  }

  ventStart(seconds: number): void {
    this.vent?.stop(0.05);
    this.vent = this.audio.play("vent", { gain: 0.55, duration: Math.max(0.35, seconds), pitchJitter: 0.03 });
  }

  ventPerfect(): void {
    this.vent?.stop(0.12);
    this.vent = null;
    this.audio.play("vent_perfect", { gain: 0.6, pitchJitter: 0 });
  }

  ventMiss(): void {
    this.audio.play("vent_miss", { gain: 0.6, pitchJitter: 0.02 });
  }

  dodge(local: boolean, at?: At, l?: Listener | null): void {
    this.audio.play("dodge", { gain: local ? 0.8 : 0.55, ...this.remote(local, at, l) });
  }

  death(at?: At, l?: Listener | null): void {
    this.audio.play("death", { gain: 0.9, pitchJitter: 0.03, at: at ?? null, listener: l ?? null });
  }

  /** One countdown second; the last one is higher. */
  tick(last: boolean): void {
    this.audio.play("beep", { gain: 0.45, rate: last ? 1.5 : 1, pitchJitter: 0 });
  }

  roundStart(): void {
    this.audio.play("round_start", { gain: 0.6, pitchJitter: 0 });
  }

  roundEnd(won: boolean): void {
    this.hum?.stop(0.1);
    this.hum = null;
    this.audio.play("round_end", { gain: 0.6, rate: won ? 1 : 0.84, pitchJitter: 0 });
  }

  surge(): void {
    this.audio.play("surge", { gain: 0.5, pitchJitter: 0 });
  }

  /** Footfalls on the plating for every player on their feet, from how far each moved since the last frame. */
  steps(players: readonly PlayerView[], slot: number, l: Listener | null): void {
    for (const p of players) {
      const prev = this.walked.get(p.slot);
      if (!prev || !p.alive || p.dodging) {
        this.walked.set(p.slot, { x: p.x, z: p.z, d: prev && p.alive ? prev.d : 0 });
        continue;
      }
      const moved = Math.hypot(p.x - prev.x, p.z - prev.z);
      // A respawn or a round's reset teleports: no footfall for that.
      const d = moved > 1.5 ? 0 : prev.d + moved;
      const stride = p.sprinting ? STRIDE_RUN : STRIDE_WALK;
      const local = p.slot === slot;
      if (d >= stride && p.speed > 0.4) {
        const run = p.sprinting;
        this.audio.play("step", {
          gain: (run ? 0.55 : 0.38) * (local ? 1 : 0.9),
          rate: run ? 1.06 : 1,
          pitchJitter: 0.06,
          gainJitter: 0.2,
          ...this.remote(local, p, l),
        });
        this.walked.set(p.slot, { x: p.x, z: p.z, d: 0 });
      } else {
        this.walked.set(p.slot, { x: p.x, z: p.z, d: p.speed > 0.4 ? d : Math.min(d, stride * 0.6) });
      }
    }
  }

  /** Play whatever a frame's events call for. `slot` is the person's. */
  play(events: readonly CombatEvent[], slot: number, l: Listener | null, players?: readonly PlayerView[]): void {
    if (players) this.steps(players, slot, l);
    if (events.length === 0) return;
    const where = (player: number): At => players?.find((p) => p.slot === player);
    for (const e of events) {
      switch (e.type) {
        case "shot": this.shot(e.player === slot, e, l); break;
        case "impact": this.impact(e, l); break;
        case "hit":
          this.bodyHit(e.target === slot, e, l);
          if (e.owner === slot && e.target !== slot) this.marker(e.health <= 0 ? "kill" : e.headshot ? "head" : "hit");
          break;
        case "block": this.block(e, l); break;
        case "deflect": this.deflect(e, l); break;
        case "parry": this.parry(e, l); break;
        case "shield_up": this.shieldUp(e.player === slot); break;
        case "shield_down": this.shieldDown(e.player === slot); break;
        case "shield_break": this.shieldBreak(e.player === slot ? undefined : where(e.player), l); break;
        case "overheat": if (e.player === slot) this.overheat(); break;
        case "vent_start": if (e.player === slot) this.ventStart((e.end - e.tick) / 60); break;
        case "vent_perfect": if (e.player === slot) this.ventPerfect(); break;
        case "vent_miss": if (e.player === slot) this.ventMiss(); break;
        case "dodge": this.dodge(e.player === slot, where(e.player), l); break;
        case "death": this.death(e.player === slot ? undefined : where(e.player), l); break;
        case "round_start": this.roundStart(); break;
        case "round_end": this.roundEnd(e.winner === slot); break;
        case "surge": this.surge(); break;
        default: break;
      }
    }
  }
}
