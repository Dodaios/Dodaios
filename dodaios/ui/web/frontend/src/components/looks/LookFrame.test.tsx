import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LookFrame, READY_TIMEOUT_MS } from "@/components/looks/LookFrame";
import type { Look } from "@/lib/looksApi";

const LOOK: Look = {
  id: "pulse-ring",
  name: "Pulse Ring",
  description: "",
  author: "Dodaios",
  version: "1.0.0",
  license: "Apache-2.0",
  attribution: "",
  homepage: "",
  builtin: true,
  preview_url: "/api/looks/pulse-ring/preview",
  frame_url: "/looks-frame/pulse-ring/index.html",
};

function frameOf(container: HTMLElement): HTMLIFrameElement {
  return container.querySelector("iframe") as HTMLIFrameElement;
}

describe("LookFrame", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("sandboxes the look: scripts only, no same-origin, no pointer input", () => {
    const { container } = render(<LookFrame look={LOOK} state="idle" onFail={() => {}} />);
    const frame = frameOf(container);
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("src")).toBe(LOOK.frame_url);
    expect(frame.className).toContain("pointer-events-none");
  });

  it("falls back when the look never says ready", () => {
    const onFail = vi.fn();
    render(<LookFrame look={LOOK} state="idle" onFail={onFail} />);
    act(() => {
      vi.advanceTimersByTime(READY_TIMEOUT_MS + 10);
    });
    expect(onFail).toHaveBeenCalledOnce();
  });

  it("answers ready with init and then forwards state changes", () => {
    const onFail = vi.fn();
    const { container, rerender } = render(
      <LookFrame look={LOOK} state="idle" onFail={onFail} />,
    );
    const target = frameOf(container).contentWindow as Window;
    const posted = vi.spyOn(target, "postMessage");

    act(() => {
      window.dispatchEvent(
        new MessageEvent("message", { data: { type: "look:ready" }, source: target }),
      );
    });
    expect(posted).toHaveBeenCalledWith(
      expect.objectContaining({ type: "look:init", state: "idle" }),
      "*",
    );

    rerender(<LookFrame look={LOOK} state="listening" onFail={onFail} />);
    expect(posted).toHaveBeenCalledWith({ type: "look:state", state: "listening" }, "*");

    act(() => {
      vi.advanceTimersByTime(READY_TIMEOUT_MS + 10);
    });
    expect(onFail).not.toHaveBeenCalled();
  });

  it("ignores ready messages from anywhere but its own frame", () => {
    const onFail = vi.fn();
    render(<LookFrame look={LOOK} state="idle" onFail={onFail} />);
    act(() => {
      window.dispatchEvent(new MessageEvent("message", { data: { type: "look:ready" }, source: window }));
      vi.advanceTimersByTime(READY_TIMEOUT_MS + 10);
    });
    expect(onFail).toHaveBeenCalledOnce();
  });
});
