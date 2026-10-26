/** The work inspector's width: chosen by dragging its edge, kept per viewer. */

export const INSPECTOR_MIN = 320;
export const INSPECTOR_MAX = 760;
export const INSPECTOR_DEFAULT = 420;
/** The conversation keeps at least this much beside the open inspector, or the inspector floats over it. */
export const CHAT_KEEP = 440;

const KEY = "dodaios.runView.inspectorWidth";

export function clampWidth(width: number, room = Number.POSITIVE_INFINITY): number {
  const max = Math.max(INSPECTOR_MIN, Math.min(INSPECTOR_MAX, room));
  return Math.round(Math.min(max, Math.max(INSPECTOR_MIN, width)));
}

export function readInspectorWidth(): number {
  try {
    const raw = Number(window.localStorage.getItem(KEY));
    return Number.isFinite(raw) && raw > 0 ? clampWidth(raw) : INSPECTOR_DEFAULT;
  } catch {
    return INSPECTOR_DEFAULT;
  }
}

export function writeInspectorWidth(width: number): void {
  try {
    window.localStorage.setItem(KEY, String(clampWidth(width)));
  } catch {
    // Private windows and blocked storage keep the width for this session only.
  }
}

/** Side by side when the pane leaves the chat its room; otherwise it floats over the chat. */
export function inspectorDocked(containerWidth: number, width: number): boolean {
  return containerWidth - width >= CHAT_KEEP;
}
