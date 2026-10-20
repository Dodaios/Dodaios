import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Terminal } from "@xterm/xterm";
import { useRef } from "react";
import {
  PaneScrollbar,
  SCROLLBAR_LINGER_MS,
  readPaneScrollState,
  sendWheelNotches,
} from "./PaneScrollbar";

type FakeOptions = {
  type?: "normal" | "alternate";
  baseY?: number;
  viewportY?: number;
  tracking?: "none" | "any" | "vt200" | "drag" | "x10";
  rows?: number;
};

function fakeTerminal(opts: FakeOptions = {}) {
  const element = document.createElement("div");
  const screenEl = document.createElement("div");
  screenEl.className = "xterm-screen";
  element.appendChild(screenEl);
  const wheels: WheelEvent[] = [];
  screenEl.addEventListener("wheel", (e) => wheels.push(e as WheelEvent));
  const listeners: Array<() => void> = [];
  const sub = (fn: () => void) => {
    listeners.push(fn);
    return { dispose: () => listeners.splice(listeners.indexOf(fn), 1) };
  };
  const active = {
    type: opts.type ?? "normal",
    baseY: opts.baseY ?? 0,
    viewportY: opts.viewportY ?? 0,
  };
  const term = {
    element,
    rows: opts.rows ?? 30,
    modes: { mouseTrackingMode: opts.tracking ?? "none" },
    buffer: { active, onBufferChange: sub },
    onScroll: sub,
    onWriteParsed: sub,
    onResize: sub,
    scrollLines: vi.fn((n: number) => {
      active.viewportY = Math.max(0, Math.min(active.baseY, active.viewportY + n));
    }),
    scrollPages: vi.fn(),
    scrollToLine: vi.fn((n: number) => {
      active.viewportY = n;
    }),
  };
  return { term, wheels, active, emit: () => listeners.slice().forEach((fn) => fn()) };
}

function Harness({ term }: { term: unknown }) {
  const termRef = useRef(term as Terminal | null);
  const regionRef = useRef<HTMLDivElement | null>(null);
  return (
    <div ref={regionRef} data-testid="region">
      <PaneScrollbar
        termRef={termRef}
        epoch={0}
        regionRef={regionRef}
        testId="bar"
        labels={{ bar: "Scroll the terminal", up: "Scroll up", down: "Scroll down" }}
      />
    </div>
  );
}

describe("readPaneScrollState", () => {
  it("is history on a normal buffer with scrollback", () => {
    const { term } = fakeTerminal({ baseY: 120, viewportY: 40 });
    expect(readPaneScrollState(term as unknown as Terminal)).toMatchObject({
      mode: "history",
      baseY: 120,
      viewportY: 40,
    });
  });

  it("is app on an alternate screen that reports the mouse (Claude Code, Codex)", () => {
    const { term } = fakeTerminal({ type: "alternate", tracking: "any" });
    expect(readPaneScrollState(term as unknown as Terminal).mode).toBe("app");
  });

  it("is none on an alternate screen without mouse reporting, where a wheel would type arrow keys", () => {
    const { term } = fakeTerminal({ type: "alternate", tracking: "none" });
    expect(readPaneScrollState(term as unknown as Terminal).mode).toBe("none");
  });

  it("is none on a normal buffer that has nothing above the screen", () => {
    const { term } = fakeTerminal({ baseY: 0 });
    expect(readPaneScrollState(term as unknown as Terminal).mode).toBe("none");
  });
});

describe("sendWheelNotches", () => {
  it("dispatches one line-mode wheel per notch on xterm's screen", () => {
    const { term, wheels } = fakeTerminal({ type: "alternate", tracking: "any" });
    expect(sendWheelNotches(term as unknown as Terminal, -1, 3)).toBe(3);
    expect(wheels).toHaveLength(3);
    expect(wheels.every((w) => w.deltaY === -1 && w.deltaMode === WheelEvent.DOM_DELTA_LINE)).toBe(true);
  });

  it("sends nothing once the CLI stops reporting the mouse", () => {
    const { term, wheels } = fakeTerminal({ type: "alternate", tracking: "none" });
    expect(sendWheelNotches(term as unknown as Terminal, 1, 4)).toBe(0);
    expect(wheels).toHaveLength(0);
  });
});

describe("PaneScrollbar", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("draws nothing while there is nothing to scroll", () => {
    const { term } = fakeTerminal();
    render(<Harness term={term} />);
    expect(screen.queryByRole("scrollbar")).toBeNull();
  });

  it("appears when the pane is scrolled and fades out after a pause", () => {
    const { term } = fakeTerminal({ baseY: 100, viewportY: 100 });
    render(<Harness term={term} />);
    const bar = screen.getByTestId("bar");
    expect(bar.dataset.visible).toBe("false");
    fireEvent.wheel(screen.getByTestId("region"), { deltaY: -100 });
    expect(bar.dataset.visible).toBe("true");
    act(() => {
      vi.advanceTimersByTime(SCROLLBAR_LINGER_MS + 10);
    });
    expect(bar.dataset.visible).toBe("false");
  });

  it("scrolls xterm's own history from the arrows in history mode", () => {
    const { term } = fakeTerminal({ baseY: 100, viewportY: 50 });
    render(<Harness term={term} />);
    fireEvent.pointerDown(screen.getByTestId("bar-up"), { button: 0 });
    fireEvent.pointerUp(window);
    expect(term.scrollLines).toHaveBeenCalledWith(-3);
    fireEvent.pointerDown(screen.getByTestId("bar-down"), { button: 0 });
    fireEvent.pointerUp(window);
    expect(term.scrollLines).toHaveBeenCalledWith(3);
  });

  it("keeps stepping while an arrow is held", () => {
    const { term } = fakeTerminal({ baseY: 1000, viewportY: 500 });
    render(<Harness term={term} />);
    fireEvent.pointerDown(screen.getByTestId("bar-up"), { button: 0 });
    act(() => {
      vi.advanceTimersByTime(320 + 60 * 5 + 5);
    });
    fireEvent.pointerUp(window);
    const calls = term.scrollLines.mock.calls.length;
    expect(calls).toBeGreaterThanOrEqual(6);
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(term.scrollLines.mock.calls.length).toBe(calls);
  });

  it("sends wheel notches to a full-screen CLI from the arrows in app mode", () => {
    const { term, wheels } = fakeTerminal({ type: "alternate", tracking: "any" });
    render(<Harness term={term} />);
    expect(screen.getByTestId("bar").dataset.mode).toBe("app");
    fireEvent.pointerDown(screen.getByTestId("bar-up"), { button: 0 });
    fireEvent.pointerUp(window);
    expect(wheels).toHaveLength(1);
    expect(wheels[0].deltaY).toBe(-1);
    fireEvent.pointerDown(screen.getByTestId("bar-down"), { button: 0 });
    fireEvent.pointerUp(window);
    expect(wheels).toHaveLength(2);
    expect(wheels[1].deltaY).toBe(1);
    expect(term.scrollLines).not.toHaveBeenCalled();
  });

  it("follows the terminal into app mode when the CLI takes the screen", () => {
    const { term, active, emit } = fakeTerminal();
    render(<Harness term={term} />);
    expect(screen.queryByRole("scrollbar")).toBeNull();
    active.type = "alternate";
    term.modes.mouseTrackingMode = "any";
    act(() => {
      emit();
      vi.advanceTimersByTime(20);
    });
    expect(screen.getByTestId("bar").dataset.mode).toBe("app");
  });
});
