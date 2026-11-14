/**
 * The sheet editor's rules, without a DOM: what a typed or pasted text
 * becomes in each column type (the value `normalize` in `sheets.py` keeps),
 * the formula grammar and its arithmetic as Python computes them, clipboard
 * text as other spreadsheet apps write it, selection moves, and every grid
 * operation on the spec (run through `produce`, as the editor runs them).
 */
import { describe, expect, it } from "vitest";

import { produce } from "../produce";
import { bindingOf, chartSource, drawnChart, storedChart } from "./charts";
import { clipboardText, parseTsv, toTsv } from "./clipboard";
import { FormulaError, columnTotal, computeRows, evaluate, formulaPlan, parseFormula, roundHalfAway } from "./formula";
import {
  blankSheet,
  columnKind,
  columnLetter,
  columnViews,
  convertCell,
  displayText,
  editText,
  parseDate,
  parseInput,
  parseNumber,
  slug,
  uniqueKey,
  type ColumnType,
  type Row,
  type Sheet,
  type SheetsSpec,
} from "./model";
import * as ops from "./ops";
import { advance, at, clampSelection, jump, move, rangeOf, selectAll, selectRows } from "./selection";

const view = (kind: ColumnType, typed = true, unit = "") => ({ kind, column: { type: typed ? kind : undefined, unit } });

function orders(): Sheet {
  return {
    name: "Orders",
    columns: [
      { key: "item", label: "Item" },
      { key: "qty", label: "Qty", type: "number", total: "sum" },
      { key: "price", label: "Price", type: "currency", unit: "EUR" },
      { key: "amount", label: "Amount", type: "currency", unit: "EUR", formula: "qty * price" },
    ],
    rows: [
      { item: "Paper", qty: 4, price: 5.5 },
      { item: "Toner", qty: 2, price: 39 },
      { item: "Pens", qty: 10, price: 1.2 },
    ],
    freeze: 1,
  };
}

function spec(): SheetsSpec {
  return { sheets: [orders()] };
}

/** Run an operation on a sheet the way the editor does: on a draft. */
function run(sheet: Sheet, change: (draft: Sheet) => void): Sheet {
  return produce({ sheets: [sheet] } as SheetsSpec, (draft) => {
    change(draft.sheets[0]);
  }).sheets[0];
}

