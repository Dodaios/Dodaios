import { afterEach, describe, expect, it, vi } from "vitest";
import { DuelSound } from "../duel/duelSound";
import type { PlayerView } from "../combat/view";
import { DUEL_SOUNDS, SOUND_FILES, VerseAudio, spatial } from "./verseAudio";

/** A WebAudio stand-in that records every buffer source started. */
function fakeAudio() {
  const started: { buffer: unknown; rate: number; loop: boolean }[] = [];
  const param = () => ({
    value: 1,
    setValueAtTime: vi.fn(), linearRampToValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn(),
    setTargetAtTime: vi.fn(), cancelScheduledValues: vi.fn(),
  });
  const node = () => ({ connect: vi.fn((n: unknown) => n), disconnect: vi.fn() });
  class Ctx {
    currentTime = 0;
    state = "running";
    destination = node();
    createGain() { return { ...node(), gain: param() }; }
    createStereoPanner() { return { ...node(), pan: param() }; }
    createDynamicsCompressor() { return { ...node(), threshold: param(), ratio: param(), attack: param(), release: param() }; }
    createBufferSource() {
      const src = {
        ...node(), buffer: null as unknown, loop: false, playbackRate: param(), onended: null,
        start: vi.fn(() => { started.push({ buffer: src.buffer, rate: src.playbackRate.value, loop: src.loop }); }),
        stop: vi.fn(),
      };
      return src;
    }
    decodeAudioData(data: ArrayBuffer) { return Promise.resolve({ duration: 0.3, tag: new Uint8Array(data)[0] }); }
    resume() { return Promise.resolve(); }
    suspend() { return Promise.resolve(); }
    close() { return Promise.resolve(); }
  }
  vi.stubGlobal("AudioContext", Ctx);
  return started;
}

afterEach(() => { vi.unstubAllGlobals(); });

describe("verse audio", () => {
  it("pans a sound to the side it happens on and fades it with distance", () => {
    const l = { x: 0, z: 0, yaw: 0 };
    const right = spatial({ x: -5, z: 0 }, l);
    const left = spatial({ x: 5, z: 0 }, l);
    expect(right.pan).toBeGreaterThan(0.5);
    expect(left.pan).toBeLessThan(-0.5);
    expect(spatial({ x: 0, z: 30 }, l).level).toBeLessThan(spatial({ x: 0, z: 3 }, l).level);
    expect(spatial({ x: 0, z: 0.2 }, l)).toEqual({ level: 1, pan: 0 });
  });

  it("lists a file for every duel sound", () => {
    for (const name of DUEL_SOUNDS) expect(SOUND_FILES[name].length).toBeGreaterThan(0);
  });

  it("loads lazily, plays the takes round robin and never one twice running", async () => {
    const started = fakeAudio();
    const fetcher = vi.fn(async (url: string) => new Uint8Array([Number(url.match(/shot_(\d)/)?.[1] ?? 0)]).buffer);
    const audio = new VerseAudio(fetcher);
    expect(audio.play("shot")).toBeNull();
    expect(fetcher).not.toHaveBeenCalled();
    await audio.preload(["shot"]);
    expect(fetcher).toHaveBeenCalledTimes(SOUND_FILES.shot.length);
    expect(fetcher.mock.calls[0][0]).toMatch(/verse\/audio\/shot_1\.ogg$/);
    for (let i = 0; i < 12; i++) audio.play("shot");
    expect(started).toHaveLength(12);
    for (let i = 1; i < started.length; i++) expect(started[i].buffer).not.toBe(started[i - 1].buffer);
    expect(new Set(started.map((s) => s.buffer)).size).toBe(SOUND_FILES.shot.length);
    // Each play varies the pitch a little around the asked rate.
    for (const s of started) expect(Math.abs(s.rate - 1)).toBeLessThanOrEqual(0.0401);
  });

  it("stays silent when the files cannot be fetched or there is no WebAudio", async () => {
    const started = fakeAudio();
    const debug = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const audio = new VerseAudio(async () => { throw new Error("404"); });
    await audio.preload(["shot", "step"]);
    expect(audio.loaded("shot")).toBe(false);
    expect(audio.play("shot")).toBeNull();
    expect(started).toHaveLength(0);
    debug.mockRestore();
    vi.unstubAllGlobals();
    vi.stubGlobal("AudioContext", undefined);
    const none = new VerseAudio(async () => new ArrayBuffer(1));
    await none.preload(["shot"]);
    expect(none.play("shot")).toBeNull();
  });
});

describe("duel sound", () => {
  const player = (o: Partial<PlayerView>): PlayerView => ({
    slot: 0, id: "p", local: true, side: 0, x: 0, z: 0, yaw: 0, pitch: 0, aimYaw: 0, aimPitch: 0, vx: 0, vz: 0, speed: 0,
    alive: true, health: 100, healthMax: 100, shieldUp: false, shieldEnergy: 1, shieldBroken: false, parrying: false,
    ads: 0, sprinting: false, dodging: false, dodgeProgress: 0, venting: false, overheated: false, heat: 0, ...o,
  });

  it("plays a footfall per stride while a player moves, none while they stand", async () => {
    const started = fakeAudio();
    const audio = new VerseAudio(async () => new ArrayBuffer(1));
    await audio.preload(["step"]);
    const sound = new DuelSound(audio);
    const l = { x: 0, z: 0, yaw: 0 };
    // Walking 4 m/s for one second at 60 fps covers about 2.7 strides.
    for (let i = 0; i <= 60; i++) sound.play([], 0, l, [player({ z: (i * 4) / 60, speed: 4 })]);
    expect(started.length).toBeGreaterThanOrEqual(2);
    expect(started.length).toBeLessThanOrEqual(3);
    const walked = started.length;
    for (let i = 0; i < 60; i++) sound.play([], 0, l, [player({ z: 4, speed: 0 })]);
    expect(started.length).toBe(walked);
  });

  it("keeps the shield's hum while it is up and stops it when the match pauses", async () => {
    fakeAudio();
    const audio = new VerseAudio(async () => new ArrayBuffer(1));
    await audio.preload(["shield_hum", "shield_up"]);
    const sound = new DuelSound(audio);
    const stop = vi.fn();
    const play = vi.spyOn(audio, "play").mockReturnValue({ stop, setGain: vi.fn(), setRate: vi.fn() });
    sound.play([{ type: "shield_up", tick: 1, player: 0, seq: 1 }], 0, null);
    expect(play).toHaveBeenCalledWith("shield_hum", expect.objectContaining({ loop: true }));
    sound.silence();
    expect(stop).toHaveBeenCalled();
  });
});
