/**
 * The courier's engine sound, synthesised (no audio files): a low hum and a
 * filtered rush that rise with the throttle, a hiss for the boost, a thud on
 * impact. It is placed in space at the ship and heard from the camera, so it
 * pans with the view; its pitch shifts with the speed between the two
 * (Doppler); in the cockpit a low-pass makes it the muffled inside of the hull.
 *
 * The audio context starts on boarding (a key press or a click, so the
 * browser allows it) and is closed again on leaving the ship.
 */
const SPEED_OF_SOUND = 343;

export interface EngineFrame {
  throttle: number;
  boost: boolean;
  /** Ship and listener positions and velocities, world metres and metres per second. */
  ship: { x: number; y: number; z: number };
  shipVelocity: { x: number; y: number; z: number };
  listener: { x: number; y: number; z: number };
  listenerVelocity: { x: number; y: number; z: number };
  /** The listener's forward and up, for the panning. */
  forward: { x: number; y: number; z: number };
  up: { x: number; y: number; z: number };
  inside: boolean;
  volume: number;
}

/** The pitch factor heard for a source moving relative to a listener (classic Doppler, clamped). */
export function dopplerFactor(frame: Pick<EngineFrame, "ship" | "shipVelocity" | "listener" | "listenerVelocity">): number {
  const dx = frame.ship.x - frame.listener.x, dy = frame.ship.y - frame.listener.y, dz = frame.ship.z - frame.listener.z;
  const d = Math.hypot(dx, dy, dz);
  if (d < 1e-3) return 1;
  const ux = dx / d, uy = dy / d, uz = dz / d;
  // Speeds along the line from listener to source; positive = moving away from the other.
  const source = frame.shipVelocity.x * ux + frame.shipVelocity.y * uy + frame.shipVelocity.z * uz;
  const listener = frame.listenerVelocity.x * ux + frame.listenerVelocity.y * uy + frame.listenerVelocity.z * uz;
  const factor = (SPEED_OF_SOUND + listener) / (SPEED_OF_SOUND + source);
  return Math.min(1.6, Math.max(0.6, factor));
}

export class CourierEngineSound {
  private ctx: AudioContext;
  private master!: GainNode;
  private panner!: PannerNode;
  private muffle!: BiquadFilterNode;
  private hum!: OscillatorNode;
  private hum2!: OscillatorNode;
  private humGain!: GainNode;
  private rushFilter!: BiquadFilterNode;
  private rushGain!: GainNode;
  private hissGain!: GainNode;

  constructor() {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    this.ctx = ctx;
    try {
      this.build(ctx);
    } catch (error) {
      // Half a graph is no use: close the context so it does not linger, and let the caller go on in silence.
      void ctx.close().catch((closeError) => console.warn("courier sound context did not close", closeError));
      throw error;
    }
  }

  private build(ctx: AudioContext): void {
    this.master = ctx.createGain();
    this.master.gain.value = 0;
    this.muffle = ctx.createBiquadFilter();
    this.muffle.type = "lowpass";
    this.muffle.frequency.value = 18000;
    this.panner = ctx.createPanner();
    this.panner.panningModel = "HRTF";
    this.panner.distanceModel = "inverse";
    this.panner.refDistance = 12;
    this.panner.rolloffFactor = 0.8;
    this.panner.connect(this.muffle).connect(this.master).connect(ctx.destination);

    // The hum: two detuned oscillators, a saw and a square an octave up.
    this.humGain = ctx.createGain();
    this.humGain.gain.value = 0;
    const humFilter = ctx.createBiquadFilter();
    humFilter.type = "lowpass";
    humFilter.frequency.value = 900;
    this.hum = ctx.createOscillator();
    this.hum.type = "sawtooth";
    this.hum.frequency.value = 48;
    this.hum2 = ctx.createOscillator();
    this.hum2.type = "square";
    this.hum2.frequency.value = 97;
    this.hum.connect(humFilter);
    this.hum2.connect(humFilter);
    humFilter.connect(this.humGain).connect(this.panner);

    // The rush and the boost's hiss: one looping noise buffer, two filters.
    const noise = ctx.createBufferSource();
    const buffer = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i += 1) data[i] = Math.random() * 2 - 1;
    noise.buffer = buffer;
    noise.loop = true;
    this.rushFilter = ctx.createBiquadFilter();
    this.rushFilter.type = "bandpass";
    this.rushFilter.Q.value = 0.7;
    this.rushGain = ctx.createGain();
    this.rushGain.gain.value = 0;
    noise.connect(this.rushFilter).connect(this.rushGain).connect(this.panner);
    const hissFilter = ctx.createBiquadFilter();
    hissFilter.type = "highpass";
    hissFilter.frequency.value = 3500;
    this.hissGain = ctx.createGain();
    this.hissGain.gain.value = 0;
    noise.connect(hissFilter).connect(this.hissGain).connect(this.panner);

