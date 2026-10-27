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
 * | 2, 3, V      | over the shoulder / through the eyes      |
 * | Wheel        | in: through the eyes; out: the shoulder   |
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

  /**
   * The mouse buttons held right now, as a pointer event's `buttons` mask
   * (1 left, 2 right). Browsers send `pointerdown` only for the first button
   * of a chord and `pointerup` only for the last; a second button arrives as
   * a `pointermove` with a changed mask, so the mask is the truth. `presses`
   * false applies only releases (a move from outside the surface).
   */
  mouseButtons(buttons: number, presses = true): void {
    const fire = (buttons & 1) !== 0;
    const ads = (buttons & 2) !== 0;
    if (presses || !fire) this.fire = fire;
    if (presses || !ads) this.ads = ads;
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
  /** A key that may switch the view (third / first person); returns whether it did. */
  view?: (code: string) => boolean;
  /** The wheel turned while the match runs: in (true) goes through the eyes, out (false) back over the shoulder. */
  zoom?: (inward: boolean) => void;
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
    if (!e.repeat && cb.view?.(e.code)) {
      e.preventDefault();
      e.stopImmediatePropagation();
      return;
    }
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
    input.mouseButtons(e.buttons);
    e.preventDefault();
  };
  // A second button pressed (or one let go) while another is held comes only as a pointermove with a new mask.
  const chord = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    const onSurface = locked() || el.contains(e.target as Node);
    input.mouseButtons(e.buttons, onSurface && cb.live());
  };
  const up = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    input.mouseButtons(e.buttons, false);
  };
  // Mouse movement anywhere turns the aim while the pointer is locked to the surface; unlocked, over the surface only.
  const move = (e: MouseEvent) => {
    if (!cb.live()) return;
    if (!locked() && !el.contains(e.target as Node)) return;
    cb.look(e.movementX || 0, e.movementY || 0);
  };
  const menu = (e: Event) => e.preventDefault();
  const wheel = (e: WheelEvent) => {
    e.preventDefault();
    if (!cb.live() || e.deltaY === 0 || e.ctrlKey) return;
    cb.zoom?.(e.deltaY < 0);
  };
  el.addEventListener("wheel", wheel, { passive: false });
  window.addEventListener("keydown", keyDown, true);
  window.addEventListener("keyup", keyUp, true);
  window.addEventListener("blur", blur);
  el.addEventListener("pointerdown", down);
  window.addEventListener("pointermove", chord);
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
  document.addEventListener("mousemove", move);
  el.addEventListener("contextmenu", menu);
  return () => {
    window.removeEventListener("keydown", keyDown, true);
    window.removeEventListener("keyup", keyUp, true);
    window.removeEventListener("blur", blur);
    el.removeEventListener("pointerdown", down);
    window.removeEventListener("pointermove", chord);
    window.removeEventListener("pointerup", up);
    window.removeEventListener("pointercancel", up);
    document.removeEventListener("mousemove", move);
    el.removeEventListener("contextmenu", menu);
    el.removeEventListener("wheel", wheel);
    input.clear();
  };
}
