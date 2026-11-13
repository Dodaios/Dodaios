/**
 * The shelf of node types: a tile narrows the library to its type and never
 * makes a node.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { NODE_TYPES, type NodeType } from "./nodeModel";
import { NodeTypeRow } from "./NodeTypeRow";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("NodeTypeRow", () => {
  it("offers one tile per type, in library order, each named by its type", () => {
    render(<NodeTypeRow selected={null} onSelect={() => undefined} />);
    const row = screen.getByTestId("nodes-type-row");
    const tiles = Array.from(row.querySelectorAll("button"));
    expect(tiles.map((tile) => tile.getAttribute("data-testid"))).toEqual(
      NODE_TYPES.map((type) => `nodes-type-${type}`),
    );
    for (const type of NODE_TYPES) {
      const tile = screen.getByTestId(`nodes-type-${type}`);
      expect(tile.textContent).toContain(`nodes.type.${type}`);
      expect(tile.getAttribute("aria-pressed")).toBe("false");
      expect(tile.style.getPropertyValue("--node-hue")).toBe(`var(--node-${type})`);
      expect(tile.querySelector(`[data-node-type-icon="${type}"]`)).toBeTruthy();
    }
  });

  it("picks a type, and lets go of it when the picked tile is chosen again", () => {
    const onSelect = vi.fn<(type: NodeType | null) => void>();
    const view = render(<NodeTypeRow selected={null} onSelect={onSelect} />);
    fireEvent.click(screen.getByTestId("nodes-type-sheets"));
    expect(onSelect).toHaveBeenLastCalledWith("sheets");

    view.rerender(<NodeTypeRow selected="sheets" onSelect={onSelect} />);
    expect(screen.getByTestId("nodes-type-sheets").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByTestId("nodes-type-docs").getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(screen.getByTestId("nodes-type-motion"));
    expect(onSelect).toHaveBeenLastCalledWith("motion");
    fireEvent.click(screen.getByTestId("nodes-type-sheets"));
    expect(onSelect).toHaveBeenLastCalledWith(null);
  });

  it("says how many nodes a type holds, and nothing for an empty one", () => {
    render(<NodeTypeRow selected={null} onSelect={() => undefined} counts={{ sheets: 3, docs: 0 }} />);
    expect(screen.getByTestId("nodes-type-count-sheets").textContent).toBe("3");
    expect(screen.queryByTestId("nodes-type-count-docs")).toBeNull();
    expect(screen.queryByTestId("nodes-type-count-slides")).toBeNull();
  });
});
