/**
 * The sheets editor on a real editing state machine (`useNodeSpecEditor`,
 * with `fetch` answering its saves) and a real frame. Only the shared chart
 * dialog is a stand-in (it has its own tests): it answers with the chart and
 * the columns the person would have picked.
 *
 * Contracts worth pinning:
 * - the grid shows the spec: formatted numbers, computed formula cells, totals;
 * - the keyboard moves and extends the selection; typing replaces a cell and
 *   Enter/Tab commit and move; F2 edits the value; Escape cancels;
 * - copy writes tab-separated text, paste reads it (and adds columns);
 * - every grid action is one undo step, undone with Ctrl+Z from the grid;
 * - rows and columns are inserted and deleted from the menus;
 * - sort reorders the stored rows, a filter only hides rows from view;
 * - Insert chart stores a chart bound to the selected columns;
 * - what is saved is the spec the server accepts.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { typedNodeCard } from "../../testCards";
import type { ChartBinding, ChartJson, ChartSource } from "../charts/chartModel";
import type { SheetsSpec } from "./model";

const chartDialog = vi.hoisted(() => ({
  last: null as null | { source?: ChartSource; value?: ChartJson | null; binding?: ChartBinding | null },
}));

vi.mock("../charts/ChartEditor", async () => {
  const React = await import("react");
  return {
    ChartEditor: (props: {
      open: boolean;
      source?: ChartSource;
      value?: ChartJson | null;
      binding?: ChartBinding | null;
      onSave: (chart: ChartJson, binding: ChartBinding | null) => void;
      onCancel: () => void;
    }) => {
      if (!props.open) return null;
      chartDialog.last = { source: props.source, value: props.value, binding: props.binding };
      const source = props.source as ChartSource;
      return React.createElement(
        "button",
        {
          "data-testid": "chart-stand-in-save",
          onClick: () =>
            props.onSave(
              {
                type: "column",
                title: "Amounts",
                x: source.rows.map((row) => String(row[0])),
                series: [{ name: source.columns[1].label, data: source.rows.map((row) => Number(row[1])) }],
              },
              { x: source.columns[0].key, series: [source.columns[1].key] },
            ),
        },
        "save chart",
      );
    },
  };
});
vi.mock("../charts/ChartPreview", () => ({
  ChartPreview: ({ chart }: { chart: ChartJson }) => <div data-testid="chart-preview">{chart.series[0]?.data.join(",")}</div>,
}));

import SheetsEditor from "./index";

function orders(): SheetsSpec {
  return {
    sheets: [
      {
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
      },
    ],
  };
}

let saved: SheetsSpec[] = [];

function installFetch() {
  saved = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body ?? "{}")) as { spec: SheetsSpec; base_version: number };
      saved.push(body.spec);
      return {
        ok: true,
        status: 200,
        json: async () => ({ version: body.base_version + 1, updated_at: 500 + saved.length, spec: body.spec }),
      };
    }),
  );
}

class NoResize {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  installFetch();
  vi.stubGlobal("ResizeObserver", NoResize);
  chartDialog.last = null;
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function open(spec: SheetsSpec = orders()) {
  const onDone = vi.fn();
  render(<SheetsEditor node={typedNodeCard("node1", { type: "sheets", title: "Orders" })} initial={{ spec, version: 3, updated_at: 100 }} onDone={onDone} />);
  return { onDone };
}

const field = () => screen.getByTestId("sheet-cell-input") as HTMLTextAreaElement;
const grid = () => screen.getByTestId("sheet-grid");
/** The text of a drawn cell (view row, column). */
function cellText(row: number, col: number): string {
  const td = grid().querySelector(`[data-row="${row}"][data-col="${col}"]`);
  return td?.textContent ?? "";
}
const address = () => screen.getByLabelText("Active cell").textContent;
const key = (k: string, extra: Partial<KeyboardEventInit> = {}) => fireEvent.keyDown(field(), { key: k, ...extra });
function type(text: string) {
  field().value = text;
  fireEvent.input(field());
}
const undoKeys = () => key("z", { ctrlKey: true });

