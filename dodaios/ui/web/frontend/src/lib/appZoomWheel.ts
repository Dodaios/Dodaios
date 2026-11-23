/**
 * Ctrl + mouse wheel zooms the whole app window, one rung of the same ladder
 * Ctrl + `+` / `-` climbs (see ./appZoom): turned away from you it zooms in,
 * turned towards you it zooms out, the way every browser does it.
 *
 * ## Pressing the wheel instead of Ctrl
 *
 * Pressing the wheel button and then turning the wheel zooms too. People do
 * that in two ways, and both have to work:
 *
 * * they keep the wheel pressed while turning it: every wheel event then
 *   carries the wheel button in `buttons`;
 * * they press it, let go, and turn: the events carry nothing. So a press arms
 *   the wheel for zoom, and it stays armed while the wheel keeps zooming, until
 *   a short pause, a pointer move, another button or a key ends it.
 *
 * On Windows the press itself is cancelled. Otherwise Chromium starts its
 * middle-click auto-scroll on it, which scrolls the page under the pointer
 * instead of zooming it and keeps scrolling until the next click. Elsewhere
 * the press is left alone: on Linux it pastes the selection.
 *
 * ## Why the app claims the gesture itself
 *
 * The engine would zoom on Ctrl + wheel by itself, off the app's ladder, with
 * no size bubble, not remembered and undone by the next Ctrl + `+`. The
 * desktop shell's page script cancels that zoom only after the event has
 * passed through the page, so the app takes the gesture first and steps its
 * own ladder.
 *
 * ## Surfaces that zoom themselves
 *
 * A whiteboard, a run graph, a team canvas and the clip timeline zoom their own
 * content on Ctrl + wheel and use the wheel button for panning. They carry
 * `data-own-wheel-zoom`, and over them both gestures are theirs: the engine's
 * zoom is still cancelled, but the event goes on to the surface untouched and
 * the window keeps its size.
 *
 * ## Capture phase on the window
 *
 * Terminal panes stop every wheel event from leaving the pane, and xterm reads
 * the wheel for its own scrollback. Listening first, on the window, is the only
 * place that sees Ctrl + wheel over a terminal at all; stopping it there keeps
 * the pane from also scrolling while the window zooms.
 */
import type { AppZoomIntent } from "@/lib/appZoom";

/** Marks an element that zooms its own content on Ctrl + wheel. */
export const OWN_WHEEL_ZOOM_ATTRIBUTE = "data-own-wheel-zoom";

/** `MouseEvent.buttons` bit of the wheel button. */
const WHEEL_BUTTONS_BIT = 4;
/** `MouseEvent.button` of the wheel button. */
const WHEEL_BUTTON = 1;

/**
 * Wheel travel, in screen pixels, that makes one zoom step.
 *
 * A mouse notch reports about 100 px in one event and steps at once. A
 * touchpad pinch or a free-spinning wheel reports a stream of small deltas;
 * stepping on each would race through the whole ladder in one gesture.
 */
export const APP_ZOOM_WHEEL_STEP = 40;

/**
 * How long, in ms, the wheel stays on zoom after the wheel button was let go,
 * counted again from every zoom step. Long enough to move the finger from
 * pressing to turning; short enough that scrolling a moment later scrolls.
 */
export const WHEEL_PRESS_ZOOM_MS = 1500;

/** Pointer travel, in screen pixels, that ends the zoom a wheel press started. */
export const WHEEL_PRESS_SLOP_PX = 12;

export type AppZoomWheelEvent = Pick<WheelEvent, "deltaY" | "ctrlKey" | "metaKey" | "altKey" | "buttons">;

/**
 * Which zoom step this wheel event asks for, or null for ordinary scrolling.
 * `wheelPressed` is true while a wheel press armed the wheel for zoom.
 *
 * Ctrl alone, on every platform: a touchpad pinch arrives as a wheel event
 * with `ctrlKey` set and no key pressed. Cmd is not a zoom modifier for the
 * wheel anywhere, Win + wheel belongs to the Windows magnifier, and Alt is
 * refused because AltGr arrives as Ctrl + Alt on European keyboards.
 */
export function appZoomWheelIntent(
  event: AppZoomWheelEvent,
  wheelPressed = false,
): Exclude<AppZoomIntent, "reset"> | null {
  const ctrl = event.ctrlKey && !event.metaKey && !event.altKey;
  const wheelHeld = ((event.buttons ?? 0) & WHEEL_BUTTONS_BIT) !== 0;
  if (!ctrl && !wheelHeld && !wheelPressed) return null;
  if (event.deltaY === 0) return null;
  return event.deltaY < 0 ? "in" : "out";
}

