/**
 * Keys pressed while the commander has taken over a desk terminal, as the
 * bytes a terminal sends for them (xterm's defaults: Enter is CR, Backspace
 * DEL, arrows and Home/End in normal cursor mode). Pure.
 */
export interface KeyLike {
  key: string;
  ctrlKey: boolean;
  altKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}

const NAMED: Readonly<Record<string, string>> = {
  Enter: "\r",
  Backspace: "\x7f",
  Tab: "\t",
  Escape: "\x1b",
  ArrowUp: "\x1b[A",
  ArrowDown: "\x1b[B",
  ArrowRight: "\x1b[C",
  ArrowLeft: "\x1b[D",
  Home: "\x1b[H",
  End: "\x1b[F",
  Delete: "\x1b[3~",
  PageUp: "\x1b[5~",
  PageDown: "\x1b[6~",
  Insert: "\x1b[2~",
};

/** The terminal input for one key press, or null for a key that sends nothing (a lone modifier, F-keys). */
export function keyToTerminalData(e: KeyLike): string | null {
  if (e.metaKey) return null;
  if (e.key === "Tab" && e.shiftKey) return "\x1b[Z";
  const named = NAMED[e.key];
  if (named) return e.altKey ? `\x1b${named}` : named;
  if (e.key.length !== 1) return null;
  if (e.ctrlKey && !e.altKey) {
    const c = e.key.toLowerCase();
    if (c >= "a" && c <= "z") return String.fromCharCode(c.charCodeAt(0) - 96);
    if (c === " " || c === "@" || c === "2") return "\x00";
    if (c === "[") return "\x1b";
    if (c === "\\") return "\x1c";
    if (c === "]") return "\x1d";
    return null;
  }
  return e.altKey ? `\x1b${e.key}` : e.key;
}

/** Ctrl+Q leaves the terminal (Escape belongs to the agent: it interrupts it). */
export function leavesTakeover(e: KeyLike): boolean {
  return e.ctrlKey && !e.altKey && !e.metaKey && e.key.toLowerCase() === "q";
}
