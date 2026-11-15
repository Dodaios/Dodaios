import { createRef } from "react";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BrowserCanvas, WHEEL_BATCH_MS } from "./BrowserCanvas";
import type { BrowserViewState } from "./useBrowserView";

const state: BrowserViewState = {
  connected: true, ready: true, fullWindow: false, extendedInput: true, previewPaused: false,
  loginAvailable: false, loginMode: false, loginReady: false, manual: true, running: false,
  controlPending: false, url: "https://example.org/", tabs: [], target: "", error: "",
};

function mount(control = vi.fn(), scrollOnHover = false) {
  const ref = createRef<HTMLCanvasElement>();
  const view = render(
    <BrowserCanvas canvas={ref} state={state} control={control} live ariaLabel="Page" scrollOnHover={scrollOnHover} />,
  );
  const canvas = ref.current as HTMLCanvasElement;
  vi.spyOn(canvas, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 1280, height: 800 } as DOMRect);
  return { canvas, control, view };
}

const scrolls = (control: ReturnType<typeof vi.fn>) => control.mock.calls.filter(([op]) => op === "scroll");

beforeEach(() => vi.useFakeTimers());
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("BrowserCanvas wheel", () => {
  it("sends the first wheel event at once and sums what follows into one message", () => {
    const { canvas, control } = mount();
    canvas.focus();
    fireEvent.wheel(canvas, { clientX: 100, clientY: 200, deltaY: 12 });
    expect(scrolls(control)).toEqual([["scroll", { x: 100, y: 200, dx: 0, dy: 12 }]]);
    // A trackpad fires several events inside one batch time.
    for (const y of [210, 220, 230, 240]) fireEvent.wheel(canvas, { clientX: 100, clientY: y, deltaX: 1, deltaY: 10 });
    expect(scrolls(control)).toHaveLength(1);
    vi.advanceTimersByTime(WHEEL_BATCH_MS);
    expect(scrolls(control)).toHaveLength(2);
    // The whole distance, at the place of the newest event.
    expect(scrolls(control)[1]).toEqual(["scroll", { x: 100, y: 240, dx: 4, dy: 40 }]);
    vi.advanceTimersByTime(WHEEL_BATCH_MS * 4);
    expect(scrolls(control)).toHaveLength(2);
  });

  it("keeps one message inside what the server accepts", () => {
    const { canvas, control } = mount();
    canvas.focus();
    fireEvent.wheel(canvas, { clientX: 5, clientY: 5, deltaY: 1 });
    for (let n = 0; n < 3; n++) fireEvent.wheel(canvas, { clientX: 5, clientY: 5, deltaY: -9000 });
    vi.advanceTimersByTime(WHEEL_BATCH_MS);
    expect(scrolls(control)[1]).toEqual(["scroll", { x: 5, y: 5, dx: 0, dy: -10000 }]);
  });

  it("needs a click on the page first where the view is only a preview", () => {
    const { canvas, control } = mount();
    fireEvent.wheel(canvas, { clientX: 100, clientY: 200, deltaY: 12 });
    vi.advanceTimersByTime(WHEEL_BATCH_MS);
    expect(scrolls(control)).toEqual([]);
  });

  it("scrolls the page under the pointer where the view is a browser", () => {
    const { canvas, control } = mount(vi.fn(), true);
    expect(document.activeElement).not.toBe(canvas);
    fireEvent.wheel(canvas, { clientX: 100, clientY: 200, deltaY: 12 });
    expect(scrolls(control)).toEqual([["scroll", { x: 100, y: 200, dx: 0, dy: 12 }]]);
  });

  it("sends nothing after the view is gone", () => {
    const { canvas, control, view } = mount();
    canvas.focus();
    fireEvent.wheel(canvas, { clientX: 1, clientY: 1, deltaY: 5 });
    fireEvent.wheel(canvas, { clientX: 1, clientY: 1, deltaY: 5 });
    view.unmount();
    vi.advanceTimersByTime(WHEEL_BATCH_MS * 4);
    expect(scrolls(control)).toHaveLength(1);
  });
});
