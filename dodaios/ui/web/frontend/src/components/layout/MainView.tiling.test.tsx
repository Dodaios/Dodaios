import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MainView } from "./MainView";
import { useEventStore } from "@/store/events";
import { useTilingStore } from "@/store/tiling";
import { leaves } from "@/lib/tilingLayout";

const mounts = vi.hoisted(() => ({ ide: 0 }));
vi.mock("@/views/ChatsSurface", () => ({ ChatsSurface: () => <div>Chat view</div> }));
vi.mock("@/views/society/SocietyView", () => ({ SocietyView: () => <div>Agents view</div> }));
vi.mock("@/views/MemoryView", () => ({ MemoryView: () => <div>Wiki view</div> }));
vi.mock("@/views/AgenticIdeView", async () => {
  const { useEffect } = await import("react");
  return {
    AgenticIdeView: ({ onScreen }: { onScreen: boolean }) => {
      useEffect(() => {
        mounts.ide += 1;
      }, []);
      return <div data-on-screen={onScreen}>IDE view</div>;
    },
  };
});

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ source: "desktop", version: "1" }) }));
  mounts.ide = 0;
  useEventStore.setState({ activeSection: "chats", solo: false });
  useTilingStore.setState({ tree: null, focusedId: null, maximizedId: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

describe("MainView tiling", () => {
  it("shows several sections side by side and follows navigation in the focused tile", async () => {
    render(<MainView />);
    act(() => useTilingStore.getState().openBeside("agents"));

    expect(screen.getByTestId("tiling-stage")).toBeTruthy();
    expect(await screen.findByText("Chat view")).toBeTruthy();
    expect(await screen.findByText("Agents view")).toBeTruthy();
    expect(screen.getAllByTestId("tile")).toHaveLength(2);
    // The new tile has focus, so navigating replaces it.
    expect(useEventStore.getState().activeSection).toBe("agents");
    act(() => useEventStore.getState().setActiveSection("memory"));
    expect(await screen.findByText("Wiki view")).toBeTruthy();
    expect(screen.queryByText("Agents view")).toBeNull();
    expect(screen.getByText("Chat view")).toBeTruthy();
  });

  it("focuses the tile that already shows a section instead of opening it twice", () => {
    render(<MainView />);
    act(() => useTilingStore.getState().openBeside("agents"));
    act(() => useEventStore.getState().setActiveSection("chats"));
    const tree = useTilingStore.getState().tree;
    expect(leaves(tree).map((item) => item.section)).toEqual(["chats", "agents"]);
    expect(leaves(tree)[0].id).toBe(useTilingStore.getState().focusedId);
  });

  it("keeps the one IDE instance mounted across layout changes", async () => {
    useEventStore.setState({ activeSection: "agentic-ide" });
    render(<MainView />);
    expect(await screen.findByText("IDE view")).toBeTruthy();
    act(() => useTilingStore.getState().openBeside("agents"));
    act(() => useTilingStore.getState().applyPreset("grid-4"));
    act(() => useTilingStore.getState().applyPreset("single"));
    expect(screen.getByText("IDE view")).toBeTruthy();
    expect(mounts.ide).toBe(1);
  });

  it("collapses to the classic stage when the second-last tile closes", async () => {
    render(<MainView />);
    act(() => useTilingStore.getState().openBeside("agents"));
    const close = screen.getAllByTestId("tile-close")[1];
    fireEvent.click(close);
    expect(useTilingStore.getState().tree).toBeNull();
    expect(screen.queryByTestId("tiling-stage")).toBeNull();
    expect(await screen.findByText("Chat view")).toBeTruthy();
  });

  it("swaps two tiles when one title bar is dropped on the other", async () => {
    render(<MainView />);
    act(() => useTilingStore.getState().openBeside("agents"));
    const [first, second] = leaves(useTilingStore.getState().tree);
    const data = new Map<string, string>();
    const dataTransfer = {
      setData: (type: string, value: string) => data.set(type, value),
      getData: (type: string) => data.get(type) ?? "",
      get types() { return [...data.keys()]; },
      effectAllowed: "move",
    };
    fireEvent.dragStart(screen.getAllByTestId("tile-header")[0], { dataTransfer });
    fireEvent.dragOver(screen.getAllByTestId("tile")[1], { dataTransfer });
    fireEvent.drop(screen.getAllByTestId("tile")[1], { dataTransfer });
    const after = leaves(useTilingStore.getState().tree);
    expect(after.map((item) => item.id)).toEqual([first.id, second.id]);
    expect(after.map((item) => item.section)).toEqual(["agents", "chats"]);
  });
});
