/**
 * The seam between the live build and the Clips editor.
 *
 * While an agent places a clip, the live reveal (`live/adapters/motion.ts`)
 * asks the editor to move its playhead onto that clip by dispatching this
 * event from the clip's element. It bubbles to the editor, which moves the
 * playhead unless the person is playing the clip.
 */
export const CLIP_LIVE_SEEK = "dodaios-clip-live-seek";

export interface ClipLiveSeekDetail {
  /** The time, in seconds, the playhead moves to. */
  t: number;
}