describe("the grid", () => {
  it("shows the spec as a grid with formatted numbers, computed formulas and totals", () => {
    open();
    expect(screen.getByRole("grid", { name: "Orders" })).toBeTruthy();
    expect(grid().getAttribute("aria-rowcount")).toBe(String(3 + 30 + 1 + 1));
    expect(cellText(0, 0)).toBe("Paper");
    expect(cellText(1, 2)).toBe("€39.00");
    expect(cellText(0, 3)).toBe("€22.00");
    expect(screen.getByTestId("sheet-total-1").textContent).toContain("16");
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent?.trim())).toEqual(["", "Item", "Qty", "Price", "Amount"]);
  });

  it("moves with the arrow keys, extends with Shift and labels the active cell", () => {
    open();
    expect(address()).toBe("A1");
    key("ArrowRight");
    key("ArrowDown");
    expect(address()).toBe("B2");
    expect(field().getAttribute("aria-label")).toBe("B2, Qty: 2");
    key("ArrowDown", { shiftKey: true });
    key("ArrowRight", { shiftKey: true });
    const selected = grid().querySelectorAll('[role="gridcell"][aria-selected="true"]');
    expect(selected).toHaveLength(4);
    key("Escape");
    expect(grid().querySelectorAll('[role="gridcell"][aria-selected="true"]')).toHaveLength(1);
    key("ArrowDown", { ctrlKey: true });
    expect(address()).toBe("B3"); // the end of the filled block
    key("Home", { ctrlKey: true });
    expect(address()).toBe("A1");
  });

  it("types over a cell, commits with Enter as one undo step and moves down", () => {
    open();
    key("ArrowRight");
    type("7");
    expect(field().value).toBe("7");
    key("Enter");
    expect(cellText(0, 1)).toBe("7");
    expect(cellText(0, 3)).toBe("€38.50"); // the formula follows
    expect(address()).toBe("B2");
    expect(screen.getByTestId("node-editor-undo").getAttribute("aria-label")).toBe("Undo: Edit cell");
    undoKeys();
    expect(cellText(0, 1)).toBe("4");
    key("y", { ctrlKey: true });
    expect(cellText(0, 1)).toBe("7");
  });

  it("edits the value with F2, cancels with Escape and commits with Tab", () => {
    open();
    key("F2");
    expect(field().value).toBe("Paper");
    field().value = "Paper A4";
    fireEvent.input(field());
    key("Escape");
    expect(cellText(0, 0)).toBe("Paper");
    key("F2");
    field().value = "Paper A4";
    fireEvent.input(field());
    key("Tab");
    expect(cellText(0, 0)).toBe("Paper A4");
    expect(address()).toBe("B1");
  });

  it("types below the data into the empty rows offered there", () => {
    open();
    for (let i = 0; i < 4; i += 1) key("ArrowDown");
    expect(address()).toBe("A5");
    type("Ink");
    key("Enter");
    expect(cellText(4, 0)).toBe("Ink");
    expect(cellText(3, 0)).toBe("");
  });

  it("refuses typing into a formula column and says why", () => {
    open();
    key("End");
    type("5");
    expect(field().value).toBe("");
    expect(screen.getByTestId("sheet-status").textContent).toMatch(/computed by its formula/);
  });

  it("clears the selection with Delete, as one step", () => {
    open();
    key("ArrowDown", { shiftKey: true });
    key("Delete");
    expect(cellText(0, 0)).toBe("");
    expect(cellText(1, 0)).toBe("");
    undoKeys();
    expect(cellText(0, 0)).toBe("Paper");
    expect(cellText(1, 0)).toBe("Toner");
  });

  it("toggles a yes/no cell with Space", () => {
    open({ sheets: [{ name: "S", columns: [{ key: "done", label: "Done", type: "check" }], rows: [{ done: false }] }] });
    key(" ");
    expect(grid().querySelector('[data-row="0"][data-col="0"] [role="img"]')?.getAttribute("aria-label")).toBe("✓");
  });
});

