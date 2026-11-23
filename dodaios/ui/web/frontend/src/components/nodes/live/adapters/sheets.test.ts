import { afterEach, describe, expect, it, vi } from "vitest";

import type { SheetsSpec } from "../../editors/sheets/model";
import { sheetsReveal, changedRows, changedTotals, firstChangedSheet } from "./sheets";

const COLUMNS = [
  { key: "item", label: "Item" },
  { key: "cost", label: "Cost", type: "currency" as const, total: "sum" as const },
];

function spec(rows: Array<Record<string, string | number>>, name = "Costs", extra: SheetsSpec["sheets"] = []): SheetsSpec {
  return { sheets: [{ name, columns: COLUMNS, rows, freeze: 1 }, ...extra] };
}

/** A grid body as the editor draws it: tabs, a header row, marked body rows, a totals cell. */
function grid(next: SheetsSpec, shown = 0): HTMLElement {
  const root = document.createElement("div");
  const tabs = next.sheets.map((_, i) => `<button data-live-path="/sheets/${i}">tab${i}</button>`).join("");
  const rows = next.sheets[shown].rows
    .map((_, i) => `<tr data-live-path="/sheets/${shown}/rows/${i}"><td>r${i}</td></tr>`)
    .join("");
  root.innerHTML =
    `<div data-live-sheet="${shown}"><table><thead><tr data-live-path="/sheets/${shown}/columns"><th>h</th></tr></thead>` +
    `<tbody>${rows}</tbody><tfoot><tr><td data-testid="sheet-total-1">t</td></tr></tfoot></table></div>${tabs}`;
  document.body.appendChild(root);
  return root;
}

function pathsOf(steps: ReturnType<typeof sheetsReveal.steps>): string[] {
  return steps.map((s) =>
    "path" in s.target ? s.target.path : "element" in s.target ? (s.target.element.getAttribute("data-live-path") ?? "?") : "?",
  );
}

const run = (previous: SheetsSpec | null, next: SheetsSpec, root: HTMLElement, initial = false) =>
  sheetsReveal.steps({ type: "sheets", previous, next, ops: null, initial, root });

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("what a sheet edit changed", () => {
  it("lists the rows that were added or rewritten, from the top", () => {
    const before = spec([{ item: "Rent", cost: 900 }]);
    const after = spec([{ item: "Rent", cost: 950 }, { item: "Food", cost: 300 }]);
    expect(changedRows(before, after, 0)).toEqual([0, 1]);
    expect(changedRows(spec([{ item: "Rent", cost: 900 }]), spec([{ item: "Rent", cost: 900 }, { item: "Food", cost: 1 }]), 0)).toEqual([1]);
  });

  it("restyles every row when the columns changed, but not for a width", () => {
    const before = spec([{ item: "a", cost: 1 }, { item: "b", cost: 2 }]);
    const wider = { sheets: [{ ...before.sheets[0], columns: [{ ...COLUMNS[0], width: 200 }, COLUMNS[1]] }] };
    expect(changedRows(before, wider, 0)).toEqual([]);
    const bold = { sheets: [{ ...before.sheets[0], columns: [{ ...COLUMNS[0], bold: true }, COLUMNS[1]] }] };
    expect(changedRows(before, bold, 0)).toEqual([0, 1]);
  });

  it("finds the first sheet that was touched", () => {
    const two = spec([{ item: "a", cost: 1 }], "Costs", [{ name: "Plan", columns: COLUMNS, rows: [] }]);
    expect(firstChangedSheet(spec([{ item: "a", cost: 1 }]), two)).toBe(1);
    expect(firstChangedSheet(two, two)).toBe(-1);
  });

  it("finds the totals that moved with the rows", () => {
    const before = spec([{ item: "a", cost: 1 }]);
    expect(changedTotals(before, spec([{ item: "a", cost: 1 }, { item: "b", cost: 2 }]), 0)).toEqual([1]);
    expect(changedTotals(before, before, 0)).toEqual([]);
  });
});

describe("the sheets reveal", () => {
  it("plays the new rows top to bottom", () => {
    const before = spec([{ item: "a", cost: 1 }]);
    const after = spec([{ item: "a", cost: 1 }, { item: "b", cost: 2 }, { item: "c", cost: 3 }]);
    const steps = run(before, after, grid(after));
    expect(pathsOf(steps)).toEqual(["/sheets/0/rows/1", "/sheets/0/rows/2"]);
    // Each drawn row is typed along, cell by cell.
    expect(steps.every((step) => step.motion !== undefined)).toBe(true);
  });

  it("builds the structure first: the header row, then the body", () => {
    const before = { sheets: [{ name: "Costs", columns: [], rows: [] }] };
    const after = spec([{ item: "a", cost: 1 }]);
    expect(pathsOf(run(before, after, grid(after)))).toEqual(["/sheets/0/columns", "/sheets/0/rows/0"]);
  });

  it("opened mid-build, plays the header and every row", () => {
    const after = spec([{ item: "a", cost: 1 }, { item: "b", cost: 2 }]);
    expect(pathsOf(run(null, after, grid(after), true))).toEqual(["/sheets/0/columns", "/sheets/0/rows/0", "/sheets/0/rows/1"]);
  });

  it("slides a new tab in first, outside the frame", () => {
    const animate = vi.fn();
    const before = spec([{ item: "a", cost: 1 }]);
    const after = spec([{ item: "a", cost: 1 }], "Costs", [{ name: "Plan", columns: COLUMNS, rows: [{ item: "x", cost: 5 }] }]);
    const root = grid(after, 1);
    root.querySelectorAll("button").forEach((b) => ((b as unknown as { animate: unknown }).animate = animate));
    const steps = run(before, after, root);
    expect(pathsOf(steps)).toEqual(["/sheets/1", "/sheets/1/columns", "/sheets/1/rows/0"]);
    expect(steps[0].framed).toBe(false);
    expect(steps[1].framed).toBeUndefined();
    expect(animate).toHaveBeenCalledTimes(1);
  });

  it("highlights a changed total quietly, after the rows are in", () => {
    vi.useFakeTimers();
    const before = spec([{ item: "a", cost: 1 }]);
    const after = spec([{ item: "a", cost: 1 }, { item: "b", cost: 2 }]);
    const root = grid(after);
    const animate = vi.fn();
    (root.querySelector('[data-testid="sheet-total-1"]') as unknown as { animate: unknown }).animate = animate;
    run(before, after, root);
    expect(animate).not.toHaveBeenCalled();
    vi.advanceTimersByTime(400);
    expect(animate).toHaveBeenCalledTimes(1);
  });

  it("plays nothing when no sheet is drawn", () => {
    const after = spec([{ item: "a", cost: 1 }]);
    expect(run(null, after, document.createElement("div"))).toEqual([]);
  });
});
