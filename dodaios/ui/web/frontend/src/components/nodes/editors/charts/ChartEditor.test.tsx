import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { ChartEditor, ChartEditorPanel, chartOf, draftOf, parseTsv } from "./ChartEditor";
import { validateChart, type ChartJson, type ChartSource } from "./chartModel";

class ChartResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

beforeEach(() => {
  vi.stubGlobal("ResizeObserver", ChartResizeObserver);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const SALES: ChartJson = {
  type: "column",
  title: "Sales",
  unit: "€",
  x: ["Q1", "Q2", "Q3"],
  series: [
    { name: "North", data: [10, 12, 9] },
    { name: "South", data: [7, null, 11] },
  ],
};

function cell(label: string): HTMLInputElement {
  return screen.getByLabelText(label) as HTMLInputElement;
}

describe("the chart editor's draft", () => {
  it("round-trips a chart through the typed draft", () => {
    const back = validateChart(chartOf(draftOf(SALES)));
    expect(back.chart).toEqual(SALES);
  });

  it("reads typed numbers with a decimal comma or thousands separators", () => {
    const draft = draftOf(SALES);
    draft.series[0].cells = ["1,5", "1,234.5", " 7 "];
    expect(validateChart(chartOf(draft)).chart?.series[0].data).toEqual([1.5, 1234.5, 7]);
  });

  it("reads a pasted block as rows of tab-separated cells", () => {
    expect(parseTsv("a\t1\r\nb\t2\n")).toEqual([
      ["a", "1"],
      ["b", "2"],
    ]);
  });
});

describe("ChartEditorPanel", () => {
  it("edits a chart and hands back exactly what parse_chart reads", () => {
    const onSave = vi.fn();
    render(<ChartEditorPanel value={SALES} onSave={onSave} onCancel={() => {}} />);
    expect(screen.getByTestId("chart-preview").getAttribute("data-kind")).toBe("column");
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: "Revenue" } });
    fireEvent.change(cell("North at Q2"), { target: { value: "20" } });
    fireEvent.click(screen.getByTestId("chart-stacked"));
    fireEvent.click(screen.getByTestId("chart-save"));
    expect(onSave).toHaveBeenCalledWith(
      {
        ...SALES,
        title: "Revenue",
        stacked: true,
        series: [
          { name: "North", data: [10, 20, 9] },
          { name: "South", data: [7, null, 11] },
        ],
      },
      null,
    );
  });

  it("says what is wrong and refuses to save a chart that would not draw", () => {
    const onSave = vi.fn();
    render(<ChartEditorPanel value={SALES} onSave={onSave} onCancel={() => {}} />);
    fireEvent.change(cell("Label 2"), { target: { value: "" } });
    fireEvent.change(cell("South at Q3"), { target: { value: "lots" } });
    const errors = screen.getByTestId("chart-errors").textContent ?? "";
    expect(errors).toContain("Every label needs a text.");
    expect(errors).toContain("Values must be numbers");
    expect((screen.getByTestId("chart-save") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.queryByTestId("chart-preview")).toBeNull();
  });

  it("turns into a pie with one series and colours per slice", () => {
    const onSave = vi.fn();
    render(<ChartEditorPanel value={SALES} onSave={onSave} onCancel={() => {}} />);
    fireEvent.click(screen.getByTestId("chart-kind-pie"));
    expect(screen.getByTestId("chart-kind-pie").getAttribute("aria-checked")).toBe("true");
    expect(screen.queryByTestId("chart-stacked")).toBeNull();
    expect(screen.queryByTestId("chart-add-series")).toBeNull();
    expect(screen.queryByLabelText("Name of series 2")).toBeNull();
    expect(screen.getByText("Slice colours")).toBeTruthy();
    expect(screen.getByTestId("chart-preview").getAttribute("data-kind")).toBe("pie");
    fireEvent.click(screen.getByTestId("chart-save"));
    expect(onSave.mock.calls[0][0]).toMatchObject({ type: "pie", series: [{ name: "North", data: [10, 12, 9] }] });
    expect(onSave.mock.calls[0][0].stacked).toBeUndefined();
  });

  it("refuses a donut with a negative share", () => {
    render(<ChartEditorPanel value={{ ...SALES, type: "donut", series: [SALES.series[0]] }} onSave={() => {}} onCancel={() => {}} />);
    fireEvent.change(cell("North at Q1"), { target: { value: "-3" } });
    expect(screen.getByTestId("chart-errors").textContent).toContain("cannot show negative values");
  });

  it("adds and removes rows and series", () => {
    const onSave = vi.fn();
    render(<ChartEditorPanel onSave={onSave} onCancel={() => {}} />);
    expect(screen.getByText("New chart")).toBeTruthy();
    fireEvent.click(screen.getByTestId("chart-add-row"));
    fireEvent.change(cell("Label 5"), { target: { value: "Q5" } });
    fireEvent.change(cell("Series 1 at Q5"), { target: { value: "30" } });
    fireEvent.click(screen.getByTestId("chart-add-series"));
    fireEvent.change(cell("Series 2 at Q1"), { target: { value: "1" } });
    fireEvent.click(screen.getByLabelText("Remove row Q2"));
    fireEvent.click(screen.getByTestId("chart-save"));
    const chart = onSave.mock.calls[0][0] as ChartJson;
    expect(chart.x).toEqual(["Q1", "Q3", "Q4", "Q5"]);
    expect(chart.series.map((series) => series.data)).toEqual([
      [12, 15, 22, 30],
      [1, null, null, null],
    ]);
  });

  it("fills the grid from a block pasted out of a spreadsheet app", () => {
    const onSave = vi.fn();
    render(<ChartEditorPanel onSave={onSave} onCancel={() => {}} />);
    fireEvent.paste(cell("Label 1"), {
      clipboardData: { getData: () => "Mon\t3\t4\nTue\t5\t6\nWed\t7\t8\nThu\t1\t1\nFri\t2\t2\n" },
    });
    fireEvent.change(cell("Name of series 2"), { target: { value: "Late" } });
    fireEvent.click(screen.getByTestId("chart-save"));
    const chart = onSave.mock.calls[0][0] as ChartJson;
    expect(chart.x).toEqual(["Mon", "Tue", "Wed", "Thu", "Fri"]);
    expect(chart.series).toEqual([
      { name: "Series 1", data: [3, 5, 7, 1, 2] },
      { name: "Late", data: [4, 6, 8, 1, 2] },
    ]);
  });

  it("takes the data from a source table and hands back the columns it used", () => {
    const source: ChartSource = {
      columns: [
        { key: "c0", label: "Region" },
        { key: "c1", label: "Units" },
        { key: "c2", label: "Revenue" },
      ],
      rows: [
        ["East", 3, 300],
        ["West", 5, 520],
      ],
    };
    const onSave = vi.fn();
    render(<ChartEditorPanel source={source} onSave={onSave} onCancel={() => {}} />);
    // The grid gives way to the column choice.
    expect(screen.queryByTestId("chart-add-row")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: "Units" }));
    fireEvent.click(screen.getByTestId("chart-save"));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ x: ["East", "West"], series: [{ name: "Revenue", data: [300, 520] }] }),
      { x: "c0", series: ["c2"] },
    );
  });

  it("reopens with the binding it was given", () => {
    const source: ChartSource = {
      columns: [
        { key: "a", label: "Name" },
        { key: "b", label: "One" },
        { key: "c", label: "Two" },
      ],
      rows: [
        ["x", 1, 2],
        ["y", 3, 4],
      ],
    };
    render(<ChartEditorPanel source={source} binding={{ x: "a", series: ["c"] }} onSave={() => {}} onCancel={() => {}} />);
    expect((screen.getByRole("checkbox", { name: "One" }) as HTMLInputElement).checked).toBe(false);
    expect((screen.getByRole("checkbox", { name: "Two" }) as HTMLInputElement).checked).toBe(true);
  });
});

describe("ChartEditor dialog", () => {
  it("opens over the editor, keeps its own undo keys, and cancels", () => {
    const onCancel = vi.fn();
    render(<ChartEditor open value={SALES} onSave={() => {}} onCancel={onCancel} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog.hasAttribute("data-own-undo")).toBe(true);
    expect(within(dialog).getByText("Edit chart", { selector: "h2:not(.sr-only)" })).toBeTruthy();
    fireEvent.click(within(dialog).getByTestId("chart-cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("renders nothing while closed", () => {
    render(<ChartEditor open={false} onSave={() => {}} onCancel={() => {}} />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
