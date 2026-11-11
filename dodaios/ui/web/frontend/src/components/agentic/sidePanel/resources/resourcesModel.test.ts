import { describe, expect, it } from "vitest";
import type { ResourceAgent, ResourceHistory, ResourceLoad } from "@/lib/resourcesApi";
import { SIDE_PANEL_TAB_IDS } from "@/store/ideSidePanel";
import { SIDE_PANEL_TABS } from "../sidePanelTabs";
import {
  agentTitle,
  areaPath,
  axisTicks,
  chartPoints,
  elseAt,
  formatMemory,
  formatPercent,
  historySpan,
  largest,
  metricValue,
  rankRows,
  rowLine,
  sortByMetric,
  sparkPath,
} from "./resourcesModel";

function load(cpu: number, memory: number, gpuMemory = 0, gpu = 0): ResourceLoad {
  return { cpu_percent: cpu, memory_mb: memory, processes: 1, threads: 1, gpu_memory_mb: gpuMemory, gpu_percent: gpu };
}

describe("resource figures", () => {
  it("names memory in the unit a person would say", () => {
    expect(formatMemory(843.4, "en-US")).toBe("843 MB");
    expect(formatMemory(1229, "en-US")).toBe("1.2 GB");
    expect(formatMemory(32420, "en-US")).toBe("31.7 GB");
    expect(formatMemory(1229, "de-DE")).toBe("1,2 GB");
    expect(formatMemory(-5, "en-US")).toBe("0 MB");
  });

  it("keeps one decimal only where it carries information", () => {
    expect(formatPercent(0, "en-US")).toBe("0 %");
    expect(formatPercent(0.4, "en-US")).toBe("0.4 %");
    expect(formatPercent(9.5, "en-US")).toBe("9.5 %");
    expect(formatPercent(37.4, "en-US")).toBe("37 %");
    expect(formatPercent(0.4, "de-DE")).toBe("0,4 %");
  });
});

describe("ranking", () => {
  const rows = [
    { id: "idle", ...load(0, 900) },
    { id: "busy", ...load(40, 200) },
    { id: "render", ...load(5, 300, 2000, 30) },
  ];

  it("sorts by the metric the reader chose", () => {
    expect(sortByMetric(rows, "cpu").map((row) => row.id)).toEqual(["busy", "render", "idle"]);
    expect(sortByMetric(rows, "memory").map((row) => row.id)).toEqual(["idle", "render", "busy"]);
    expect(sortByMetric(rows, "gpu").map((row) => row.id)).toEqual(["render", "idle", "busy"]);
  });

  it("keeps the given order between equals and leaves the input alone", () => {
    const equal = [{ id: "a", ...load(1, 1) }, { id: "b", ...load(1, 1) }];
    expect(sortByMetric(equal, "cpu").map((row) => row.id)).toEqual(["a", "b"]);
    expect(rows[0].id).toBe("idle");
  });

  it("finds the heaviest row for the bars", () => {
    expect(largest(rows, "cpu")).toBe(40);
    expect(largest(rows, "memory")).toBe(900);
    expect(largest([], "cpu")).toBe(0);
    expect(metricValue(rows[2], "gpu")).toBeGreaterThan(metricValue(rows[0], "gpu"));
  });
});

describe("the order of the agent list", () => {
  const agent = (id: string, cpu: number, memory: number): ResourceAgent => ({
    ...load(cpu, memory), id, kind: "pane", agent: "claude", agent_label: "Claude Code", label: id, detail: "", workspace: "", pid: 1, started_at: 0, runtime: load(0, 0), tools: [], linked: [],
  });
  const history = (lines: Record<string, (number | null)[]>): ResourceHistory => ({
    t: [],
    series: {},
    row_points: 90,
    rows: Object.fromEntries(Object.entries(lines).map(([id, cpu]) => [id, { cpu, memory: cpu }])),
  });

  it("does not reshuffle on one busy sample", () => {
    const agents = [agent("steady", 8, 100), agent("spike", 60, 100)];
    const brief = history({ steady: [10, 10, 10, 10, 10, 10, 10, 8], spike: [0, 0, 0, 0, 0, 0, 0, 60] });
    expect(rankRows(agents, brief, "cpu").map((item) => item.id)).toEqual(["steady", "spike"]);
    // Load that lasts does move it to the top.
    const lasting = history({ steady: [10, 10, 10, 10, 10, 10, 10, 8], spike: [0, 0, 0, 60, 60, 60, 60, 60] });
    expect(rankRows(agents, lasting, "cpu").map((item) => item.id)).toEqual(["spike", "steady"]);
  });

  it("looks back half a minute, not over the whole window", () => {
    const old = [...Array(40).fill(90), ...Array(15).fill(0)];
    const agents = [agent("was-busy", 0, 100), agent("is-busy", 5, 100)];
    const lines = history({ "was-busy": old, "is-busy": Array(55).fill(5) });
    expect(rankRows(agents, lines, "cpu").map((item) => item.id)).toEqual(["is-busy", "was-busy"]);
  });

  it("ranks an agent without a line by its current figure and breaks ties by memory", () => {
    const agents = [agent("small", 0, 100), agent("new", 3, 50), agent("large", 0, 900)];
    const lines = history({ small: [0, 0], large: [null, 0] });
    expect(rankRows(agents, lines, "cpu").map((item) => item.id)).toEqual(["new", "large", "small"]);
  });

  it("ranks memory as it stands", () => {
    const agents = [agent("a", 50, 100), agent("b", 0, 900)];
    expect(rankRows(agents, history({ a: [50], b: [0] }), "memory").map((item) => item.id)).toEqual(["b", "a"]);
  });
});

