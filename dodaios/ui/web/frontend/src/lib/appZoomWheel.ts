/**
 * Ctrl + mouse wheel zooms the whole app window, one rung of the same ladder
 * Ctrl + `+` / `-` climbs (see ./appZoom): turned away from you it zooms in,
 * turned towards you it zooms out, the way every browser does it.
 *
 * Turning the wheel while it is held down counts too, for people who reach
 * for the wheel button rather than for Ctrl.
 *
 * ## Why the app claims the gesture instead of leaving it to the engine
 *
 * WebView2 zooms on Ctrl + wheel by itself. That zoom bypasses everything the
 * app keeps about zoom: it is not on the ladder, shows no size bubble, is not
 * remembered, does not reach the other windows, and the next Ctrl + `+` jumps
 * back to the stored level. So the engine's default is cancelled for every
 * Ctrl + wheel and the step goes through the app's own path instead.
 *
 * ## Surfaces that zoom themselves
 *
 * A whiteboard, a run graph, a team canvas and the clip timeline zoom their own
 * content on Ctrl + wheel. They carry `data-own-wheel-zoom`, and over them the
 * gesture is theirs: the engine's zoom is still cancelled, but the event goes on
 * to the surface untouched and the window keeps its size.
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

/** `WheelEvent.buttons` bit of the wheel button. */
const WHEEL_BUTTON = 4;

/**
 * Wheel travel, in screen pixels, that makes one zoom step.
 *
 * A mouse notch reports about 100 px in one event and steps at once. A
 * touchpad pinch or a free-spinning wheel reports a stream of small deltas;
 * stepping on each would race through the whole ladder in one gesture.
 */
export const APP_ZOOM_WHEEL_STEP = 40;

export type AppZoomWheelEvent = Pick<WheelEvent, "deltaY" | "ctrlKey" | "metaKey" | "altKey" | "buttons">;

/**
 * Which zoom step this wheel event asks for, or null for ordinary scrolling.
 *
 * Ctrl alone, on every platform: a touchpad pinch arrives as a wheel event
 * with `ctrlKey` set and no key pressed. Cmd is not a zoom modifier for the
 * wheel anywhere, Win + wheel belongs to the Windows magnifier, and Alt is
 * refused because AltGr arrives as Ctrl + Alt on European keyboards.
 */
export function appZoomWheelIntent(event: AppZoomWheelEvent): Exclude<AppZoomIntent, "reset"> | null {
  const ctrl = event.ctrlKey && !event.metaKey && !event.altKey;
  const wheelHeld = ((event.buttons ?? 0) & WHEEL_BUTTON) !== 0;
  if (!ctrl && !wheelHeld) return null;
  if (event.deltaY === 0) return null;
  return event.deltaY < 0 ? "in" : "out";
}

export interface AppZoomWheelOptions {
  /**
   * May the engine's own Ctrl + wheel zoom be cancelled? False where the app
   * cannot zoom the window itself (a shell whose engine has no zoom), so the
   * gesture is not swallowed there.
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
}

/** Claim Ctrl + wheel on `target` (the window) as app zoom; returns the cleanup. */
export function installAppZoomWheel(
  target: Pick<EventTarget, "addEventListener" | "removeEventListener">,
  { claims, enabled, level, apply }: AppZoomWheelOptions,
): () => void {
  /** Signed travel not yet spent on a step. */
  let travel = 0;

  const onWheel = (event: Event) => {
    const wheel = event as WheelEvent;
    const intent = appZoomWheelIntent(wheel);
    if (intent === null || !claims()) {
      travel = 0;
      return;
    }
    // `passive: false` below is what makes this cancel anything: browsers
    // treat wheel listeners on the window as passive unless told otherwise.
    event.preventDefault();
    const over = wheel.target;
    if (over instanceof Element && over.closest(`[${OWN_WHEEL_ZOOM_ATTRIBUTE}]`)) {
      travel = 0;
      return;
    }
    event.stopPropagation();
    if (!enabled()) return;
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

  target.addEventListener("wheel", onWheel, { capture: true, passive: false });
  return () => target.removeEventListener("wheel", onWheel, { capture: true });
}