describe("typing into a cell", () => {
  it("reads numbers in the locale's notation, with currency signs, units and grouping", () => {
    expect(parseNumber("1,234.5", "en-US")).toBe(1234.5);
    expect(parseNumber("1.234,5", "de-DE")).toBe(1234.5);
    expect(parseNumber("1,5", "de-DE")).toBe(1.5);
    expect(parseNumber("1.5", "de-DE")).toBe(1.5);
    expect(parseNumber("1.234", "de-DE")).toBe(1234);
    expect(parseNumber("1.234", "en-US")).toBe(1.234);
    expect(parseNumber("€ 12.50", "en-US")).toBe(12.5);
    expect(parseNumber("12,50 €", "de-DE")).toBe(12.5);
    expect(parseNumber("-€5", "en-US")).toBe(-5);
    expect(parseNumber("−3", "en-US")).toBe(-3);
    expect(parseNumber("(12)", "en-US")).toBe(-12);
    expect(parseNumber("12.5%", "en-US")).toBe(12.5);
    expect(parseNumber("4 kg", "en-US", "kg")).toBe(4);
    expect(parseNumber("1e3", "en-US")).toBe(1000);
    expect(parseNumber("USD 40", "en-US")).toBe(40);
    for (const text of ["", "n/a", "12abc", "1,2,3.4.5", "abc12", "1.2.3,4"]) expect(parseNumber(text, "en-US")).toBeNull();
  });

  it("reads dates as ISO or in the locale's day/month order", () => {
    expect(parseDate("2026-03-31")).toBe("2026-03-31");
    expect(parseDate("2026-03-31 14:30")).toBe("2026-03-31T14:30");
    expect(parseDate("31.03.2026", "de-DE")).toBe("2026-03-31");
    expect(parseDate("3/31/2026", "en-US")).toBe("2026-03-31");
    expect(parseDate("31/3/26 9:05", "en-GB")).toBe("2026-03-31T09:05");
    expect(parseDate("2026-02-30")).toBeNull();
    expect(parseDate("31.02.2026", "de-DE")).toBeNull();
    expect(parseDate("end of March")).toBeNull();
  });

  it("stores what the column's type keeps, as the server would", () => {
    expect(parseInput("  12,5 ", view("number"), "de-DE")).toBe(12.5);
    expect(parseInput("n/a", view("number"), "en-US")).toBe("n/a");
    expect(parseInput("", view("text"))).toBeNull();
    expect(parseInput("  two   words ", view("text"))).toBe("two words");
    expect(parseInput("12", view("text"))).toBe("12");
    // A column without a type keeps a typed number a number, so it stays a number column.
    expect(parseInput("12", view("number", false), "en-US")).toBe(12);
    expect(parseInput("hello", view("text", false))).toBe("hello");
    expect(parseInput("yes", view("check"))).toBe(true);
    expect(parseInput("✓", view("check"))).toBe(true);
    expect(parseInput("off", view("check"))).toBe(false);
    expect(parseInput("maybe", view("check"))).toBeNull();
    expect(parseInput("31.03.2026", view("date"), "de-DE")).toBe("2026-03-31");
    expect(parseInput("end of March", view("date"))).toBe("end of March");
    expect(parseInput("https://example.org/a", view("link"))).toEqual({ text: "https://example.org/a", href: "https://example.org/a" });
    expect(parseInput("Invoice", view("link"), undefined, { text: "Old", href: "https://x.org" })).toEqual({ text: "Invoice", href: "https://x.org" });
    expect(parseInput("javascript:alert(1)", view("link"))).toBe("javascript:alert(1)");
    expect(parseInput("Late", view("status"), undefined, { text: "Risky", tone: "warn" })).toEqual({ text: "Late", tone: "warn" });
    expect(parseInput("x".repeat(900), view("text"))).toHaveLength(500);
  });

  it("carries cells into a column of another type", () => {
    expect(convertCell("12", "number", "")).toBe(12);
    expect(convertCell("text", "number", "")).toBe("text");
    expect(convertCell(1, "check", "")).toBe(true);
    expect(convertCell(12.5, "text", "", "en-US")).toBe("12.5");
    expect(convertCell("yes", "check", "")).toBe(true);
  });

  it("shows numbers formatted, dates written out and starts an edit from the raw value", () => {
    const sheet = orders();
    const views = columnViews(sheet.columns, sheet.rows, "en-US");
    const price = views[2];
    expect(price.decimals).toBe(2);
    expect(displayText(39, price, "en-US")).toBe("€39.00");
    expect(displayText(1234.5, columnViews([{ key: "n", label: "N", type: "number", decimals: 1 }], [], "en-US")[0], "en-US")).toBe("1,234.5");
    const pct = columnViews([{ key: "p", label: "P", type: "percent" }], [{ p: 12.5 }], "en-US")[0];
    expect(displayText(12.5, pct, "en-US")).toBe("12.5%");
    const day = columnViews([{ key: "d", label: "D", type: "date" }], [], "en-US")[0];
    expect(displayText("2026-03-31", day, "en-US")).toMatch(/Mar 31, 2026/);
    expect(displayText("end of March", day, "en-US")).toBe("end of March");
    expect(editText(1234.5, "de-DE")).toBe("1234,5");
    expect(editText({ text: "Invoice", href: "https://x.org" })).toBe("Invoice");
  });

  it("infers a column's type from its cells and makes keys like the server", () => {
    expect(columnKind({ key: "a", label: "A" }, [{ a: 1 }, { a: 2.5 }])).toBe("number");
    expect(columnKind({ key: "a", label: "A" }, [{ a: true }])).toBe("check");
    expect(columnKind({ key: "a", label: "A" }, [{ a: 1 }, { a: "x" }])).toBe("text");
    expect(columnKind({ key: "a", label: "A", formula: "b * 2" }, [])).toBe("number");
    expect(slug("Unit Price", 0)).toBe("unit_price");
    expect(slug("2026", 0)).toBe("_2026");
    expect(slug("class", 0)).toBe("class_");
    expect(slug("???", 3)).toBe("col4");
    expect(uniqueKey("item", new Set(["item", "item_2"]))).toBe("item_3");
    expect(columnLetter(0)).toBe("A");
    expect(columnLetter(26)).toBe("AA");
    expect(blankSheet("Sheet", [orders(), { ...orders(), name: "Sheet 3" }]).name).toBe("Sheet 4");
  });
});

