/**
 * The Analytics editor on its own, with the network stubbed and the chart
 * editor and chart drawing replaced by stand-ins (the real ones are tested
 * where they live).
 *
 * Contracts worth pinning:
 * - the dashboard opens with every section, tile, chart and table of its spec,
 * - typing a value is one undo step, and the save sends the edited spec,
 * - tiles, charts and tables are added, moved (from the keyboard), duplicated
 *   and deleted, and the last part of the dashboard cannot be deleted,
 * - the inspector's "lower is better" and "full width" change the spec,
 * - a new chart comes from the chart editor; an edited chart keeps its width,
 * - a tile without a label holds the save with the reason instead of failing,
 * - a typed number is saved as a number; cells pasted from a spreadsheet
 *   grow the table,
 * - a kept-current dashboard says what its refresh does to values typed by hand
 *   (its status line is the stage's upkeep bar above the editor).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import type { NodeCard } from "../../nodeModel";

vi.mock("../charts/ChartPreview", () => ({
  ChartPreview: ({ chart }: { chart: { title?: string } }) => <div data-testid="chart-preview">{chart.title}</div>,
}));
vi.mock("../charts/ChartEditor", () => ({
  ChartEditor: ({
    open,
    value,
    onSave,
    onCancel,
  }: {
    open: boolean;
    value?: Record<string, unknown> | null;
    onSave: (chart: Record<string, unknown>, binding: null) => void;
    onCancel: () => void;
  }) =>
    open ? (
      <div data-testid="chart-editor">
        <span data-testid="chart-editor-title">{String(value?.title ?? "")}</span>
        <button type="button" onClick={() => onSave({ type: "line", title: "Saved chart", x: ["a", "b"], series: [{ name: "", data: [1, 2] }] }, null)}>
          save-chart
        </button>
        <button type="button" onClick={onCancel}>
          cancel-chart
        </button>
      </div>
    ) : null,
}));

import DataEditor from "./index";

const SPEC = {
  summary: "Sales through October.",
  sources: ["orders.csv"],
  sections: [
    {
      title: "October",
      text: "",
      metrics: [
        { label: "Revenue", value: "48.2k €", delta: "+12 %" },
        { label: "Orders", value: "1,204" },
      ],
      charts: [{ type: "column", title: "By month", x: ["a", "b"], series: [{ name: "", data: [1, 2] }], wide: true }],
      tables: [{ title: "Top", columns: ["Product", "Units"], rows: [["Filter", 412]] }],
    },
  ],
};

function card(over: Partial<NodeCard> = {}): NodeCard {
  return {
    key: "k",
    id: "n1",
    type: "data",
    origin: "node",
    title: "Sales 2026",
    slug: "2026__node__n1",
    path: "index.html",
    visual_kind: "page",
    created_at: 1,
    updated_at: Math.floor(Date.now() / 1000) - 120,
    size: 0,
    version: 1,
    status: "ready",
    kept_current: false,
    refreshing: false,
    every_minutes: 0,
    request: "",
    preview: null,
    ...over,
  };
}

let puts: Array<{ spec: Record<string, unknown>; base_version: number }> = [];

beforeEach(() => {
  puts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/spec") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        puts.push(body);
        return new Response(JSON.stringify({ version: body.base_version + 1, updated_at: 200 + puts.length, spec: body.spec }), { status: 200 });
      }
      if (url.endsWith("/preview")) return new Response("<!doctype html><html><head></head><body><main>page</main></body></html>", { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function open(spec: unknown = SPEC, over: Partial<NodeCard> = {}) {
  const onDone = vi.fn();
  render(<DataEditor node={card(over)} initial={{ spec: structuredClone(spec), version: 1, updated_at: 100 }} onDone={onDone} />);
  return { onDone };
}

const lastSaved = () => puts[puts.length - 1]!.spec as typeof SPEC;
/** The charts on the canvas (the inspector draws the selected one again). */
const canvasCharts = () => screen.getAllByTestId("data-chart").map((tile) => within(tile).getByTestId("chart-preview").textContent);
const labels = () => screen.getAllByTestId("data-metric-label").map((input) => (input as HTMLInputElement).value);

