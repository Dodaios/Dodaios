import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LayoutMenuButton } from "./LayoutMenuButton";
import { TileHeader } from "./TileHeader";
import { leaves } from "@/lib/tilingLayout";
import { useEventStore } from "@/store/events";
import { useTilingStore } from "@/store/tiling";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ source: "desktop", version: "1" }) }));
  useEventStore.setState({ activeSection: "chats", solo: false });
  useTilingStore.setState({ tree: null, focusedId: null, maximizedId: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const sections = () => leaves(useTilingStore.getState().tree).map((item) => item.section);

describe("choosing what each tile shows", () => {
  it("keeps the menu open after a layout and lets each slot pick its section", () => {
    render(<LayoutMenuButton />);
    fireEvent.click(screen.getByTestId("layout-menu-button"));
    fireEvent.click(screen.getByTestId("layout-preset-columns-2"));

    expect(screen.getByTestId("layout-menu")).toBeTruthy();
    const slots = screen.getAllByTestId("layout-slot");
    expect(slots).toHaveLength(2);

    fireEvent.click(slots[1]);
    expect(screen.getByTestId("section-picker")).toBeTruthy();
    fireEvent.click(screen.getByTestId("section-pick-memory"));

    expect(sections()).toEqual(["chats", "memory"]);
    expect(screen.queryByTestId("section-picker")).toBeNull();
  });

  it("swaps two tiles when the picked section is already shown elsewhere", () => {
    act(() => useTilingStore.getState().applyPreset("columns-2"));
    const [first, second] = sections();
    render(<LayoutMenuButton />);
    fireEvent.click(screen.getByTestId("layout-menu-button"));
    fireEvent.click(screen.getAllByTestId("layout-slot")[0]);
    fireEvent.click(screen.getByTestId(`section-pick-${second}`));
    expect(sections()).toEqual([second, first]);
  });

  it("filters the list by search and picks the first match on Enter", () => {
    act(() => useTilingStore.getState().applyPreset("columns-2"));
    const leaf = leaves(useTilingStore.getState().tree)[1];
    render(<TileHeader leafId={leaf.id} section={leaf.section} focused maximized={false} />);
    fireEvent.click(screen.getByTestId("tile-section-button"));
    const search = screen.getByRole("textbox");
    fireEvent.change(search, { target: { value: "zzzz-nothing" } });
    expect(screen.queryAllByRole("menuitem")).toHaveLength(0);
    fireEvent.change(search, { target: { value: "memory" } });
    fireEvent.keyDown(search, { key: "Enter" });
    expect(sections()[1]).toBe("memory");
  });
});
