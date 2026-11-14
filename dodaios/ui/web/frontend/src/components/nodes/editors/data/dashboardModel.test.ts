/**
 * The Analytics spec model: reading a saved spec, and every structural
 * change the editor makes.
 *
 * Contracts worth pinning:
 * - a hand-written spec reads like `data.normalize` reads it (top-level parts
 *   become the first section, rows are fitted to the columns),
 * - the dashboard never loses its last metric, chart or table (the server
 *   would refuse it), and a new section is never one `normalize` drops,
 * - the limits of `data.py` hold for every list,
 * - moving, duplicating and moving between sections keep everything else,
 * - the row layout mirrors the page's (`_metrics`, `_charts`),
 * - typed and pasted cells become what the page expects.
 */
import { describe, expect, it } from "vitest";

import { produce } from "../produce";
import {
  LIMITS,
  addColumn,
  addItem,
  addRow,
  addSection,
  canAdd,
  cellFromInput,
  chartRowSpans,
  duplicateItem,
  duplicateSection,
  findProblems,
  metricsPerRow,
  moveColumn,
  moveInList,
  moveItemToSection,
  newMetric,
  parsePastedGrid,
  pasteGrid,
  readDashSpec,
  removeColumn,
  removeItem,
  removeSection,
  type DashSpec,
} from "./dashboardModel";

const chart = (title: string, wide = false) => ({
  type: "column",
  title,
  x: ["a", "b"],
  series: [{ name: "", data: [1, 2] }],
  ...(wide ? { wide: true } : {}),
});

function spec(): DashSpec {
  return readDashSpec({
    summary: "Sales",
    sources: ["orders.csv"],
    sections: [
      {
        title: "October",
        metrics: [
          { label: "Revenue", value: "48k", delta: "+12 %" },
          { label: "Orders", value: "1,204" },
        ],
        charts: [chart("One"), chart("Two")],
      },
      { title: "Products", tables: [{ title: "Top", columns: ["Product", "Units"], rows: [["Filter", 412]] }] },
    ],
  });
}

describe("readDashSpec", () => {
  it("reads the shorthand and fits rows to the columns", () => {
    const read = readDashSpec({
      metrics: [{ label: "A", value: 3 }],
      tables: [{ columns: ["x", "y"], rows: [["only"], ["a", "b", "c"]] }],
      sections: [{ title: "Later", text: "words" }],
    });
    expect(read.sections).toHaveLength(2);
    expect(read.sections[0]!.metrics[0]).toEqual({ label: "A", value: "3" });
    expect(read.sections[0]!.tables[0]!.rows).toEqual([
      ["only", ""],
      ["a", "b"],
    ]);
    expect(read.sections[1]!.title).toBe("Later");
    expect(read.sources).toBeUndefined();
  });

  it("keeps the newer chart keys it does not itself know", () => {
    const read = readDashSpec({ sections: [{ charts: [{ ...chart("Pie"), type: "pie", colors: ["#FF0000", ""] }] }] });
    expect(read.sections[0]!.charts[0]).toMatchObject({ type: "pie", colors: ["#FF0000", ""] });
  });

  it("gives an empty spec one section to work in", () => {
    expect(readDashSpec(null).sections).toHaveLength(1);
  });
});

describe("structure", () => {
  it("adds a titled section after the given one, up to the limit", () => {
    const next = produce(spec(), (draft) => void addSection(draft, 0, "New"));
    expect(next.sections.map((s) => s.title)).toEqual(["October", "New", "Products"]);
    const full = produce(spec(), (draft) => {
      while (draft.sections.length < LIMITS.sections) addSection(draft, 0, "x");
      expect(addSection(draft, 0, "one too many")).toBe(-1);
    });
    expect(full.sections).toHaveLength(LIMITS.sections);
  });

  it("duplicates a section as a deep copy", () => {
    const base = spec();
    const next = produce(base, (draft) => void duplicateSection(draft, 0));
    expect(next.sections[1]).toEqual(base.sections[0]);
    expect(next.sections[1]!.metrics).not.toBe(next.sections[0]!.metrics);
    // The history's earlier version is untouched.
    expect(base.sections).toHaveLength(2);
  });

  it("never removes the dashboard's last part, nor its only section", () => {
    const lone = readDashSpec({ sections: [{ metrics: [{ label: "A", value: "1" }] }] });
    produce(lone, (draft) => {
      expect(removeItem(draft, 0, "metrics", 0)).toBe(false);
      expect(removeSection(draft, 0)).toBe(false);
    });
    const two = readDashSpec({ sections: [{ metrics: [{ label: "A", value: "1" }] }, { title: "Empty" }] });
    const next = produce(two, (draft) => {
      expect(removeSection(draft, 0)).toBe(false); // it holds the last part
      expect(removeSection(draft, 1)).toBe(true);
    });
    expect(next.sections).toHaveLength(1);
  });

  it("adds items up to each list's limit", () => {
    const next = produce(spec(), (draft) => {
      while (canAdd(draft, 0, "metrics")) addItem(draft, 0, "metrics", newMetric("x"));
      expect(addItem(draft, 0, "metrics", newMetric("y"))).toBe(-1);
      expect(duplicateItem(draft, 0, "metrics", 0)).toBe(-1);
    });
    expect(next.sections[0]!.metrics).toHaveLength(LIMITS.metrics);
  });

  it("moves within a list and between sections", () => {
    const items = ["a", "b", "c"];
    expect(moveInList(items, 0, 9)).toBe(2);
    expect(items).toEqual(["b", "c", "a"]);
    expect(moveInList(items, 1, 1)).toBe(1);

    const next = produce(spec(), (draft) => {
      expect(moveItemToSection(draft, 0, "charts", 1, 1)).toBe(0);
    });
    expect(next.sections[0]!.charts.map((c) => c.title)).toEqual(["One"]);
    expect(next.sections[1]!.charts.map((c) => c.title)).toEqual(["Two"]);
  });

  it("refuses to move into a full section", () => {
    produce(spec(), (draft) => {
      while (canAdd(draft, 1, "metrics")) addItem(draft, 1, "metrics", newMetric("x"));
      expect(moveItemToSection(draft, 0, "metrics", 0, 1)).toBe(-1);
      expect(draft.sections[0]!.metrics).toHaveLength(2);
    });
  });
});

