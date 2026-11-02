import { act, createEvent, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { ThreadColumns } from "./ThreadColumns";
import { THREAD_DRAG_MIME, THREAD_PROJECT_DRAG_MIME, setDraggedThread, useThreadChat } from "./threadModel";

// Each column shows which thread its own store would open; the real view is tested on its own.
vi.mock("./ThreadView", () => ({
  ThreadView: ({ column }: { column?: { sessionId: string } }) => {
    const store = useThreadChat();
    return <div data-testid="view" data-thread={column?.sessionId ?? "main"} data-store={String(Boolean(store))} />;
  },
}));

/** A drag that carries a thread, the way a sidebar row starts one. */
function threadDrag(sessionId: string, projectId: string) {
  const data: Record<string, string> = { [THREAD_DRAG_MIME]: sessionId, [THREAD_PROJECT_DRAG_MIME]: projectId };
  return {
    types: Object.keys(data),
    getData: (type: string) => data[type] ?? "",
    setData: () => undefined,
    dropEffect: "none",
    effectAllowed: "move",
  };
}

/** Lay the columns out 400px wide each, left to right; jsdom measures nothing. */
function layOut() {
  screen.getByTestId("thread-columns").querySelectorAll<HTMLElement>("[data-thread-column]").forEach((cell, index) => {
    cell.getBoundingClientRect = () => ({ left: index * 400, right: index * 400 + 400, width: 400, top: 0, bottom: 800, height: 800, x: index * 400, y: 0, toJSON: () => ({}) });
  });
}

function dropAt(sessionId: string, clientX: number) {
  const box = screen.getByTestId("thread-columns");
  setDraggedThread(sessionId);
  const dataTransfer = threadDrag(sessionId, "p1");
  // jsdom has no DragEvent: the pointer's x is set on the plain event by hand.
  for (const kind of ["dragOver", "drop"] as const) {
    const event = createEvent[kind](box, { dataTransfer });
    Object.defineProperty(event, "clientX", { value: clientX });
    fireEvent(box, event);
  }
}

function renderColumns() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ThreadColumns onScreen /></QueryClientProvider>);
}

const shown = () => screen.getAllByTestId("view").map((view) => view.dataset.thread);

describe("ThreadColumns", () => {
  beforeEach(() => {
    localStorage.clear();
    useIdeThreadsStore.setState({ selection: { projectId: "p1", sessionId: "s1" }, split: [], mainAt: 0 });
  });
  afterEach(() => setDraggedThread(null));

  it("opens a thread dropped on the right half next to the main one, and on the left half before it", () => {
    renderColumns();
    expect(shown()).toEqual(["main"]);
    layOut();
    act(() => dropAt("s2", 300));
    expect(shown()).toEqual(["main", "s2"]);
    layOut();
    act(() => dropAt("s3", 100));
    expect(shown()).toEqual(["s3", "main", "s2"]);
  });

  it("ignores a drop of the main column's own thread and closes side columns from their header", () => {
    renderColumns();
    layOut();
    act(() => dropAt("s1", 300));
    expect(shown()).toEqual(["main"]);
    layOut();
    act(() => dropAt("s2", 300));
    fireEvent.click(screen.getByTestId("thread-column-close-s2"));
    expect(shown()).toEqual(["main"]);
  });
});
