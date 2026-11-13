import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { AgentCursor } from "./AgentCursor";
import { glideDurationMs } from "./agentCursorMotion";
import type { BrowserPointerState } from "./browserPointerState";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function installFrame() {
  let now = 5000;
  const frames: FrameRequestCallback[] = [];
  vi.spyOn(performance, "now").mockImplementation(() => now);
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.push(callback);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    disconnect() {}
  });
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(640);
  vi.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(480);
  return {
    frames,
    at(time: number) { now = time; },
  };
}

const here = (over: Partial<BrowserPointerState> = {}): BrowserPointerState => ({
  x: 100, y: 200, width: 1280, height: 800, click_id: 1, click_x: 100, click_y: 200, ...over,
});

test("the arrow sits on the pictured point and marks a click that is already there", () => {
  installFrame();
  render(<AgentCursor pointer={here()} />);
  const arrow = screen.getByTestId("browser-agent-pointer");
  expect(arrow.style.transform).toBe("translate3d(50px, 140px, 0)");
  expect(screen.getAllByTestId("browser-click-mark")).toHaveLength(1);
  expect(arrow.querySelector("path")?.getAttribute("fill")).toBe("#FFFFFF");
  expect(arrow.querySelector("path")?.getAttribute("stroke")).toBe("#0A0A0A");
});

test("the arrow glides to the next click and only then presses", () => {
  const clock = installFrame();
  const { rerender } = render(<AgentCursor pointer={here()} />);
  rerender(<AgentCursor pointer={here({ x: 600, click_id: 2, click_x: 600 })} />);
  const arrow = screen.getByTestId("browser-agent-pointer");
  expect(arrow.dataset.x).toBe("100");
  expect(screen.getAllByTestId("browser-click-mark")).toHaveLength(1);
  // Timed in page pixels (500 across), whatever size the view is drawn at.
  const duration = glideDurationMs(500);
  act(() => { clock.frames.at(-1)?.(5000 + duration / 2); });
  expect(Number(arrow.dataset.x)).toBeCloseTo(350, 1);
  expect(Number(arrow.dataset.y)).toBeLessThan(200);
  act(() => { clock.frames.at(-1)?.(5000 + duration); });
  expect(Number(arrow.dataset.x)).toBeCloseTo(600, 1);
  expect(screen.getAllByTestId("browser-click-mark")).toHaveLength(2);
});

test("reduced motion puts the arrow on the button without a glide", () => {
  installFrame();
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query.includes("reduce"),
    media: query,
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() { return false; },
  }));
  const { rerender } = render(<AgentCursor pointer={here()} />);
  rerender(<AgentCursor pointer={here({ x: 600, click_id: 2, click_x: 600 })} />);
  expect(screen.getByTestId("browser-agent-pointer").dataset.x).toBe("600");
  expect(screen.getAllByTestId("browser-click-mark")).toHaveLength(2);
});

test("the arrow leaves when the agent is no longer driving", () => {
  installFrame();
  const { rerender } = render(<AgentCursor pointer={here()} />);
  rerender(<AgentCursor />);
  expect(screen.queryByTestId("browser-agent-pointer")).toBeNull();
});

test("the arrow carries the driver's name when it is given one", () => {
  installFrame();
  render(<AgentCursor pointer={here()} label="Dodaios" />);
  expect(screen.getByTestId("browser-agent-pointer-label").textContent).toBe("Dodaios");
});