describe("formulas", () => {
  it("follow Python's precedence and functions", () => {
    const calc = (text: string, row = {}) => evaluate(parseFormula(text), row);
    expect(calc("2 ** 3 ** 2")).toBe(512);
    expect(calc("-2 ** 2")).toBe(-4);
    expect(calc("2 ** -1")).toBe(0.5);
    expect(calc("7 // 2 + 7 % 2")).toBe(4);
    expect(calc("-7 // 2")).toBe(-4);
    expect(calc("-7 % 3")).toBe(2);
    expect(calc("round(2.675, 2)")).toBe(2.68);
    expect(calc("round(-2.5)")).toBe(-3);
    expect(calc("round(1234.5, -2)")).toBe(1200);
    expect(calc("0.1 + 0.2")).toBe(0.3);
    expect(calc("max(1, qty, 3) + sum(qty, qty)", { qty: 5 })).toBe(15);
    expect(calc("abs(-3) * min(4, 2)")).toBe(6);
    expect(roundHalfAway(0.125, 2)).toBe(0.13);
  });

  it("leave a cell empty for a missing input, a division by zero or an overflow", () => {
    const calc = (text: string, row = {}) => evaluate(parseFormula(text), row);
    expect(calc("a * 2")).toBeNull();
    expect(calc("a * 2", { a: "text" })).toBeNull();
    expect(calc("1 / 0")).toBeNull();
    expect(calc("5 % 0")).toBeNull();
    expect(calc("2 ** 4000")).toBeNull();
    expect(calc("(0 - 8) ** 0.5")).toBeNull();
  });

  it("refuse anything outside the grammar", () => {
    for (const text of ["", "qty *", "__import__('os')", "a.b", "a[0]", "lambda: 1", "foo(1)", "round()", "abs(1, 2)", "1 if a else 2", "'x'", "a = 1", "2 3", "x".repeat(201)]) {
      expect(() => parseFormula(text), text).toThrow(FormulaError);
    }
  });

  it("are planned in dependency order and report unknown keys and cycles", () => {
    const plan = formulaPlan([
      { key: "a", label: "A" },
      { key: "c", label: "C", formula: "b + 1" },
      { key: "b", label: "B", formula: "a * 2" },
    ]);
    expect(plan.order.map(([key]) => key)).toEqual(["b", "c"]);
    expect(computeRows([{ a: 2 }], plan)).toEqual([{ a: 2, b: 4, c: 5 }]);
    expect(formulaPlan([{ key: "a", label: "A", formula: "zz + 1" }]).problems).toEqual([{ key: "a", reason: "unknown", name: "zz" }]);
    const cyclic = formulaPlan([
      { key: "a", label: "A", formula: "b" },
      { key: "b", label: "B", formula: "a" },
    ]);
    expect(cyclic.problems.map((p) => p.reason)).toContain("cycle");
    expect(formulaPlan([{ key: "a", label: "A", formula: "1 +" }]).problems[0].reason).toBe("grammar");
  });

  it("totals as the page totals", () => {
    const rows: Row[] = [{ v: 2 }, { v: 4 }, { v: "x" }, {}];
    expect(columnTotal("sum", "number", "v", rows)).toBe(6);
    expect(columnTotal("avg", "number", "v", rows)).toBe(3);
    expect(columnTotal("min", "number", "v", rows)).toBe(2);
    expect(columnTotal("count", "text", "v", rows)).toBe(3);
    expect(columnTotal("count", "check", "c", [{ c: true }, { c: false }, { c: true }])).toBe(2);
    expect(columnTotal("sum", "number", "v", [{}])).toBeNull();
  });
});

describe("the clipboard", () => {
  it("parses what spreadsheet apps write: tabs, CRLF, quoted cells with tabs, breaks and quotes", () => {
    expect(parseTsv("a\tb\r\nc\td\r\n")).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]);
    expect(parseTsv('"x\ty"\t"line 1\nline 2"\t"say ""hi"""\nz')).toEqual([["x\ty", "line 1\nline 2", 'say "hi"'], ["z"]]);
    expect(parseTsv("one")).toEqual([["one"]]);
    expect(parseTsv("a\t\tc")).toEqual([["a", "", "c"]]);
    expect(parseTsv("")).toEqual([]);
    expect(parseTsv('5" screen\tok')).toEqual([['5" screen', "ok"]]);
  });

  it("writes cells another app reads back as the same values", () => {
    const text = toTsv([
      ["a\tb", "plain"],
      ['q"uote', "multi\nline"],
    ]);
    expect(text).toBe('"a\tb"\tplain\n"q""uote"\t"multi\nline"');
    expect(parseTsv(text)).toEqual([
      ["a\tb", "plain"],
      ['q"uote', "multi\nline"],
    ]);
    expect(clipboardText(1234.5, "de-DE")).toBe("1234,5");
    expect(clipboardText(true)).toBe("TRUE");
    expect(clipboardText({ text: "https://x.org", href: "https://x.org" })).toBe("https://x.org");
    expect(clipboardText(undefined)).toBe("");
  });
});

