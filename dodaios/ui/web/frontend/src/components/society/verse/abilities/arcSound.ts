/**
 * Arc Storm's sound, synthesised with WebAudio: a low electric hum under a
 * crackle of filtered noise whose loudness jumps with every strike. Made on
 * the first press (a user gesture); silent without WebAudio.
 */
export class ArcSound {
  private ctx: AudioContext | null = null;
  private failed = false;
  private out: GainNode | null = null;
  private crackle: GainNode | null = null;
  private hum: GainNode | null = null;
  volume = 0.45;

  private audio(): AudioContext | null {
    if (this.ctx || this.failed) return this.ctx;
    try {
      const AC = (window as unknown as { AudioContext?: typeof AudioContext }).AudioContext;
      if (!AC) { this.failed = true; return null; }
      const ctx = new AC();
      const out = ctx.createGain();
      out.gain.value = 0;
      out.connect(ctx.destination);
      // Crackle: looping white noise through a band-pass, its gain driven per frame.
      const buf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
      const data = buf.getChannelData(0);
      for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
      const noise = ctx.createBufferSource();
      noise.buffer = buf;
      noise.loop = true;
      const band = ctx.createBiquadFilter();
      band.type = "bandpass";
      band.frequency.value = 2600;
      band.Q.value = 0.7;
      const crackle = ctx.createGain();
      crackle.gain.value = 0;
      noise.connect(band).connect(crackle).connect(out);
      noise.start();
      // Hum: two detuned saws, low-passed.
      const low = ctx.createBiquadFilter();
      low.type = "lowpass";
      low.frequency.value = 420;
      const hum = ctx.createGain();
      hum.gain.value = 0;
      for (const f of [55, 56.3]) {
        const o = ctx.createOscillator();
        o.type = "sawtooth";
        o.frequency.value = f;
        o.connect(low);
        o.start();
      }
      low.connect(hum).connect(out);
      this.ctx = ctx;
      this.out = out;
      this.crackle = crackle;
      this.hum = hum;
      return ctx;
    } catch {
      this.failed = true;
      return null;
    }
  }

  /** Every frame: `level` 0..1 is how far the power is up. */
  update(level: number, held: boolean): void {
    if (!held && !this.ctx) return;
    const ctx = this.audio();
    if (!ctx || !this.out || !this.crackle || !this.hum) return;
    if (ctx.state === "suspended" && held) void ctx.resume();
    const t = ctx.currentTime;
    this.out.gain.setTargetAtTime(this.volume * level, t, 0.04);
    this.hum.gain.setTargetAtTime(0.35 * level, t, 0.05);
    // Jumps of loudness are the strikes.
    this.crackle.gain.setTargetAtTime(level * (0.25 + Math.random() * 0.9), t, 0.01);
  }

  dispose(): void {
    void this.ctx?.close();
    this.ctx = null;
  }
}
