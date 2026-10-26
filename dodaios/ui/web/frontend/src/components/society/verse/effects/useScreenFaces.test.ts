import { describe, expect, it } from "vitest";
import type { Deck } from "../content/deck";
import { masterScreenPanes, terminalSocketIds } from "./useScreenFaces";

function deck(id: string): Deck {
  const sockets = [
    { id: "term_1", kind: "seat" }, { id: "term_1", kind: "screen" },
    { id: "plot_table", kind: "screen", station: "master" }, { id: "master__2", kind: "screen", station: "master" },
    { id: "reactor_ring__ring_1", kind: "screen" },
  ];
  return { id, sockets } as unknown as Deck;
}

describe("terminal screens", () => {
  it("are the engineering desks and the master station's screens", () => {
    expect([...terminalSocketIds(deck("engineering"))].sort()).toEqual(["master__2", "plot_table", "term_1"]);
    expect(terminalSocketIds(deck("bridge")).size).toBe(0);
    expect(terminalSocketIds(null).size).toBe(0);
  });

  it("show every pane on the big screens and one pane on a numbered console", () => {
    expect(masterScreenPanes({ id: "plot_table" }, ["a", "b", "c"])).toEqual(["a", "b", "c"]);
    expect(masterScreenPanes({ id: "master__2" }, ["a", "b", "c"])).toEqual(["b"]);
    expect(masterScreenPanes({ id: "master__5" }, ["a"])).toEqual([]);
  });
});