describe("the clipboard", () => {
  it("copies the selection as tab-separated text", () => {
    open();
    key("ArrowDown", { shiftKey: true });
    key("ArrowRight", { shiftKey: true });
    const data: Record<string, string> = {};
    fireEvent.copy(field(), { clipboardData: { setData: (type: string, value: string) => (data[type] = value) } });
    expect(data["text/plain"]).toBe("Paper\t4\nToner\t2");
  });

  it("pastes a block from another app, adding the columns it needs", () => {
    open();
    key("ArrowRight");
    key("ArrowRight");
    key("ArrowRight"); // Amount (a formula column: skipped)
    key("ArrowLeft");
    fireEvent.paste(field(), { clipboardData: { getData: () => "1.5\t\tx\r\n2\t\ty\r\n" } });
    expect(cellText(0, 2)).toBe("€1.50");
    expect(cellText(1, 2)).toBe("€2.00");
    expect(screen.getAllByRole("columnheader")).toHaveLength(6); // one column added for "x"
    expect(cellText(0, 4)).toBe("x");
    expect(screen.getByTestId("sheet-status").textContent).toMatch(/1 column/);
    undoKeys();
    expect(screen.getAllByRole("columnheader")).toHaveLength(5);
    expect(cellText(0, 2)).toBe("€5.50");
  });

  it("fills one pasted value into the whole selection", () => {
    open();
    key("ArrowRight");
    key("ArrowDown", { shiftKey: true });
    key("ArrowDown", { shiftKey: true });
    fireEvent.paste(field(), { clipboardData: { getData: () => "9" } });
    expect([cellText(0, 1), cellText(1, 1), cellText(2, 1)]).toEqual(["9", "9", "9"]);
  });

  it("cuts: copies and clears", () => {
    open();
    const data: Record<string, string> = {};
    fireEvent.cut(field(), { clipboardData: { setData: (type: string, value: string) => (data[type] = value) } });
    expect(data["text/plain"]).toBe("Paper");
    expect(cellText(0, 0)).toBe("");
  });
});

describe("rows, columns and fill", () => {
  it("inserts and deletes rows from the context menu", () => {
    open();
    key("ArrowDown");
    fireEvent.contextMenu(grid().querySelector('[data-row="1"][data-col="0"]') as Element);
    fireEvent.click(screen.getByTestId("sheet-menu-insert-above"));
    expect(cellText(1, 0)).toBe("");
    expect(cellText(2, 0)).toBe("Toner");
    key("ArrowDown");
    key("ArrowDown", { shiftKey: true });
    fireEvent.contextMenu(grid().querySelector('[data-row="2"][data-col="0"]') as Element);
    fireEvent.click(screen.getByTestId("sheet-menu-delete-rows"));
    expect(cellText(2, 0)).toBe("");
    expect(cellText(0, 0)).toBe("Paper");
  });

  it("inserts a column from the column menu and refuses to delete one a formula reads", () => {
    open();
    fireEvent.click(screen.getByTestId("sheet-head-menu-0"));
    fireEvent.click(screen.getByTestId("sheet-menu-insert-right"));
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent?.trim())).toEqual(["", "Item", "E", "Qty", "Price", "Amount"]);
    fireEvent.click(screen.getByTestId("sheet-head-menu-2"));
    fireEvent.click(screen.getByTestId("sheet-menu-delete"));
    expect(screen.getByTestId("sheet-status").textContent).toMatch(/Used in the formula of: Amount/);
    expect(screen.getAllByRole("columnheader")).toHaveLength(6);
  });

  it("fills down with Ctrl+D", () => {
    open();
    key("ArrowRight");
    key("ArrowDown", { shiftKey: true });
    key("ArrowDown", { shiftKey: true });
    key("d", { ctrlKey: true });
    expect([cellText(0, 1), cellText(1, 1), cellText(2, 1)]).toEqual(["4", "4", "4"]);
    expect(screen.getByTestId("node-editor-undo").getAttribute("aria-label")).toBe("Undo: Fill down");
  });
});

