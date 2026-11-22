import { afterEach, describe, expect, it, vi } from "vitest";

import { readDashSpec } from "../../editors/data/dashboardModel";
import { dataEntries, dataReveal } from "./data";
import { chartSignature, countText, formatFigure, motionSpan, parseFigure, Run } from "./dataMotion";

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

const spec = (sections: unknown[], summary = "") => readDashSpec({ summary, sections });
const section = (extra: Record<string, unknown> = {}) => ({ title: "Sales", text: "", metrics: [], charts: [], tables: [], ...extra });

describe("which cards play", () => {
  it("plays everything in reading order when nothing was there before", () => {
    const next = spec(
      [
        section({
          metrics: [{ label: "Revenue", value: "10" }],
          charts: [{ type: "column", x: ["a"], series: [{ name: "s", data: [1] }] }],
          tables: [{ title: "T", columns: ["a"], rows: [["1"]] }],
        }),
      ],
      "A summary",
    );
    expect(dataEntries(null, next).map((e) => e.path)).toEqual([
      "/summary",
      "/sections/0/title",
      "/sections/0/metrics/0",
      "/sections/0/charts/0",
      "/sections/0/tables/0",
    ]);
  });

  it("plays only the cards that changed", () => {
    const before = spec([section({ metrics: [{ label: "A", value: "1" }, { label: "B", value: "2" }] })]);
    const after = spec([section({ metrics: [{ label: "A", value: "1" }, { label: "B", value: "3" }] })]);
    const entries = dataEntries(before, after);
    expect(entries.map((e) => e.path)).toEqual(["/sections/0/metrics/1"]);
    expect(entries[0].before).toMatchObject({ value: "2" });
  });

  it("plays a new section's heading before its cards", () => {
    const before = spec([section()]);
    const after = spec([section(), section({ title: "Costs", metrics: [{ label: "Rent", value: "5" }] })]);
    expect(dataEntries(before, after).map((e) => e.path)).toEqual(["/sections/1/title", "/sections/1/metrics/0"]);
  });
});

describe("figures", () => {
  it("reads prefix, number and suffix", () => {
    expect(parseFigure("$1,240.50")).toMatchObject({ prefix: "$", value: 1240.5, decimals: 2, grouped: true });
    expect(parseFigure("98%")).toMatchObject({ value: 98, suffix: "%" });
    expect(parseFigure("n/a")).toBeNull();
  });

  it("reads a decimal comma and a thousands dot", () => {
    expect(parseFigure("48,2k €")).toMatchObject({ value: 48.2, decimals: 1, suffix: "k €", decimal: "," });
    expect(parseFigure("1.204")).toMatchObject({ value: 1204, decimals: 0, grouped: true, group: "." });
    expect(parseFigure("1.234,56 €")).toMatchObject({ value: 1234.56, decimals: 2, group: ".", decimal: "," });
    expect(parseFigure("0.125")).toMatchObject({ value: 0.125, decimals: 3 });
    expect(parseFigure("1,240")).toMatchObject({ value: 1240, grouped: true });
  });

  it("counts a figure in its own way of writing, never through a wrong magnitude", () => {
    const mid = countText(null, "48,2k €", 0.5)!;
    expect(mid).toMatch(/^\d{1,2},\dk €$/);
    expect(Number(mid.replace("k €", "").replace(",", "."))).toBeLessThan(48.2);
    const orders = countText(null, "1.204", 0.5)!;
    expect(orders).toMatch(/^(\d{1,3}|1\.\d{3})$/);
    expect(Number(orders.replace(".", ""))).toBeLessThan(1204);
    expect(countText(null, "+12 %", 0.5)).toMatch(/^\+\d+ %$/);
  });

  it("writes a figure the way the target writes it", () => {
    const like = parseFigure("$1,240")!;
    expect(formatFigure(1234567, like)).toBe("$1,234,567");
    expect(formatFigure(1234567.5, parseFigure("1.234,56 €")!)).toBe("1.234.567,50 €");
  });

  it("counts from the old value to the new and ends on the exact text", () => {
    expect(countText("100", "200", 0)).toBe("100");
    expect(countText("100", "200", 1)).toBe("200");
    const mid = Number(countText("100", "200", 0.5));
    expect(mid).toBeGreaterThan(100);
    expect(mid).toBeLessThan(200);
  });

  it("counts a new figure from zero, and does not count when the unit changed", () => {
    expect(countText(null, "40%", 0)).toBe("0%");
    expect(countText("10%", "40 ms", 0.5)).toBeNull();
    expect(countText(null, "high", 0.5)).toBeNull();
  });

  it("keeps every motion inside the batch budget", () => {
    expect(motionSpan(0)).toBe(800);
    expect(motionSpan(2900)).toBeGreaterThanOrEqual(220);
    expect(2900 + motionSpan(2900)).toBeLessThanOrEqual(3200);
  });

  it("names a chart by its type, series and points", () => {
    expect(chartSignature({ type: "line", x: ["a", "b"], series: [{}] })).toBe("line:1:2");
  });
});