export interface AppZoomWheelOptions {
  /**
   * May the app take the gesture from the engine? False where the app cannot
   * zoom the window itself (a shell whose engine has no zoom), so nothing is
   * swallowed there.
   */
  claims: () => boolean;
  /** Is whole-app zoom switched on? When off, Ctrl + wheel does nothing. */
  enabled: () => boolean;
  /**
   * The zoom level now. Wheel deltas are CSS pixels, which shrink as the
   * window zooms in; multiplying by the level measures the travel on the
   * screen, so one notch is one step at 50 % and at 300 % alike.
   */
  level: () => number;
  /** Take one step. The ladder's ends belong to the caller. */
  apply: (intent: Exclude<AppZoomIntent, "reset">) => void;
  /**
   * Cancel the wheel press, so the engine does not start auto-scrolling on
   * it. True on Windows; false on Linux, where the press pastes.
   */
  cancelPress: boolean;
  /** The clock, in ms. Tests pass their own. */
  now?: () => number;
}

function ownsWheelZoom(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(`[${OWN_WHEEL_ZOOM_ATTRIBUTE}]`) !== null;
}

/** Claim Ctrl + wheel and wheel-press + wheel on `target` (the window) as app zoom; returns the cleanup. */
export function installAppZoomWheel(
  target: Pick<EventTarget, "addEventListener" | "removeEventListener">,
  { claims, enabled, level, apply, cancelPress, now = () => performance.now() }: AppZoomWheelOptions,
): () => void {
  /** Signed travel not yet spent on a step. */
  let travel = 0;
  /** Where the wheel button went down, while it arms the wheel for zoom. */
  let press: { x: number; y: number } | null = null;
  /** The wheel button is down right now. */
  let held = false;
  /** After the button came up: the wheel zooms until this time. */
  let armedUntil = 0;

  const disarm = () => {
    press = null;
    held = false;
  };

  const armed = (): boolean => {
    if (press === null) return false;
    if (held || now() <= armedUntil) return true;
    disarm();
    return false;
  };

  const onMouseDown = (event: Event) => {
    const mouse = event as MouseEvent;
    if (mouse.button !== WHEEL_BUTTON) {
      disarm();
      return;
    }
    if (!claims() || !enabled() || ownsWheelZoom(mouse.target)) {
      disarm();
      return;
    }
    // Keeps Chromium from starting its middle-click auto-scroll (see above).
    // `auxclick` still fires, so a wheel click that closes a tab still does.
    if (cancelPress) mouse.preventDefault();
    press = { x: mouse.screenX, y: mouse.screenY };
    held = true;
    travel = 0;
  };

  const onMouseUp = (event: Event) => {
    if ((event as MouseEvent).button !== WHEEL_BUTTON || press === null) return;
    held = false;
    armedUntil = now() + WHEEL_PRESS_ZOOM_MS;
  };

  /** The button came up outside the window: no `mouseup` ever arrived. */
  const releaseMissed = (event: MouseEvent) => held && (event.buttons & WHEEL_BUTTONS_BIT) === 0;

  const onMouseMove = (event: Event) => {
    if (press === null) return;
    const mouse = event as MouseEvent;
    if (releaseMissed(mouse) || Math.hypot(mouse.screenX - press.x, mouse.screenY - press.y) > WHEEL_PRESS_SLOP_PX) {
      disarm();
    }
  };

  const onWheel = (event: Event) => {
    const wheel = event as WheelEvent;
    if (releaseMissed(wheel)) disarm();
    const pressed = armed();
    const intent = appZoomWheelIntent(wheel, pressed);
    if (intent === null || !claims()) {
      travel = 0;
      return;
    }
    // `passive: false` below is what makes this cancel anything: browsers
    // treat wheel listeners on the window as passive unless told otherwise.
    event.preventDefault();
    if (ownsWheelZoom(wheel.target)) {
      travel = 0;
      return;
    }
    event.stopPropagation();
    if (!enabled()) return;
    // Every notch of a released press keeps the wheel on zoom a while longer.
    if (pressed && !held) armedUntil = now() + WHEEL_PRESS_ZOOM_MS;
    // Lines and pages come from devices that already counted in notches.
    if (wheel.deltaMode !== 0) {
      travel = 0;
      apply(intent);
      return;
    }
    // Turning back mid-gesture drops what was banked the other way, so the
    // correction takes effect on the next notch.
    const delta = wheel.deltaY * Math.max(0.1, level());
    if (travel !== 0 && Math.sign(travel) !== Math.sign(delta)) travel = 0;
    travel += delta;
    if (Math.abs(travel) < APP_ZOOM_WHEEL_STEP) return;
    // One step per event, however far a coalesced burst travelled.
    travel = 0;
    apply(intent);
  };

  const capture = { capture: true } as const;
  target.addEventListener("wheel", onWheel, { capture: true, passive: false });
  target.addEventListener("mousedown", onMouseDown, capture);
  target.addEventListener("mouseup", onMouseUp, capture);
  target.addEventListener("mousemove", onMouseMove, { capture: true, passive: true });
  target.addEventListener("keydown", disarm, capture);
  target.addEventListener("blur", disarm);
  return () => {
    target.removeEventListener("wheel", onWheel, capture);
    target.removeEventListener("mousedown", onMouseDown, capture);
    target.removeEventListener("mouseup", onMouseUp, capture);
    target.removeEventListener("mousemove", onMouseMove, capture);
    target.removeEventListener("keydown", disarm, capture);
    target.removeEventListener("blur", disarm);
  };
}
