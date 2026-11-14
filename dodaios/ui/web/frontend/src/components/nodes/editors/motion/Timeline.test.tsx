/**
 * The timeline: blocks as long as their scenes, reorder by dragging and by
 * keys, length by the edge handle, transitions, the playhead.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { readMotionSpec, type MotionSpec } from "./motionModel";
import { Timeline, layoutBlocks, slotAt, type TimelineProps } from "./Timeline";

vi.mock("@/i18n", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/i18n")>();
  return { ...actual, useT: () => (key: string) => key, useUiLanguage: () => "en" };
});

afterEach(cleanup);

// jsdom has no PointerEvent; a mouse event with a pointer id carries what the timeline reads.
if (typeof window.PointerEvent === "undefined") {
  class TestPointerEvent extends MouseEvent {
    readonly pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 1;
    }
  }
  (window as unknown as { PointerEvent: typeof TestPointerEvent }).PointerEvent = TestPointerEvent;
}

function film(): MotionSpec {
  return readMotionSpec({
    scenes: [
      { type: "title", title: "Hello", seconds: 4, transition: "fade" },
      { type: "bullets", title: "Points", bullets: ["a"], seconds: 3.5, transition: "slide" },
      { type: "end", title: "Bye", seconds: 2.5, transition: "zoom" },
    ],
  });
}

function setup(overrides: Partial<TimelineProps> = {}) {
  const props: TimelineProps = {
    spec: film(),
    selected: 0,
    onSelect: vi.fn(),
    onMove: vi.fn(),
    onSeconds: vi.fn(),
    onTransition: vi.fn(),
    onAdd: vi.fn(),
    onDuplicate: vi.fn(),
    onRemove: vi.fn(),
    playhead: null,
    ...overrides,
  };
  render(<Timeline {...props} />);
  return props;
}

describe("layout", () => {
  it("sizes blocks by their length, never below a readable minimum", () => {
    const boxes = layoutBlocks([4, 3.5, 0.5], 48);
    expect(boxes.map((box) => box.width)).toEqual([192, 168, 76]);
    expect(boxes.map((box) => box.left)).toEqual([0, 214, 404]);
    // The slot under a pointer: left of a block's middle is before it.
    expect([0, 95, 97, 300, 900].map((x) => slotAt(boxes, x))).toEqual([0, 0, 1, 2, 3]);
  });
});

describe("Timeline", () => {
  it("lists the scenes with their kind, text and length, and the total", () => {
    setup();
    const blocks = screen.getAllByRole("option");
    expect(blocks).toHaveLength(3);
    expect(blocks[0].getAttribute("aria-selected")).toBe("true");
    expect(blocks[1].textContent).toContain("nodes.editor.motion.kinds.bullets");
    expect(blocks[1].textContent).toContain("Points");
    expect(screen.getByTestId("motion-total").textContent).toBe("nodes.editor.motion.timeline.summary");
    // Width follows the length (unmeasured: 48 px per second).
    expect(blocks[0].style.width).toBe("192px");
    expect(blocks[2].style.left).toBe("404px");
  });

  it("reorders by dragging a block over another gap", () => {
    const props = setup();
    const first = screen.getByTestId("motion-scene-0");
    fireEvent.pointerDown(first, { button: 0, pointerId: 1, clientX: 20 });
    expect(props.onSelect).toHaveBeenCalledWith(0);
    const track = first.closest(".overflow-x-auto") as HTMLElement;
    fireEvent.pointerMove(track, { pointerId: 1, clientX: 470 });
    fireEvent.pointerUp(track, { pointerId: 1, clientX: 470 });
    // Past the middle of the last block: the end of the list.
    expect(props.onMove).toHaveBeenCalledWith(0, 2);
    expect(props.onSelect).toHaveBeenLastCalledWith(2);
  });

  it("treats a press without travel as a pick, not a move", () => {
    const props = setup();
    const second = screen.getByTestId("motion-scene-1");
    fireEvent.pointerDown(second, { button: 0, pointerId: 1, clientX: 250 });
    fireEvent.pointerMove(second, { pointerId: 1, clientX: 252 });
    fireEvent.pointerUp(second, { pointerId: 1, clientX: 252 });
    expect(props.onSelect).toHaveBeenCalledWith(1);
    expect(props.onMove).not.toHaveBeenCalled();
  });

  it("drags a scene's length with its edge, as one gesture", () => {
    const props = setup();
    const handle = screen.getByTestId("motion-length-0");
    fireEvent.pointerDown(handle, { button: 0, pointerId: 2, clientX: 190 });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 238 });
    // 48 px at 48 px per second: one second longer.
    expect(props.onSeconds).toHaveBeenLastCalledWith(0, 5, false);
    fireEvent.pointerUp(handle, { pointerId: 2, clientX: 238 });
    expect(props.onSeconds).toHaveBeenLastCalledWith(0, 4, true);
    expect(props.onMove).not.toHaveBeenCalled();
  });

  it("works from the keyboard: pick, move, length, duplicate, delete", () => {
    const props = setup({ selected: 1 });
    const block = screen.getByTestId("motion-scene-1");
    fireEvent.keyDown(block, { key: "ArrowRight" });
    expect(props.onSelect).toHaveBeenLastCalledWith(2);
    fireEvent.keyDown(block, { key: "ArrowLeft", altKey: true });
    expect(props.onMove).toHaveBeenLastCalledWith(1, 0);
    fireEvent.keyDown(block, { key: "d", metaKey: true });
    expect(props.onDuplicate).toHaveBeenCalledWith(1);
    fireEvent.keyDown(block, { key: "Delete" });
    expect(props.onRemove).toHaveBeenCalledWith(1);

    const handle = screen.getByTestId("motion-length-1");
    expect(handle.getAttribute("aria-valuenow")).toBe("3.5");
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(props.onSeconds).toHaveBeenLastCalledWith(1, 3.6, false);
    fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
    expect(props.onSeconds).toHaveBeenLastCalledWith(1, 3, false);
    fireEvent.keyDown(handle, { key: "End" });
    expect(props.onSeconds).toHaveBeenLastCalledWith(1, 20, false);
  });

  it("offers the transitions between scenes", () => {
    const props = setup();
    expect(screen.queryByTestId("motion-transition-0")).toBeNull();
    fireEvent.click(screen.getByTestId("motion-transition-2"));
    fireEvent.click(screen.getByTestId("motion-transition-2-cut"));
    expect(props.onTransition).toHaveBeenCalledWith(2, "cut");
  });

  it("adds a scene of a kind from its own end", () => {
    const props = setup();
    fireEvent.click(screen.getByTestId("motion-timeline-add"));
    fireEvent.click(screen.getByTestId("motion-add-quote"));
    expect(props.onAdd).toHaveBeenCalledWith("quote");
  });

  it("runs a playhead across the playing scene", () => {
    setup({ playhead: { t: 5, scene: 1 } });
    // Scene 2 starts at 214 px and 4 s; one second in at 48 px per second.
    expect(screen.getByTestId("motion-playhead").style.left).toBe("262px");
  });

  it("marks a scene the server would refuse", () => {
    const spec = film();
    spec.scenes[2] = { ...spec.scenes[2], title: "" };
    setup({ spec });
    expect(screen.getByTestId("motion-scene-2").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByTestId("motion-scene-0").getAttribute("aria-invalid")).toBeNull();
  });
});