describe("sort, filter and number format", () => {
  it("sorts the stored rows by the active column (formula values too)", () => {
    open();
    key("End");
    fireEvent.click(screen.getByTestId("sheet-sort-desc"));
    expect([cellText(0, 0), cellText(1, 0), cellText(2, 0)]).toEqual(["Toner", "Paper", "Pens"]);
    expect(screen.getByTestId("node-editor-undo").getAttribute("aria-label")).toBe("Undo: Sort by Amount");
  });

  it("filters rows from view without changing the spec", () => {
    open();
    fireEvent.click(screen.getByTestId("sheet-filter-button"));
    const panel = screen.getByTestId("sheet-filter");
    fireEvent.click(within(panel).getByLabelText(/^Toner/));
    fireEvent.click(within(panel).getByTestId("sheet-filter-apply"));
    expect(cellText(0, 0)).toBe("Paper");
    expect(cellText(1, 0)).toBe("Pens");
    expect(screen.getByTestId("sheet-filter-count").textContent).toBe("2 of 3 rows shown");
    expect((screen.getByTestId("node-editor-undo") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId("sheet-filter-clear"));
    expect(cellText(1, 0)).toBe("Toner");
  });

  it("changes decimals of a number column from the toolbar", () => {
    open();
    key("ArrowRight");
    fireEvent.click(screen.getByTestId("sheet-decimals-up"));
    expect(cellText(0, 1)).toBe("4.0");
    fireEvent.click(screen.getByTestId("sheet-decimals-down"));
    expect(cellText(0, 1)).toBe("4");
  });
});

describe("charts and sheets", () => {
  it("inserts a chart from the selection, bound to its columns, and saves it", async () => {
    open();
    key("ArrowDown", { shiftKey: true });
    key("ArrowRight", { shiftKey: true });
    key("ArrowRight", { shiftKey: true });
    key("ArrowRight", { shiftKey: true });
    fireEvent.click(screen.getByTestId("sheet-insert-chart"));
    expect(chartDialog.last?.source?.columns.map((c) => c.key)).toEqual(["item", "qty", "price", "amount"]);
    expect(chartDialog.last?.source?.rows).toEqual([
      ["Paper", 4, 5.5, 22],
      ["Toner", 2, 39, 78],
    ]);
    fireEvent.click(screen.getByTestId("chart-stand-in-save"));
    expect(screen.getByTestId("chart-preview").textContent).toBe("4,2");
    await act(async () => {
      fireEvent.click(screen.getByTestId("node-editor-done"));
    });
    await waitFor(() => expect(saved.length).toBeGreaterThan(0));
    expect(saved.at(-1)?.sheets[0].charts).toEqual([
      { type: "column", title: "Amounts", x: "item", series: [{ column: "qty" }], rows: [1, 2] },
    ]);
  });

  it("adds, renames and switches sheets from the tabs", () => {
    open();
    fireEvent.click(screen.getByTestId("sheet-tab-add"));
    expect(screen.getByTestId("sheet-tab-1").textContent).toBe("Sheet 2");
    expect(screen.getByRole("grid", { name: "Sheet 2" })).toBeTruthy();
    fireEvent.doubleClick(screen.getByTestId("sheet-tab-1"));
    const input = screen.getByLabelText("Rename sheet") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Totals" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("sheet-tab-1").textContent).toBe("Totals");
    fireEvent.click(screen.getByTestId("sheet-tab-0"));
    expect(screen.getByRole("grid", { name: "Orders" })).toBeTruthy();
    expect(screen.getByTestId("node-editor-undo").getAttribute("aria-label")).toBe("Undo: Rename sheet");
  });

  it("saves the person's work by itself, as a spec the server keeps", async () => {
    open();
    type("Paper A3");
    key("Enter");
    await waitFor(() => expect(saved.length).toBe(1), { timeout: 3_000 });
    expect(saved[0].sheets[0].rows[0]).toEqual({ item: "Paper A3", qty: 4, price: 5.5 });
    expect(saved[0].sheets[0].rows).toHaveLength(3);
  });
});