describe("DataEditor", () => {
  it("opens with every part of the dashboard", () => {
    open();
    expect((screen.getByTestId("data-summary") as HTMLTextAreaElement).value).toBe("Sales through October.");
    expect(screen.getByText("orders.csv")).toBeTruthy();
    expect(labels()).toEqual(["Revenue", "Orders"]);
    expect(screen.getByTestId("chart-preview").textContent).toBe("By month");
    expect(screen.getByTestId("data-table-grid")).toBeTruthy();
    expect(screen.queryByTestId("data-upkeep-note")).toBeNull();
  });

  it("makes a run of typing one undo step and saves the edited spec", async () => {
    open();
    const value = screen.getAllByTestId("data-metric-value")[0]!;
    fireEvent.change(value, { target: { value: "50" } });
    fireEvent.change(value, { target: { value: "50.1k €" } });
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(lastSaved().sections[0]!.metrics[0]!.value).toBe("50.1k €");
    expect(puts[0]!.base_version).toBe(1);

    fireEvent.click(screen.getByTestId("node-editor-undo"));
    expect((screen.getAllByTestId("data-metric-value")[0] as HTMLInputElement).value).toBe("48.2k €");
    expect((screen.getByTestId("node-editor-undo") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByTestId("node-editor-redo"));
    expect((screen.getAllByTestId("data-metric-value")[0] as HTMLInputElement).value).toBe("50.1k €");
  });

  it("adds a metric to the selected section and selects it", () => {
    open();
    fireEvent.click(screen.getByTestId("data-add-metric"));
    expect(labels()).toEqual(["Revenue", "Orders", "New metric"]);
    const tiles = screen.getAllByTestId("data-metric");
    expect(tiles[2]!.getAttribute("data-selected")).toBe("true");
    expect(screen.getByTestId("data-inspector-metric")).toBeTruthy();
  });

  it("moves a tile with the arrow keys on its handle", () => {
    open();
    const grip = screen.getByRole("button", { name: /Move Revenue \(drag/ });
    fireEvent.keyDown(grip, { key: "ArrowRight" });
    expect(labels()).toEqual(["Orders", "Revenue"]);
    fireEvent.keyDown(screen.getByRole("button", { name: /Move Revenue \(drag/ }), { key: "ArrowLeft" });
    expect(labels()).toEqual(["Revenue", "Orders"]);
  });

  it("duplicates and deletes with the keyboard on a selected tile", () => {
    open();
    fireEvent.mouseDown(screen.getAllByTestId("data-metric")[1]!);
    const canvas = screen.getByTestId("data-canvas");
    fireEvent.keyDown(canvas, { key: "d", metaKey: true });
    expect(labels()).toEqual(["Revenue", "Orders", "Orders"]);
    fireEvent.keyDown(canvas, { key: "Delete" });
    expect(labels()).toEqual(["Revenue", "Orders"]);
  });

  it("keeps the dashboard's last part", () => {
    open({ sections: [{ metrics: [{ label: "Only", value: "1" }] }] });
    fireEvent.mouseDown(screen.getByTestId("data-metric"));
    const keep = screen.getAllByRole("button", { name: "The dashboard keeps at least one metric, chart or table" });
    expect(keep.every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    fireEvent.keyDown(screen.getByTestId("data-canvas"), { key: "Delete" });
    expect(labels()).toEqual(["Only"]);
  });

  it("flips a delta's reading from the inspector", async () => {
    open();
    fireEvent.mouseDown(screen.getAllByTestId("data-metric")[0]!);
    fireEvent.click(screen.getByTestId("data-metric-lower"));
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(lastSaved().sections[0]!.metrics[0]).toMatchObject({ label: "Revenue", better: "lower" });
  });

  it("adds a chart through the chart editor and keeps an edited chart's width", () => {
    open();
    fireEvent.click(screen.getByTestId("data-add-chart"));
    expect(screen.getByTestId("chart-editor-title").textContent).toBe("New chart");
    fireEvent.click(screen.getByText("save-chart"));
    expect(canvasCharts()).toEqual(["By month", "Saved chart"]);

    fireEvent.click(screen.getAllByTestId("data-chart-edit")[0]!);
    expect(screen.getByTestId("chart-editor-title").textContent).toBe("By month");
    fireEvent.click(screen.getByText("save-chart"));
    expect(canvasCharts()).toEqual(["Saved chart", "Saved chart"]);
    // The first chart was full width and stays so.
    expect(screen.getAllByTestId("data-chart")[0]!.className).toContain("xl:col-span-2");

    fireEvent.click(screen.getByTestId("data-add-chart"));
    fireEvent.click(screen.getByText("cancel-chart"));
    expect(canvasCharts()).toHaveLength(2);
  });

  it("holds the save while a tile has no label, with the reason", async () => {
    open();
    fireEvent.change(screen.getAllByTestId("data-metric-label")[0]!, { target: { value: "" } });
    await waitFor(() => expect(screen.getByTestId("node-editor-save-state").getAttribute("data-state")).toBe("held"), { timeout: 3000 });
    expect(screen.getByTestId("node-editor-save-state").textContent).toContain("needs a label and a value");
    expect(puts).toHaveLength(0);
    expect(screen.getAllByTestId("data-metric-label")[0]!.getAttribute("aria-invalid")).toBe("true");
  });

  it("saves a typed number as a number and grows the table on a paste", async () => {
    open();
    const grid = screen.getByTestId("data-table-grid");
    const cell = within(grid).getByLabelText("Units, row 1");
    fireEvent.change(cell, { target: { value: "500" } });
    const first = within(grid).getByLabelText("Product, row 1");
    fireEvent.paste(first, { clipboardData: { getData: () => "Bottle\t388\nCarafe\t97.5" } });
    expect(within(grid).getAllByRole("row")).toHaveLength(3); // the head and two rows
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect(lastSaved().sections[0]!.tables[0]!.rows).toEqual([
      ["Bottle", 388],
      ["Carafe", 97.5],
    ]);
  });

  it("adds a row and a column to a table", () => {
    open();
    fireEvent.click(screen.getByTestId("data-table-add-row"));
    fireEvent.click(screen.getByTestId("data-table-add-column"));
    const grid = screen.getByTestId("data-table-grid");
    expect(within(grid).getAllByRole("row")).toHaveLength(3);
    expect(within(grid).getAllByRole("columnheader")).toHaveLength(4); // three columns and the add button
  });

  it("says what a kept-current dashboard's refresh does to hand edits", () => {
    open(SPEC, { kept_current: true, refreshing: true, every_minutes: 60 });
    expect(screen.getByTestId("data-upkeep-note").textContent).toContain("refreshed every");
  });

  it("edits the named sources in the inspector", async () => {
    open();
    const input = screen.getByTestId("data-source-input");
    fireEvent.change(input, { target: { value: "returns.xlsx" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("returns.xlsx")).toBeTruthy();
    await waitFor(() => expect(puts.length).toBeGreaterThan(0), { timeout: 3000 });
    expect((lastSaved() as { sources?: string[] }).sources).toEqual(["orders.csv", "returns.xlsx"]);
  });

  it("shows the real page on demand", async () => {
    open();
    await act(async () => {
      fireEvent.click(screen.getByTestId("data-view-page"));
    });
    await waitFor(() => expect(screen.getByTestId("node-preview-frame").getAttribute("srcdoc")).toContain("page"), { timeout: 3000 });
  });
});