describe("a run", () => {
  it("finishes at once: timers stop and counts are put back", () => {
    vi.useFakeTimers();
    const run = new Run();
    const task = vi.fn();
    const restore = vi.fn();
    run.after(500, task);
    run.tween(500, () => undefined, restore);
    run.finish();
    vi.advanceTimersByTime(1000);
    expect(task).not.toHaveBeenCalled();
    expect(restore).toHaveBeenCalledTimes(1);
  });
});

describe("the adapter", () => {
  function body(): HTMLElement {
    const root = document.createElement("div");
    root.innerHTML = `
      <div data-live-path="/sections/0/title"></div>
      <div data-live-path="/sections/0/metrics/0"><input data-testid="data-metric-value" value="12"></div>
      <div data-live-path="/sections/0/metrics/1"><input data-testid="data-metric-value" value="7"></div>`;
    document.body.appendChild(root);
    return root;
  }

  it("returns one element step per drawn card, in reading order", () => {
    const root = body();
    const next = spec([section({ metrics: [{ label: "A", value: "12" }, { label: "B", value: "7" }] })]);
    const steps = dataReveal.steps({ type: "data", previous: null, next, ops: null, initial: true, root });
    expect(steps.map((s) => (s.target as { element: Element }).element.getAttribute("data-live-path"))).toEqual([
      "/sections/0/title",
      "/sections/0/metrics/0",
      "/sections/0/metrics/1",
    ]);
  });

  it("skips a card that is not drawn", () => {
    const root = body();
    const next = spec([section({ metrics: [{ label: "A", value: "12" }, { label: "B", value: "7" }, { label: "C", value: "1" }] })]);
    const previous = spec([section({ metrics: [{ label: "A", value: "12" }, { label: "B", value: "7" }] })]);
    expect(dataReveal.steps({ type: "data", previous, next, ops: null, initial: false, root })).toEqual([]);
  });

  it("counts a changed figure and leaves the exact value at the end", () => {
    vi.useFakeTimers();
    const root = body();
    const previous = spec([section({ metrics: [{ label: "A", value: "12" }, { label: "B", value: "7" }] })]);
    const next = spec([section({ metrics: [{ label: "A", value: "12" }, { label: "B", value: "7" }] })]);
    next.sections[0].metrics[0].value = "20";
    root.querySelectorAll("input")[0]!.value = "20";
    const steps = dataReveal.steps({ type: "data", previous, next, ops: null, initial: false, root });
    expect(steps).toHaveLength(1);
    // The person clicks in: the count ends on the exact value.
    root.dispatchEvent(new Event("pointerdown", { bubbles: true }));
    vi.advanceTimersByTime(2000);
    expect(root.querySelectorAll("input")[0]!.value).toBe("20");
  });
});
