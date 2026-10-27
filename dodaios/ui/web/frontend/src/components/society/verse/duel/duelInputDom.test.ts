// @vitest-environment jsdom
/**
 * The duel's mouse binding on a real DOM surface. Browsers send
 * `pointerdown` only for the first button of a chord and `pointerup` only
 * for the last one; a button pressed or let go while another is held comes
 * as a `pointermove` with a new `buttons` mask. Holding the sights (right
 * button) and then pulling the trigger (left button) must fire, in either
 * order, and the right button never opens a menu.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attachDuelInput, DuelInput } from "./duelInput";

const LEFT = 1;
const RIGHT = 2;

describe("duel mouse binding", () => {
  let el: HTMLDivElement;
  let lockedTo: Element | null = null;
  let detach: () => void = () => {};
  let input: DuelInput;
  const cb = () => ({ look: vi.fn(), escape: vi.fn(), relock: vi.fn(), live: () => true, view: vi.fn(() => false), zoom: vi.fn() });

  beforeEach(() => {
    el = document.createElement("div");
    document.body.appendChild(el);
    Object.defineProperty(document, "pointerLockElement", { configurable: true, get: () => lockedTo });
    lockedTo = el;
    input = new DuelInput();
  });
  afterEach(() => {
    detach();
    el.remove();
    lockedTo = null;
  });

  /** A mouse pointer event as Chrome sends it: `button` is what changed, `buttons` what is held after it. */
  const send = (type: string, button: number, buttons: number) => {
    const e = new MouseEvent(type, { bubbles: true, cancelable: true, button, buttons });
    Object.defineProperty(e, "pointerType", { value: "mouse" });
    el.dispatchEvent(e);
    return e;
  };
  const state = () => {
    const c = input.control(0, 0);
    return { fire: c.fire, ads: c.ads };
  };

  it("fires with the sights held: right down, then left (the left press comes as a pointermove)", () => {
    detach = attachDuelInput(el, input, cb());
    send("pointerdown", 2, RIGHT);
    expect(state()).toEqual({ fire: false, ads: true });
    send("pointermove", 0, RIGHT | LEFT);
    expect(state()).toEqual({ fire: true, ads: true });
    send("pointermove", 0, RIGHT);
    expect(state()).toEqual({ fire: false, ads: true });
    send("pointerup", 2, 0);
    expect(state()).toEqual({ fire: false, ads: false });
  });

  it("aims while firing: left down, then right; letting the right go mid-burst stops aiming only", () => {
    detach = attachDuelInput(el, input, cb());
    send("pointerdown", 0, LEFT);
    send("pointermove", 2, LEFT | RIGHT);
    expect(state()).toEqual({ fire: true, ads: true });
    send("pointermove", 2, LEFT);
    expect(state()).toEqual({ fire: true, ads: false });
    send("pointerup", 0, 0);
    expect(state()).toEqual({ fire: false, ads: false });
  });

  it("lets the trigger go when the left button is released before the right", () => {
    detach = attachDuelInput(el, input, cb());
    send("pointerdown", 0, LEFT);
    send("pointermove", 2, LEFT | RIGHT);
    send("pointermove", 0, RIGHT);
    expect(state()).toEqual({ fire: false, ads: true });
    send("pointerup", 2, 0);
    expect(state()).toEqual({ fire: false, ads: false });
  });

  it("presses nothing while the match does not take input, but still lets go", () => {
    let live = true;
    detach = attachDuelInput(el, input, { ...cb(), live: () => live });
    send("pointerdown", 2, RIGHT);
    live = false;
    send("pointermove", 0, RIGHT | LEFT);
    expect(state().fire).toBe(false);
    send("pointerup", 2, 0);
    expect(state().ads).toBe(false);
  });

  it("never opens a context menu on the surface", () => {
    detach = attachDuelInput(el, input, cb());
    const e = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2 });
    el.dispatchEvent(e);
    expect(e.defaultPrevented).toBe(true);
  });

  it("the wheel hands over between the shoulder and the eyes, and fire keeps working after it", () => {
    const callbacks = cb();
    detach = attachDuelInput(el, input, callbacks);
    const wheel = new WheelEvent("wheel", { deltaY: -100, cancelable: true });
    el.dispatchEvent(wheel);
    expect(wheel.defaultPrevented).toBe(true);
    expect(callbacks.zoom).toHaveBeenCalledWith(true);
    el.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, cancelable: true }));
    expect(callbacks.zoom).toHaveBeenLastCalledWith(false);
    send("pointerdown", 2, RIGHT);
    send("pointermove", 0, RIGHT | LEFT);
    expect(state()).toEqual({ fire: true, ads: true });
  });
});