describe("chart series", () => {
  const history: ResourceHistory = {
    t: [100, 102, 104],
    series: {
      cpu: [10, 30, 50],
      "cpu.agents": [4, 20, 30],
      "cpu.linked": [0, 2, 5],
      "cpu.app": [1, 3, 5],
      "cpu.other": [5, 5, 10],
      memory: [60, 61, 62],
      "memory.agents": [20, 21, 22],
      gpu: [0, 15, 40],
    },
    row_points: 90,
    rows: {},
  };

  it("stacks the four owners of one metric", () => {
    expect(chartPoints(history, "cpu")).toEqual([
      { t: 100, agents: 4, linked: 0, app: 1, other: 5, total: 10 },
      { t: 102, agents: 20, linked: 2, app: 3, other: 5, total: 30 },
      { t: 104, agents: 30, linked: 5, app: 5, other: 10, total: 50 },
    ]);
  });

  it("reads a series the server did not send as zero", () => {
    expect(chartPoints(history, "memory")[2]).toEqual({ t: 104, agents: 22, linked: 0, app: 0, other: 0, total: 62 });
  });

  it("gives the graphics card one series", () => {
    expect(chartPoints(history, "gpu").map((point) => [point.agents, point.total])).toEqual([[0, 0], [15, 15], [40, 40]]);
  });
});

describe("sparkline", () => {
  it("runs left to right across the box on a fixed scale", () => {
    expect(sparkPath([0, 50, 100], 100, 22, { ceiling: 100 })).toBe("M0.0 21.0 L50.0 11.0 L100.0 1.0");
  });

  it("starts where the agent started and sits at the right edge while history is short", () => {
    expect(sparkPath([null, null, 10, 10], 30, 12, { ceiling: 10 })).toBe("M20.0 1.0 L30.0 1.0");
    expect(sparkPath([5, 5], 100, 12, { ceiling: 10, slots: 5 })).toBe("M75.0 6.0 L100.0 6.0");
  });

  it("does not stretch an idle line into noise", () => {
    const flat = sparkPath([0.1, 0.2, 0.1], 20, 12, { floor: 2 });
    expect(flat).toBe("M0.0 10.5 L10.0 10.0 L20.0 10.5");
  });

  it("draws nothing without a value and a dash for a single one", () => {
    expect(sparkPath([], 10, 10)).toBe("");
    expect(sparkPath([null, null], 10, 10)).toBe("");
    expect(sparkPath([null, 4], 10, 10)).toBe("M10.0 1.0 L10.0 1.0");
  });
});

describe("agent names", () => {
  const base = { ...load(0, 0), id: "x", agent: "claude", agent_label: "Claude Code", detail: "", workspace: "", pid: 1, started_at: 0, runtime: load(0, 0), tools: [], linked: [] };

  it("uses the pane's call-sign and what it is working on", () => {
    const pane: ResourceAgent = { ...base, kind: "pane", label: "T1", detail: "Fix the login test" };
    expect(agentTitle(pane, "Thread")).toBe("T1 · Fix the login test");
    expect(agentTitle({ ...pane, detail: "" }, "Thread")).toBe("T1");
  });

  it("uses a thread's title, and says Thread when it has none yet", () => {
    expect(agentTitle({ ...base, kind: "thread", label: "Review the PR" }, "Thread")).toBe("Review the PR");
    expect(agentTitle({ ...base, kind: "thread", label: "" }, "Thread")).toBe("Thread");
  });

  it("falls back to the CLI's name for an agent nobody named", () => {
    expect(agentTitle({ ...base, kind: "external", label: "" }, "Thread")).toBe("Claude Code");
  });
});

