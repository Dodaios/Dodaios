import { describe, expect, it } from "vitest";
import {
  chartReach,
  deltaDirection,
  endsInOpenFence,
  formatChartTick,
  formatChartValue,
  isChartFenceLine,
  parseChartSpec,
  withUnit,
} from "./chartSpec";

const PRICE = {
  type: "line",
  title: "ACME share price",
  unit: "USD",
  note: "daily close",
  value: "142.30 USD",
  delta: "+2.1 %",
  x: ["1 Jun", "2 Jun", "3 Jun"],
  series: [{ name: "ACME", data: [139.4, 140.1, 142.3] }],
};

describe("reading a chart block", () => {
  it("reads the chart the assistant is told to write", () => {
    expect(parseChartSpec(JSON.stringify(PRICE))).toEqual({ ...PRICE });
  });

  it("takes one list of numbers on the object as a single series named by the title", () => {
    const spec = parseChartSpec(JSON.stringify({ type: "columns", title: "Orders", labels: ["Q1", "Q2"], values: [3, "4.5"] }));
    expect(spec?.type).toBe("column");
    expect(spec?.series).toEqual([{ name: "Orders", data: [3, 4.5] }]);
  });

  it("keeps a missing value as a gap", () => {
    const spec = parseChartSpec(JSON.stringify({ x: ["a", "b", "c"], series: [{ name: "s", data: [1, null, 3] }] }));
    expect(spec?.type).toBe("line");
    expect(spec?.series[0].data).toEqual([1, null, 3]);
  });

  it.each([
    ["JSON that is still arriving", '{"type": "line", "x": ["a", "b"], "series": [{"name": "s", "da'],
    ["a list instead of an object", "[1, 2, 3]"],
    ["an unknown type", JSON.stringify({ ...PRICE, type: "pie" })],
    ["numbers that do not line up with the labels", JSON.stringify({ ...PRICE, series: [{ name: "ACME", data: [1, 2] }] })],
    ["a value that is not a number", JSON.stringify({ ...PRICE, series: [{ name: "ACME", data: [1, "high", 3] }] })],
    ["a series with no value at all", JSON.stringify({ ...PRICE, series: [{ name: "ACME", data: [null, null, null] }] })],
    ["a single point", JSON.stringify({ x: ["a"], series: [{ name: "s", data: [1] }] })],
    ["more series than there are colours", JSON.stringify({ x: ["a", "b"], series: Array.from({ length: 7 }, (_, i) => ({ name: `s${i}`, data: [1, 2] })) })],
    ["several series without names", JSON.stringify({ x: ["a", "b"], series: [{ data: [1, 2] }, { data: [2, 3] }] })],
    ["more bar rows than a card holds", JSON.stringify({ type: "bar", x: Array.from({ length: 25 }, (_, i) => `row ${i}`), values: Array.from({ length: 25 }, (_, i) => i) })],
    ["no labels", JSON.stringify({ series: [{ name: "s", data: [1, 2] }] })],
  ])("leaves %s as the code it is", (_name, code) => {
    expect(parseChartSpec(code)).toBeNull();
  });
});

describe("finding a block that is still being written", () => {
  it("knows an open fence from a closed one", () => {
    expect(endsInOpenFence("Here:\n\n```chart\n{\"type\":")).toBe(true);
    expect(endsInOpenFence("Here:\n\n```chart\n{}\n```\n\nDone.")).toBe(false);
    expect(endsInOpenFence("```js\na\n```\n\n~~~chart\n{")).toBe(true);
    expect(endsInOpenFence("no code at all")).toBe(false);
  });

  it("recognises the opening line of a chart block only", () => {
    expect(isChartFenceLine("```chart")).toBe(true);
    expect(isChartFenceLine("  ``` chart  ")).toBe(true);
    expect(isChartFenceLine("```charts")).toBe(false);
    expect(isChartFenceLine("```json")).toBe(false);
    expect(isChartFenceLine("chart")).toBe(false);
  });
});

describe("writing a chart's numbers", () => {
  it("puts the unit where it is read", () => {
    expect(withUnit("12.50", "$")).toBe("$12.50");
    expect(withUnit("-3", "$")).toBe("-$3");
    expect(withUnit("4.2", "%")).toBe("4.2%");
    expect(withUnit("142.3", "USD")).toBe("142.3 USD");
    expect(withUnit("7", "")).toBe("7");
  });

  it("writes a value in the reader's language, with the precision its size needs", () => {
    expect(formatChartValue(142.345, "en")).toBe("142.3");
    expect(formatChartValue(1.2345, "en")).toBe("1.23");
    expect(formatChartValue(12345.6, "en")).toBe("12,346");
    expect(formatChartValue(12345.6, "de")).toBe("12.346");
    expect(formatChartValue(0.00123, "en")).toBe("0.0012");
  });

  it("keeps axis numbers in full under ten thousand and compact above", () => {
    expect(formatChartTick(2000, "en", 9000)).toBe("2,000");
    expect(formatChartTick(20000, "en", 80000)).toBe("20K");
    expect(formatChartTick(0.5, "en", 2)).toBe("0.5");
    expect(chartReach(parseChartSpec(JSON.stringify(PRICE))!)).toBe(142.3);
  });

  it("reads which way a change points", () => {
    expect(deltaDirection("+2.1 %")).toBe(1);
    expect(deltaDirection("-0.4")).toBe(-1);
    expect(deltaDirection("−3 USD")).toBe(-1);
    expect(deltaDirection("0.0 %")).toBe(0);
    expect(deltaDirection("unchanged")).toBe(0);
  });
});