describe("the selection", () => {
  const size = { rows: 10, cols: 4 };

  it("moves with the arrows, extends with Shift and stays inside the grid", () => {
    let sel = at(0, 0);
    sel = move(sel, -1, 0, size);
    expect(sel.active).toEqual({ row: 0, col: 0 });
    sel = move(sel, 2, 1, size);
    expect(sel.active).toEqual({ row: 2, col: 1 });
    sel = move(sel, 1, 1, size, true);
    expect(rangeOf(sel)).toEqual({ top: 2, left: 1, bottom: 3, right: 2 });
    expect(sel.active).toEqual({ row: 2, col: 1 });
    expect(clampSelection(at(20, 9), size).active).toEqual({ row: 9, col: 3 });
  });

  it("jumps to the edge of a block of filled cells with Cmd/Ctrl", () => {
    const filled = (row: number, col: number) => col === 0 && (row <= 3 || row === 7);
    expect(jump(at(0, 0), 1, 0, size, filled).active).toEqual({ row: 3, col: 0 });
    expect(jump(at(3, 0), 1, 0, size, filled).active).toEqual({ row: 7, col: 0 });
    expect(jump(at(7, 0), 1, 0, size, filled).active).toEqual({ row: 9, col: 0 });
    expect(rangeOf(jump(at(0, 0), 1, 0, size, filled, true))).toEqual({ top: 0, left: 0, bottom: 3, right: 0 });
  });

  it("walks Enter and Tab through a range and wraps", () => {
    let sel = { anchor: { row: 1, col: 1 }, focus: { row: 2, col: 2 }, active: { row: 1, col: 1 } };
    sel = advance(sel, false, true, size);
    expect(sel.active).toEqual({ row: 1, col: 2 });
    sel = advance(sel, false, true, size);
    expect(sel.active).toEqual({ row: 2, col: 1 });
    sel = advance(sel, true, true, size);
    expect(sel.active).toEqual({ row: 1, col: 2 });
    expect(rangeOf(sel)).toEqual({ top: 1, left: 1, bottom: 2, right: 2 });
    expect(advance(at(4, 1), true, true, size).active).toEqual({ row: 5, col: 1 });
    expect(advance(at(4, 1), false, false, size).active).toEqual({ row: 4, col: 0 });
  });

  it("selects whole rows and everything", () => {
    expect(rangeOf(selectRows(2, 4, size))).toEqual({ top: 2, left: 0, bottom: 4, right: 3 });
    expect(rangeOf(selectAll(size, 5))).toEqual({ top: 0, left: 0, bottom: 4, right: 3 });
  });
});

