/**
 * The duel's controls (docs/verse/combat.md, "Input mapping"): keys and
 * mouse buttons held or pressed during a match, turned into the combat
 * core's ControlState once per frame.
 *
 * | Key          | Control                                   |
 * |--------------|-------------------------------------------|
 * | W A S D      | move (strafe / forward, in the aim frame) |
 * | Shift (hold) | sprint                                    |
 * | Left button  | fire (hold for full auto)                 |
 * | Right button | aim down the sights (hold)                |
 * | Q (hold)     | energy shield                             |
 * | Space        | dodge roll (in the move direction)        |
 * | R            | vent; again inside the window: perfect    |
 * | Esc          | pause (pointer released); again: leave    |
 *
 * Presses (dodge, vent) are latched until the next `control()` call reads
 * them, so a tap shorter than a frame is never lost (the client latches
 * them again until its next tick). Pure apart from its own state; the DOM
 * binding is `attachDuelInput`.
 */
import { idleControl, type ControlState } from "../combat/input";

/** Key codes per control. Arrow keys move too, for people who prefer them. */
export const DUEL_KEYS = {
  forward: ["KeyW", "ArrowUp"],
  back: ["KeyS", "ArrowDown"],
  left: ["KeyA", "ArrowLeft"],
  right: ["KeyD", "ArrowRight"],
  sprint: ["ShiftLeft", "ShiftRight"],
  shield: ["KeyQ"],
  dodge: ["Space"],
  vent: ["KeyR"],
} as const;

type Held = "forward" | "back" | "left" | "right" | "sprint" | "shield";
type Pressed = "dodge" | "vent";

const HELD: readonly Held[] = ["forward", "back", "left", "right", "sprint", "shield"];
const PRESSED: readonly Pressed[] = ["dodge", "vent"];

function controlOf(code: string): Held | Pressed | null {
  for (const name of [...HELD, ...PRESSED]) if ((DUEL_KEYS[name] as readonly string[]).includes(code)) return name;
  return null;
}

/** The key is one the duel uses (the stage must not also act on it). */
export function isDuelKey(code: string): boolean {
  return controlOf(code) !== null;
}

export class DuelInput {
  private readonly held = new Set<string>();
  private fire = false;
  private ads = false;
  private latched = { dodge: false, vent: false };

  /** A key went down; returns whether the duel uses it. Auto-repeat never presses twice. */
  keyDown(code: string, repeat = false): boolean {
    const c = controlOf(code);
    if (!c) return false;
    if (c === "dodge" || c === "vent") {
      if (!repeat) this.latched[c] = true;
      return true;
    }
    this.held.add(code);
    return true;
  }

  keyUp(code: string): boolean {
    if (!controlOf(code)) return false;
    this.held.delete(code);
    return true;
  }

  /** Mouse buttons: 0 fires, 2 aims down the sights. */
  mouseDown(button: number): void {
    if (button === 0) this.fire = true;
    else if (button === 2) this.ads = true;
  }

  mouseUp(button: number): void {
    if (button === 0) this.fire = false;
    else if (button === 2) this.ads = false;
  }

  /** Everything let go (the window lost focus, the match paused). Latched presses go too. */
  clear(): void {
    this.held.clear();
    this.fire = false;
    this.ads = false;
    this.latched = { dodge: false, vent: false };
  }

  private down(name: Held): boolean {
    for (const code of DUEL_KEYS[name]) if (this.held.has(code)) return true;
    return false;
  }

  /** Movement as the core wants it: x strafes right, y forward, each -1..1 (diagonals are clamped by the core). */
  move(): { x: number; y: number } {
    const x = (this.down("right") ? 1 : 0) - (this.down("left") ? 1 : 0);
    const y = (this.down("forward") ? 1 : 0) - (this.down("back") ? 1 : 0);
    return { x, y };
  }

  /**
   * This frame's control state at the given aim (radians, yaw 0 faces +Z,
   * pitch positive up). Reading it consumes the latched presses.
   */
  control(yaw: number, pitch: number, out?: ControlState): ControlState {
    const c = out ?? idleControl();
    const m = this.move();
    c.moveX = m.x;
    c.moveY = m.y;
    c.yaw = yaw;
    c.pitch = pitch;
    c.fire = this.fire;
    c.ads = this.ads;
    c.shield = this.down("shield");
    c.sprint = this.down("sprint") && m.y > 0;
    c.dodge = this.latched.dodge;
    c.vent = this.latched.vent;
    c.forfeit = false;
    this.latched.dodge = false;
    this.latched.vent = false;
    return c;
  }
}

export interface DuelInputCallbacks {
  /** Mouse movement while the match runs (CSS px; pointer-lock deltas when locked). */
  look: (dx: number, dy: number) => void;
  /** Escape (when the browser delivers it). */
  escape: () => void;
  /** The surface was clicked while the pointer is not locked (resume aiming). */
  relock: () => void;
  /** The duel takes input now (running, not paused or over). */
  live: () => boolean;
}

/**
 * Binds the keyboard (window) and the mouse (the stage surface) to a
 * DuelInput while a duel is on. Keys the duel uses never reach the stage's
 * own handlers (they would walk the commander). The context menu is off on
 * the surface, so the right button can aim.
 */
export function attachDuelInput(el: HTMLElement, input: DuelInput, cb: DuelInputCallbacks): () => void {
  const typing = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement | null;
    return !!t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
  };
  const keyDown = (e: KeyboardEvent) => {
    if (typing(e)) return;
    if (e.code === "Escape") {
      e.preventDefault();
      e.stopImmediatePropagation();
      cb.escape();
      return;
    }
    if (!cb.live()) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (input.keyDown(e.code, e.repeat)) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  };
  const keyUp = (e: KeyboardEvent) => {
    if (input.keyUp(e.code)) e.stopImmediatePropagation();
  };
  const blur = () => input.clear();
  const locked = () => document.pointerLockElement === el;
  const down = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    if (!cb.live()) return;
    if (!locked()) cb.relock();
    input.mouseDown(e.button);
    e.preventDefault();
  };
  const up = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    input.mouseUp(e.button);
  };
  // Mouse movement anywhere turns the aim while the pointer is locked to the surface; unlocked, over the surface only.
  const move = (e: MouseEvent) => {
    if (!cb.live()) return;
    if (!locked() && !el.contains(e.target as Node)) return;
    cb.look(e.movementX || 0, e.movementY || 0);
  };
  const menu = (e: Event) => e.preventDefault();
  window.addEventListener("keydown", keyDown, true);
  window.addEventListener("keyup", keyUp, true);
  window.addEventListener("blur", blur);
  el.addEventListener("pointerdown", down);
  window.addEventListener("pointerup", up);
  document.addEventListener("mousemove", move);
  el.addEventListener("contextmenu", menu);
  return () => {
    window.removeEventListener("keydown", keyDown, true);
    window.removeEventListener("keyup", keyUp, true);
    window.removeEventListener("blur", blur);
    el.removeEventListener("pointerdown", down);
    window.removeEventListener("pointerup", up);
    document.removeEventListener("mousemove", move);
    el.removeEventListener("contextmenu", menu);
    input.clear();
  };
}
