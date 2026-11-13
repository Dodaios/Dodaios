/**
 * The "Make something new" row.
 *
 * Contracts worth pinning:
 * - one tile per node type, in the library's order, each a button whose
 *   accessible name is the type's name (the icon and the sheen say nothing),
 * - a click hands the type to `onPick`,
 * - a disabled row offers nothing to click.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { NewNodeRow } from "./NewNodeRow";
import { NODE_TYPES } from "./nodeModel";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));

afterEach(() => {
  cleanup();
});

describe("NewNodeRow", () => {
  it("offers one named tile per node type, in order", () => {
    render(<NewNodeRow onPick={() => undefined} />);
    const row = screen.getByTestId("nodes-new-row");
    const buttons = Array.from(row.querySelectorAll("button"));
    expect(buttons.map((button) => button.getAttribute("data-testid"))).toEqual(
      NODE_TYPES.map((type) => `nodes-new-${type}`),
    );
    for (const type of NODE_TYPES) {
      const tile = screen.getByRole("button", { name: `nodes.type.${type}` });
      expect(tile.getAttribute("data-testid")).toBe(`nodes-new-${type}`);
      // The type's own icon, in the type's own hue.
      expect(tile.querySelector(`[data-node-type-icon="${type}"]`)).toBeTruthy();
      expect(tile.style.getPropertyValue("--node-hue")).toBe(`var(--node-${type})`);
    }
  });

  it("hands the picked type to onPick", () => {
    const onPick = vi.fn();
    render(<NewNodeRow onPick={onPick} />);
    fireEvent.click(screen.getByTestId("nodes-new-sheets"));
    fireEvent.click(screen.getByTestId("nodes-new-motion"));
    expect(onPick.mock.calls).toEqual([["sheets"], ["motion"]]);
  });

  it("offers nothing to click while disabled", () => {
    const onPick = vi.fn();
    render(<NewNodeRow onPick={onPick} disabled />);
    for (const type of NODE_TYPES) {
      const tile = screen.getByTestId(`nodes-new-${type}`) as HTMLButtonElement;
      expect(tile.disabled).toBe(true);
      fireEvent.click(tile);
    }
    expect(onPick).not.toHaveBeenCalled();
  });
});