describe("grid operations on the spec", () => {
  it("write cells, create rows below the data and drop trailing blank rows", () => {
    const before = orders();
    const after = run(before, (draft) =>
      ops.writeCells(draft, [
        { row: 0, key: "qty", value: 5 },
        { row: 5, key: "item", value: "Ink" },
        { row: 1, key: "amount", value: 99 },
      ]),
    );
    expect(after.rows[0].qty).toBe(5);
    expect(after.rows).toHaveLength(6);
    expect(after.rows[4]).toEqual({});
    expect(after.rows[5]).toEqual({ item: "Ink" });
    expect("amount" in after.rows[1]).toBe(false); // a formula column stores nothing
    expect(after.rows[2]).toBe(before.rows[2]); // untouched rows are shared
    const cleared = run(after, (draft) => ops.clearCells(draft, [5], ["item"]));
    expect(cleared.rows).toHaveLength(3);
  });

  it("insert and delete rows, moving a chart's row range with them", () => {
    const sheet = { ...orders(), charts: [{ type: "column", x: "item", series: [{ column: "qty" }], rows: [2, 3] as [number, number] }] };
    const inserted = run(sheet, (draft) => ops.insertRows(draft, 1, 2));
    expect(inserted.rows).toHaveLength(5);
    expect(inserted.rows[1]).toEqual({});
    expect(inserted.charts?.[0].rows).toEqual([4, 5]);
    const deleted = run(inserted, (draft) => ops.deleteRows(draft, [1, 2, 3]));
    expect(deleted.rows.map((r) => r.item)).toEqual(["Paper", "Pens"]);
    expect(deleted.charts?.[0].rows).toEqual([2, 2]);
    const below = run(sheet, (draft) => ops.insertRows(draft, 3, 1));
    expect(below.rows).toHaveLength(3); // below the data the grid offers empty rows already
  });

  it("insert, move and delete columns; a column a formula reads cannot go", () => {
    const sheet = orders();
    const wider = run(sheet, (draft) => void ops.insertColumns(draft, 1, 2));
    expect(wider.columns.map((c) => c.label)).toEqual(["Item", "E", "F", "Qty", "Price", "Amount"]);
    expect(new Set(wider.columns.map((c) => c.key)).size).toBe(6);
    let refused: string[] = [];
    const same = run(sheet, (draft) => {
      refused = ops.deleteColumns(draft, ["qty"]).map((c) => c.key);
    });
    expect(refused).toEqual(["amount"]);
    expect(same).toBe(sheet);
    const charted = { ...sheet, charts: [{ type: "column", x: "item", series: [{ column: "price" }, { column: "qty" }] }] };
    const fewer = run(charted, (draft) => void ops.deleteColumns(draft, ["item", "amount"]));
    expect(fewer.columns.map((c) => c.key)).toEqual(["qty", "price"]);
    expect(fewer.rows[0]).toEqual({ qty: 4, price: 5.5 });
    expect(fewer.charts?.[0]).toEqual({ type: "column", series: [{ column: "price" }, { column: "qty" }] });
    const noPrice = run(fewer, (draft) => void ops.deleteColumns(draft, ["price", "qty"]));
    expect(noPrice.columns).toHaveLength(2); // a sheet keeps at least one column
    const moved = run(sheet, (draft) => ops.moveColumn(draft, 0, 2));
    expect(moved.columns.map((c) => c.key)).toEqual(["qty", "price", "item", "amount"]);
  });

  it("sort rows by value, formula values included, empty cells last either way", () => {
    const sheet = { ...orders(), rows: [...orders().rows, { item: "Clips" }] };
    const computed = computeRows(sheet.rows, formulaPlan(sheet.columns));
    const byAmount = run(sheet, (draft) => ops.sortRows(draft, "amount", -1, true, computed));
    expect(byAmount.rows.map((r) => r.item)).toEqual(["Toner", "Paper", "Pens", "Clips"]);
    const byName = run(sheet, (draft) => ops.sortRows(draft, "item", 1, false, computed));
    expect(byName.rows.map((r) => r.item)).toEqual(["Clips", "Paper", "Pens", "Toner"]);
    const natural = run({ ...sheet, rows: [{ item: "Item 10" }, { item: "item 9" }] }, (draft) =>
      ops.sortRows(draft, "item", 1, false, [{ item: "Item 10" }, { item: "item 9" }]),
    );
    expect(natural.rows.map((r) => r.item)).toEqual(["item 9", "Item 10"]);
  });

  it("fill down and right, converting into the target column", () => {
    const sheet = orders();
    const down = run(sheet, (draft) => ops.fill(draft, [0, 1, 2, 3], ["qty"], "down", (v) => v));
    expect(down.rows.map((r) => r.qty)).toEqual([4, 4, 4, 4]);
    const right = run(sheet, (draft) =>
      ops.fill(draft, [0], ["item", "qty"], "right", (value) => convertCell(value, "number", "")),
    );
    expect(right.rows[0].qty).toBe("Paper");
  });

  it("change a column: a new type carries the cells, a formula empties them, empty fields go", () => {
    const sheet: Sheet = { name: "S", columns: [{ key: "a", label: "A", type: "text", total: "count" }], rows: [{ a: "12" }, { a: "x" }] };
    const typed = run(sheet, (draft) => ops.patchColumn(draft, 0, { type: "number" }));
    expect(typed.rows).toEqual([{ a: 12 }, { a: "x" }]);
    const formula = run(sheet, (draft) => ops.patchColumn(draft, 0, { formula: "1 + 1" }));
    expect(formula.rows).toEqual([]);
    expect(formula.columns[0].type).toBeUndefined();
    const plain = run(typed, (draft) => ops.patchColumn(draft, 0, { width: 120, bold: true, color: "green", align: "center" }));
    expect(plain.columns[0]).toMatchObject({ width: 120, bold: true, color: "green", align: "center" });
    const reset = run(plain, (draft) => ops.patchColumn(draft, 0, { width: undefined, bold: undefined, label: "  New   name " }));
    expect(reset.columns[0].width).toBeUndefined();
    expect(reset.columns[0].bold).toBeUndefined();
    expect(reset.columns[0].label).toBe("New name");
    const text = run(typed, (draft) => ops.patchColumn(draft, 0, { total: "sum", type: "text" }));
    expect(text.columns[0].total).toBeUndefined();
    expect(ops.normalFormula("  = QTY *   Price ")).toBe("qty * price");
  });

  it("add, duplicate, rename, move and delete sheets", () => {
    let next = produce(spec(), (draft) => void ops.addSheet(draft, "Sheet"));
    expect(next.sheets.map((s) => s.name)).toEqual(["Orders", "Sheet 2"]);
    next = produce(next, (draft) => void ops.duplicateSheet(draft, 0, "copy"));
    expect(next.sheets.map((s) => s.name)).toEqual(["Orders", "Orders copy", "Sheet 2"]);
    expect(next.sheets[1].rows).toEqual(next.sheets[0].rows);
    next = produce(next, (draft) => ops.renameSheet(draft, 2, "  Totals  "));
    next = produce(next, (draft) => ops.moveSheet(draft, 2, 0));
    expect(next.sheets.map((s) => s.name)).toEqual(["Totals", "Orders", "Orders copy"]);
    next = produce(next, (draft) => ops.deleteSheet(draft, 0));
    next = produce(next, (draft) => ops.deleteSheet(draft, 0));
    next = produce(next, (draft) => ops.deleteSheet(draft, 0));
    expect(next.sheets).toHaveLength(1); // the last sheet stays
  });
});

