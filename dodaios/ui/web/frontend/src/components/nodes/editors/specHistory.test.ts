import { describe, expect, it } from "vitest";

import { COALESCE_MS, applyChange, breakRun, commit, createHistory, redo, undo } from "./specHistory";

interface Doc {
  title: string;
  body: string;
}

const T = 1_000_000;

function typed(text: string, at: number, key = "title") {
  return (history: ReturnType<typeof createHistory<Doc>>) =>
    applyChange(history, (draft) => void (draft.title = text), { label: "Title", coalesce: key }, at);
}

describe("the undo history", () => {
  it("undoes and redoes whole steps, with their labels", () => {
    let h = createHistory<Doc>({ title: "", body: "" });
    h = applyChange(h, (d) => void (d.title = "A"), { label: "Title" }, T);
    h = applyChange(h, (d) => void (d.body = "B"), { label: "Body" }, T + 10);
    expect(h.past.map((e) => e.label)).toEqual(["Title", "Body"]);
    h = undo(h);
    expect(h.present).toEqual({ title: "A", body: "" });
    expect(h.future.map((e) => e.label)).toEqual(["Body"]);
    h = undo(h);
    expect(h.present).toEqual({ title: "", body: "" });
    expect(undo(h).present).toBe(h.present);
    h = redo(redo(h));
    expect(h.present).toEqual({ title: "A", body: "B" });
    expect(redo(h)).toBe(h);
  });

  it("merges a run of keystrokes in one field into one step", () => {
    let h = createHistory<Doc>({ title: "", body: "" });
    h = typed("H", T)(h);
    h = typed("He", T + 300)(h);
    h = typed("Hel", T + 600)(h);
    expect(h.past).toHaveLength(1);
    expect(undo(h).present.title).toBe("");
  });

  it("ends the run on another field, a pause, an undo or an explicit break", () => {
    let h = createHistory<Doc>({ title: "", body: "" });
    h = typed("A", T)(h);
    h = typed("A", T + 100, "body")(h); // same text, no change: nothing recorded
    h = applyChange(h, (d) => void (d.body = "x"), { coalesce: "body" }, T + 200);
    expect(h.past).toHaveLength(2);
    h = applyChange(h, (d) => void (d.body = "xy"), { coalesce: "body" }, T + 200 + COALESCE_MS + 1);
    expect(h.past).toHaveLength(3);
    h = breakRun(h);
    h = applyChange(h, (d) => void (d.body = "xyz"), { coalesce: "body" }, T + 200 + COALESCE_MS + 2);
    expect(h.past).toHaveLength(4);
    h = undo(h);
    h = applyChange(h, (d) => void (d.body = "xyw"), { coalesce: "body" }, T + 200 + COALESCE_MS + 3);
    expect(h.past).toHaveLength(4);
    expect(h.present.body).toBe("xyw");
  });

  it("clears the redo branch on a new change", () => {
    let h = createHistory<Doc>({ title: "", body: "" });
    h = applyChange(h, (d) => void (d.title = "A"), {}, T);
    h = undo(h);
    expect(h.future).toHaveLength(1);
    h = applyChange(h, (d) => void (d.title = "B"), {}, T + 1);
    expect(h.future).toHaveLength(0);
    expect(h.present.title).toBe("B");
  });

  it("keeps at most `depth` steps, dropping the oldest", () => {
    let h = createHistory<Doc>({ title: "0", body: "" });
    for (let n = 1; n <= 8; n += 1) h = applyChange(h, (d) => void (d.title = String(n)), {}, T + n, 5);
    expect(h.past).toHaveLength(5);
    while (h.past.length > 0) h = undo(h);
    expect(h.present.title).toBe("3");
  });

  it("returns the same history for a change that changes nothing", () => {
    const h = createHistory<Doc>({ title: "A", body: "" });
    expect(applyChange(h, (d) => void (d.title = "A"))).toBe(h);
  });

  it("commits a whole new spec as one step (a remote revision)", () => {
    let h = createHistory<Doc>({ title: "A", body: "" });
    h = commit(h, { title: "Theirs", body: "" }, { label: "Revised" }, T);
    expect(h.past.map((e) => e.label)).toEqual(["Revised"]);
    expect(undo(h).present.title).toBe("A");
  });
});