    this.hum.start();
    this.hum2.start();
    noise.start();
  }

  update(frame: EngineFrame): void {
    const t = this.ctx.currentTime, glide = 0.08;
    const doppler = dopplerFactor(frame);
    const th = frame.throttle;
    this.master.gain.setTargetAtTime(frame.volume * 0.5, t, 0.3);
    this.hum.frequency.setTargetAtTime((44 + th * 40) * doppler, t, glide);
    this.hum2.frequency.setTargetAtTime((89 + th * 82) * doppler, t, glide);
    this.humGain.gain.setTargetAtTime(0.18 + th * 0.22, t, glide);
    this.rushFilter.frequency.setTargetAtTime((300 + th * 1400) * doppler, t, glide);
    this.rushGain.gain.setTargetAtTime(0.05 + th * 0.35, t, glide);
    this.hissGain.gain.setTargetAtTime(frame.boost ? 0.16 : 0, t, 0.15);
    this.muffle.frequency.setTargetAtTime(frame.inside ? 700 : 18000, t, 0.2);
    setPosition(this.panner, frame.ship, t);
    const l = this.ctx.listener;
    if (l.positionX) {
      l.positionX.setTargetAtTime(frame.listener.x, t, 0.03);
      l.positionY.setTargetAtTime(frame.listener.y, t, 0.03);
      l.positionZ.setTargetAtTime(frame.listener.z, t, 0.03);
      l.forwardX.setTargetAtTime(frame.forward.x, t, 0.03);
      l.forwardY.setTargetAtTime(frame.forward.y, t, 0.03);
      l.forwardZ.setTargetAtTime(frame.forward.z, t, 0.03);
      l.upX.setTargetAtTime(frame.up.x, t, 0.03);
      l.upY.setTargetAtTime(frame.up.y, t, 0.03);
      l.upZ.setTargetAtTime(frame.up.z, t, 0.03);
    } else {
      // Older engines: the deprecated setters.
      l.setPosition(frame.listener.x, frame.listener.y, frame.listener.z);
      l.setOrientation(frame.forward.x, frame.forward.y, frame.forward.z, frame.up.x, frame.up.y, frame.up.z);
    }
  }

  /** A thud for an impact of this speed (m/s); the master gain already carries the pilot's volume. */
  impact(speed: number): void {
    const t = this.ctx.currentTime;
    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(90, t);
    osc.frequency.exponentialRampToValueAtTime(30, t + 0.4);
    gain.gain.setValueAtTime(Math.min(0.8, speed / 40), t);
    gain.gain.exponentialRampToValueAtTime(0.001, t + 0.5);
    osc.connect(gain).connect(this.muffle);
    osc.start(t);
    osc.stop(t + 0.55);
  }

  resume(): void {
    if (this.ctx.state === "suspended") void this.ctx.resume().catch((error) => console.warn("courier sound could not start", error));
  }

  close(): void {
    void this.ctx.close().catch((error) => console.warn("courier sound did not close cleanly", error));
  }
}

function setPosition(panner: PannerNode, p: { x: number; y: number; z: number }, t: number) {
  if (panner.positionX) {
    panner.positionX.setTargetAtTime(p.x, t, 0.03);
    panner.positionY.setTargetAtTime(p.y, t, 0.03);
    panner.positionZ.setTargetAtTime(p.z, t, 0.03);
  } else {
    panner.setPosition(p.x, p.y, p.z);
  }
}
