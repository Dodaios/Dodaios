/**
 * Voice notes: record with the phone's microphone, decode in the browser and
 * resample to the 16 kHz mono int16 PCM the computer's recognizer takes. The
 * computer never has to decode a phone codec, and nothing leaves the phone
 * until the person stops the recording.
 */

export interface Recorder {
  stop(): Promise<Blob>;
  cancel(): void;
}

export function canRecord(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    Boolean(navigator.mediaDevices?.getUserMedia)
  );
}

export async function startRecording(): Promise<Recorder> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const recorder = new MediaRecorder(stream);
  const chunks: BlobPart[] = [];
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  });
  const stopped = new Promise<Blob>((resolve) => {
    recorder.addEventListener("stop", () => {
      stream.getTracks().forEach((track) => track.stop());
      resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
    });
  });
  recorder.start();
  return {
    stop: () => {
      if (recorder.state !== "inactive") recorder.stop();
      return stopped;
    },
    cancel: () => {
      if (recorder.state !== "inactive") recorder.stop();
      stream.getTracks().forEach((track) => track.stop());
    },
  };
}

/** Float samples in [-1, 1] → little-endian int16 bytes. */
export function floatToPcm16(samples: Float32Array): ArrayBuffer {
  const out = new DataView(new ArrayBuffer(samples.length * 2));
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    out.setInt16(i * 2, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
  }
  return out.buffer;
}

/** Linear resampling to `targetRate`; good enough for speech, dependency-free. */
export function resample(samples: Float32Array, sourceRate: number, targetRate = 16_000): Float32Array {
  if (sourceRate === targetRate) return samples;
  const ratio = sourceRate / targetRate;
  const length = Math.max(1, Math.floor(samples.length / ratio));
  const out = new Float32Array(length);
  for (let i = 0; i < length; i += 1) {
    const position = i * ratio;
    const index = Math.floor(position);
    const next = Math.min(index + 1, samples.length - 1);
    const frac = position - index;
    out[i] = samples[index] * (1 - frac) + samples[next] * frac;
  }
  return out;
}

/** Mix an AudioBuffer down to one channel. */
export function mono(buffer: { numberOfChannels: number; length: number; getChannelData(i: number): Float32Array }): Float32Array {
  if (buffer.numberOfChannels === 1) return buffer.getChannelData(0);
  const out = new Float32Array(buffer.length);
  for (let c = 0; c < buffer.numberOfChannels; c += 1) {
    const channel = buffer.getChannelData(c);
    for (let i = 0; i < out.length; i += 1) out[i] += channel[i] / buffer.numberOfChannels;
  }
  return out;
}

/** A recorded blob → 16 kHz mono int16 PCM, decoded by the phone's browser. */
export async function blobToPcm16k(blob: Blob): Promise<ArrayBuffer> {
  const context = new AudioContext();
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    return floatToPcm16(resample(mono(decoded), decoded.sampleRate, 16_000));
  } finally {
    await context.close().catch(() => undefined);
  }
}