describe("charts from the grid", () => {
  it("are stored bound to the selection's columns and drawn from the cells", () => {
    const sheet = orders();
    const computed = computeRows(sheet.rows, formulaPlan(sheet.columns));
    const source = chartSource(sheet, computed, [0, 3], [0, 1]);
    expect(source).toEqual({
      columns: [
        { key: "item", label: "Item" },
        { key: "amount", label: "Amount" },
      ],
      rows: [
        ["Paper", 22],
        ["Toner", 78],
      ],
    });
    const fromEditor = {
      type: "column" as const,
      title: "Spend",
      stacked: false,
      x: ["Paper", "Toner"],
      series: [{ name: "Amount", data: [22, 78] }],
      colors: [""],
    };
    const stored = storedChart(fromEditor, { x: "item", series: ["amount"] }, sheet, [1, 2]);
    expect(stored).toEqual({ type: "column", title: "Spend", x: "item", series: [{ column: "amount" }], rows: [1, 2] });
    expect(bindingOf(stored)).toEqual({ x: "item", series: ["amount"] });
    const drawn = drawnChart(stored, sheet, computed);
    expect(drawn.x).toEqual(["Paper", "Toner"]);
    expect(drawn.series).toEqual([{ name: "Amount", data: [22, 78] }]);
    // The chart follows the cells.
    const edited = run(sheet, (draft) => ops.writeCells(draft, [{ row: 0, key: "qty", value: 10 }]));
    expect(drawnChart(stored, edited, computeRows(edited.rows, formulaPlan(edited.columns))).series[0].data).toEqual([55, 78]);
  });

  it("keep a renamed series, label rows by number without a label column and clip to what the type draws", () => {
    const sheet = orders();
    const stored = storedChart(
      { type: "bar", x: ["1"], series: [{ name: "Units", data: [1] }] },
      { x: "", series: ["qty"] },
      sheet,
      [3, 100],
    );
    expect(stored.series).toEqual([{ column: "qty", name: "Units" }]);
    expect(stored.x).toBeUndefined();
    expect(stored.rows).toEqual([3, 26]); // a bar chart draws 24 rows at most
    const drawn = drawnChart({ ...stored, rows: [2, 3] }, sheet, sheet.rows);
    expect(drawn.x).toEqual(["2", "3"]);
  });

  it("store a chart without a binding as the literal chart", () => {
    const literal = { type: "line" as const, x: ["a", "b"], series: [{ name: "s", data: [1, 2] }] };
    const stored = storedChart(literal, null, orders(), null);
    expect(stored).toEqual(literal);
    expect(drawnChart(stored, orders(), [])).toBe(stored);
  });
});
