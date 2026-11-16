/**
 * The node window before its content is there.
 *
 * The window's chunk can still be on its way when the click comes (the first
 * seconds after the app started, a slow disk). The click must not wait for
 * it: the window's frame, the node's name and the ways out are drawn at once
 * from the entry bundle. Here the chunk never arrives, which is the slowest
 * case there is.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { useNodePeek } from "@/store/nodePeek";

vi.mock("./peekFrame", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./peekFrame")>()),
  // Never resolves: the window's content does not arrive in these tests.
  loadNodePeekWindow: () => new Promise(() => undefined),
}));

import { NodePeekHost } from "./NodePeekHost";
import { PEEK_FRAME_CLASS, PEEK_SCRIM_CLASS } from "./peekFrame";

const PLAN = "run-1::tasks/report/artifacts/files/plan.html";

beforeEach(() => {
  useNodePeek.setState({ peek: null, touched: {} });
});

afterEach(() => {
  cleanup();
  useNodePeek.setState({ peek: null, touched: {} });
});

describe("the node window while its content loads", () => {
  it("is on screen at the click: the frame, the node's name and a close button", () => {
    render(<NodePeekHost />);
    expect(screen.queryByTestId("node-peek-loading")).toBeNull();
    act(() => useNodePeek.getState().open(PLAN, { title: "Business plan v1" }));
    // No waiting: the same render that took the click drew the window.
    const frame = screen.getByRole("dialog");
    expect(frame.getAttribute("aria-busy")).toBe("true");
    expect(frame.getAttribute("aria-label")).toBe("Business plan v1");
    expect(frame.textContent).toContain("Business plan v1");
    // The frame the content will stand in, so nothing moves when it arrives.
    expect(frame.className).toBe(PEEK_FRAME_CLASS);
  });

  it("names a node the click gave no name by its file", () => {
    render(<NodePeekHost />);
    act(() => useNodePeek.getState().open(PLAN));
    expect(screen.getByRole("dialog").getAttribute("aria-label")).toBe("plan.html");
  });

  it("can be left at once: the close button, Escape, a click beside it", () => {
    render(<NodePeekHost />);
    act(() => useNodePeek.getState().open(PLAN));
    fireEvent.click(screen.getByTestId("node-peek-loading-close"));
    expect(screen.queryByTestId("node-peek-loading")).toBeNull();

    act(() => useNodePeek.getState().open(PLAN));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(useNodePeek.getState().peek).toBeNull();

    act(() => useNodePeek.getState().open(PLAN));
    const scrim = screen.getByTestId("node-peek-loading").firstElementChild as HTMLElement;
    fireEvent.click(scrim);
    expect(useNodePeek.getState().peek).toBeNull();
  });

  it("dims the page without blurring it and without an entrance animation", () => {
    // A blurred full-window layer over a live app is paid for on every frame,
    // and an animation is time the window is not there yet.
    expect(PEEK_SCRIM_CLASS).not.toContain("blur");
    for (const classes of [PEEK_SCRIM_CLASS, PEEK_FRAME_CLASS]) {
      expect(classes).not.toContain("animate-");
      expect(classes).not.toContain("duration-");
    }
  });
});