describe("layout mirrors the page", () => {
  it("puts metrics in rows of even length", () => {
    expect([1, 2, 3, 4, 5, 6, 7, 8].map(metricsPerRow)).toEqual([1, 2, 3, 4, 3, 3, 4, 4]);
  });

  it("lets a chart alone in its row take the row", () => {
    expect(chartRowSpans([{}, {}, {}])).toEqual([false, false, true]);
    expect(chartRowSpans([{}, { wide: true }, {}])).toEqual([true, true, true]);
    expect(chartRowSpans([{}, {}, { wide: true }, {}, {}])).toEqual([false, false, true, false, false]);
  });
});

describe("problems the server would refuse", () => {
  it("names a metric without label or value and a table without a column name", () => {
    const broken = readDashSpec({
      sections: [{ metrics: [{ label: "", value: "1" }], tables: [{ columns: [""], rows: [] }] }],
    });
    expect(findProblems(broken)).toEqual([
      { section: 0, part: "metrics", index: 0, field: "label" },
      { section: 0, part: "tables", index: 0, field: "columns" },
    ]);
    expect(findProblems(spec())).toEqual([]);
  });
});

describe("table cells", () => {
  it("stores a plain number as a number and anything else as the text typed", () => {
    expect(cellFromInput("412")).toBe(412);
    expect(cellFromInput("-3.5")).toBe(-3.5);
    expect(cellFromInput("14,420 €")).toBe("14,420 €");
    expect(cellFromInput("2025-01-15")).toBe("2025-01-15");
    expect(cellFromInput("")).toBe("");
    expect(cellFromInput("12345678901234567890")).toBe("12345678901234567890");
  });

  it("adds, removes and moves columns together with their cells", () => {
    const table = { title: "", columns: ["a", "b"], rows: [[1, 2]] as (string | number)[][] };
    addColumn(table, "c", 1);
    expect(table).toEqual({ title: "", columns: ["a", "c", "b"], rows: [[1, "", 2]] });
    moveColumn(table, 2, 0);
    expect(table.rows[0]).toEqual([2, 1, ""]);
    expect(removeColumn(table, 0)).toBe(true);
    expect(removeColumn({ title: "", columns: ["only"], rows: [] }, 0)).toBe(false);
    addRow(table);
    expect(table.rows[1]).toEqual(["", ""]);
  });

  it("reads cells copied from a spreadsheet or a CSV file", () => {
    expect(parsePastedGrid("a\tb\n1\t2\n")).toEqual([
      ["a", "b"],
      ["1", "2"],
    ]);
    expect(parsePastedGrid('name,note\n"Smith, J","said ""hi"""')).toEqual([
      ["name", "note"],
      ["Smith, J", 'said "hi"'],
    ]);
    expect(parsePastedGrid("x;y")).toEqual([["x", "y"]]);
  });

  it("pastes a grid from a cell, growing the table up to its limits", () => {
    const table = { title: "", columns: ["a"], rows: [["keep"]] as (string | number)[][] };
    expect(pasteGrid(table, 0, 0, [["one"]])).toBe(false);
    expect(pasteGrid(table, 1, 0, [["x", "1"], ["y", "2"]])).toBe(true);
    expect(table.columns).toHaveLength(2);
    expect(table.rows).toEqual([
      ["keep", ""],
      ["x", 1],
      ["y", 2],
    ]);
  });
});