describe("the side panel registry", () => {
  it("offers the resource view under a letter of its own", () => {
    const tab = SIDE_PANEL_TABS.find((item) => item.id === "resources");
    expect(tab?.shortcut).toBe("R");
    expect(SIDE_PANEL_TAB_IDS).toContain("resources");
    const letters = SIDE_PANEL_TABS.map((item) => item.shortcut);
    expect(new Set(letters).size).toBe(letters.length);
    expect(letters).not.toContain("T");
  });
});

describe("a row's own curve", () => {
  const history: ResourceHistory = {
    t: [],
    series: {},
    row_points: 4,
    rows: { "app:Blender": { cpu: [null, 10, 20], memory: [null, 100, 200] } },
  };

  it("reads the line of the chosen metric, and nothing where none was sent", () => {
    expect(rowLine(history, "app:Blender", "cpu")).toEqual([null, 10, 20]);
    expect(rowLine(history, "app:Blender", "gpu")).toEqual([]);
    expect(rowLine(history, "app:Gone", "memory")).toEqual([]);
  });

  it("closes the line down to the baseline for the filled area", () => {
    const { line, area } = areaPath([null, 10, 20], 30, 12, { slots: 4 });
    expect(line).toBe("M20.0 6.0 L30.0 1.0");
    expect(area).toBe("M20.0 6.0 L30.0 1.0 L30.0 12 L20.0 12 Z");
    expect(areaPath([], 30, 12)).toEqual({ line: "", area: "" });
  });
});

describe("a chart that is full from the start", () => {
  it("spans what has been measured, and at least a few seconds", () => {
    expect(historySpan([])).toBe(10);
    expect(historySpan([100])).toBe(10);
    expect(historySpan([100, 101, 102])).toBe(10);
    expect(historySpan([100, 130, 160])).toBe(60);
    expect(historySpan([0, 299])).toBe(299);
  });

  it("puts a handful of ticks on round steps back from now", () => {
    expect(axisTicks(1000, 10)).toEqual([990, 1000]);
    expect(axisTicks(1000, 45)).toEqual([960, 970, 980, 990, 1000]);
    expect(axisTicks(1000, 70)).toEqual([940, 955, 970, 985, 1000]);
    expect(axisTicks(1000, 140)).toEqual([880, 910, 940, 970, 1000]);
    expect(axisTicks(1000, 299)).toEqual([760, 820, 880, 940, 1000]);
  });
});

describe("what everything else was made of", () => {
  const history: ResourceHistory = {
    t: [100, 102, 104, 106],
    series: {},
    row_points: 3,
    rows: {
      // A row's line is shorter than the series and ends with it.
      "app:Chrome": { cpu: [5, 20, 2], memory: [1000, 1000, 2000] },
      "app:Code": { cpu: [null, 4, 9], memory: [null, 500, 500] },
      system: { cpu: [10, 10, 0.05], memory: [4000, 4000, 4000] },
    },
  };
  const rows = [
    { id: "app:Chrome", label: "Chrome" },
    { id: "app:Code", label: "Code" },
    { id: "system", label: "System" },
    { id: "app:Gone", label: "Gone" },
  ];

  it("names the largest rows at the hovered sample", () => {
    expect(elseAt(history, rows, 3, "cpu", 8000)).toEqual([
      { id: "app:Code", label: "Code", value: 9 },
      { id: "app:Chrome", label: "Chrome", value: 2 },
    ]);
    expect(elseAt(history, rows, 2, "cpu", 8000).map((part) => part.label)).toEqual(["Chrome", "System", "Code"]);
  });

  it("leaves out a row that did not exist yet, and has nothing before the lines begin", () => {
    expect(elseAt(history, rows, 1, "cpu", 8000).map((part) => part.label)).toEqual(["System", "Chrome"]);
    expect(elseAt(history, rows, 0, "cpu", 8000)).toEqual([]);
    expect(elseAt(history, rows, -1, "cpu", 8000)).toEqual([]);
  });

  it("gives memory as a share of the machine, like the band it explains", () => {
    expect(elseAt(history, rows, 3, "memory", 8000, 2)).toEqual([
      { id: "system", label: "System", value: 50 },
      { id: "app:Chrome", label: "Chrome", value: 25 },
    ]);
  });
});
