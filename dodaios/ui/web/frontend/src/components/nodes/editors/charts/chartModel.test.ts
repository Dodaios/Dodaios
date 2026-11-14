import { describe, expect, it } from "vitest";

import {
  MAX_SLICES,
  chartFromSource,
  guessBinding,
  isNumericColumn,
  starterChart,
  validateChart,
  type ChartSource,
} from "./chartModel";

describe("validateChart mirrors parse_chart", () => {
  it("accepts the starter and every kind, cleaning texts", () => {
    for (const kind of ["column", "bar", "line", "area", "pie", "donut"] as const) {
      const check = validateChart(starterChart(kind));
      expect(check.errors).toEqual([]);
      expect(check.chart?.type).toBe(kind);
    }
    const check = validateChart({ type: "Columns", title: "  Sales   by  month ", x: ["a", "b"], data: [1, "2.5"] });
    expect(check.chart).toEqual({ type: "column", title: "Sales by month", x: ["a", "b"], series: [{ name: "Sales by month", data: [1, 2.5] }] });
    expect(validateChart({ type: "doughnut", x: ["a", "b"], data: [1, 2] }).chart?.type).toBe("donut");
  });

  it("names every problem", () => {
    expect(validateChart(null).errors).toEqual(["not_object"]);
    expect(validateChart({ type: "radar", x: ["a", "b"], data: [1, 2] }).errors).toEqual(["type"]);
    expect(validateChart({ type: "line", x: ["a"], data: [1] }).errors).toContain("labels_count");
    expect(validateChart({ type: "line", x: ["a", ""], data: [1, 2] }).errors).toContain("label_empty");
    expect(validateChart({ type: "line", x: ["a", "b"], series: [] }).errors).toContain("series_count");
    expect(validateChart({ type: "line", x: ["a", "b"], data: [1] }).errors).toContain("series_length");
    expect(validateChart({ type: "line", x: ["a", "b"], data: [1, "x"] }).errors).toContain("value");
    expect(validateChart({ type: "line", x: ["a", "b"], data: [null, null] }).errors).toContain("series_empty");
    expect(
      validateChart({ type: "line", x: ["a", "b"], series: [{ name: "A", data: [1, 2] }, { name: "", data: [1, 2] }] }).errors,
    ).toContain("series_name");
    expect(validateChart({ type: "bar", x: Array.from({ length: 25 }, (_, n) => `r${n}`), data: Array(25).fill(1) }).errors).toContain(
      "labels_count",
    );
  });

  it("holds a pie or donut to one series of shares, at most twelve", () => {
    const two = [
      { name: "A", data: [1, 2] },
      { name: "B", data: [1, 2] },
    ];
    expect(validateChart({ type: "pie", x: ["a", "b"], series: two }).errors).toContain("round_one_series");
    expect(validateChart({ type: "pie", x: ["a", "b"], data: [1, -1] }).errors).toEqual(["round_negative"]);
    expect(validateChart({ type: "donut", x: ["a", "b"], data: [0, null] }).errors).toEqual(["round_zero"]);
    const many = Array.from({ length: MAX_SLICES + 1 }, (_, n) => `s${n}`);
    expect(validateChart({ type: "pie", x: many, data: many.map(() => 1) }).errors).toEqual(["labels_count"]);
    expect(validateChart({ type: "pie", x: ["a", "b"], data: [3, null] }).chart?.series[0].data).toEqual([3, null]);
  });

  it("keeps stacked only where it means something, and colours per slot", () => {
    const stacked = validateChart({
      type: "column",
      stacked: true,
      x: ["a", "b"],
      series: [
        { name: "A", data: [1, 2] },
        { name: "B", data: [3, 4] },
      ],
      colors: ["#ff0000", "nope", "#00ff00"],
    }).chart;
    expect(stacked?.stacked).toBe(true);
    expect(stacked?.colors).toEqual(["#FF0000", ""]);
    expect(validateChart({ type: "line", stacked: true, x: ["a", "b"], data: [1, 2] }).chart?.stacked).toBeUndefined();
    const pie = validateChart({ type: "pie", x: ["a", "b", "c"], data: [1, 2, 3], colors: ["", "#123456"] }).chart;
    expect(pie?.colors).toEqual(["", "#123456", ""]);
    expect(validateChart({ type: "pie", x: ["a", "b"], data: [1, 2], colors: ["x"] }).chart?.colors).toBeUndefined();
  });
});

describe("charts from a table", () => {
  const source: ChartSource = {
    columns: [
      { key: "month", label: "Month" },
      { key: "north", label: "North" },
      { key: "south", label: "South" },
      { key: "note", label: "Note" },
    ],
    rows: [
      ["Jan", 10, "1,200", "ok"],
      ["Feb", 12, "", "late"],
      ["Mar", "13.5", "900", ""],
    ],
  };

  it("tells number columns from text columns and guesses a binding", () => {
    expect([0, 1, 2, 3].map((index) => isNumericColumn(source, index))).toEqual([false, true, true, false]);
    expect(guessBinding(source)).toEqual({ x: "month", series: ["north", "south"] });
  });

  it("takes labels and series along the binding, gaps for empty cells", () => {
    const chart = chartFromSource({ type: "column", title: "T", x: [], series: [] }, source, { x: "month", series: ["north", "south"] });
    expect(chart.x).toEqual(["Jan", "Feb", "Mar"]);
    expect(chart.series).toEqual([
      { name: "North", data: [10, 12, 13.5] },
      { name: "South", data: [1200, null, 900] },
    ]);
    expect(validateChart(chart).errors).toEqual([]);
    const pie = chartFromSource({ type: "pie", x: [], series: [] }, source, { x: "month", series: ["north", "south"] });
    expect(pie.series).toHaveLength(1);
  });
});
