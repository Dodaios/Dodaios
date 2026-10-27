import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { followInspection, latestTurnId, openInspection, useInspectedTurn } from "./inspectedTurn";

const turn = (id: string) => ({ type: "turn", id });
const user = (id: string) => ({ type: "user", id });

describe("the inspected turn", () => {
  it("knows the newest turn of a conversation", () => {
    expect(latestTurnId([])).toBeNull();
    expect(latestTurnId([user("u1"), turn("t1"), user("u2")])).toBe("t1");
    expect(latestTurnId([turn("t1"), user("u2"), turn("t2")])).toBe("t2");
  });

  it("opened on the newest turn it follows; opened on an older one it is pinned", () => {
    expect(openInspection("t2", "t2")).toEqual({ turnId: "t2", pinned: false });
    expect(openInspection("t1", "t2")).toEqual({ turnId: "t1", pinned: true });
    expect(followInspection({ turnId: "t2", pinned: false }, "t3")).toEqual({ turnId: "t3", pinned: false });
    expect(followInspection({ turnId: "t1", pinned: true }, "t3")).toEqual({ turnId: "t1", pinned: true });
    expect(followInspection(null, "t3")).toBeNull();
  });

  it("moves to the live turn when the next one starts, unless an older turn was picked", () => {
    let items = [user("u1"), turn("t1")];
    const { result, rerender } = renderHook(() => useInspectedTurn(items));
    expect(result.current.inspecting).toBeNull();

    act(() => result.current.open("t1"));
    expect(result.current.inspecting).toBe("t1");
    items = [...items, user("u2"), turn("t2")];
    rerender();
    expect(result.current.inspecting).toBe("t2");

    // The person picks the earlier turn on purpose: it stays while t3 runs.
    act(() => result.current.open("t1"));
    expect(result.current.pinned).toBe(true);
    items = [...items, user("u3"), turn("t3")];
    rerender();
    expect(result.current.inspecting).toBe("t1");

    // Picking the newest turn again follows once more.
    act(() => result.current.open("t3"));
    items = [...items, user("u4"), turn("t4")];
    rerender();
    expect(result.current.inspecting).toBe("t4");

    act(() => result.current.close());
    items = [...items, turn("t5")];
    rerender();
    expect(result.current.inspecting).toBeNull();
  });
});
