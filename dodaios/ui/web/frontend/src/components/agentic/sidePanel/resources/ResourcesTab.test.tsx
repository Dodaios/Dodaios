import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { endResourceTools, fetchResources, type ResourceLoad, type ResourceSnapshot } from "@/lib/resourcesApi";
import { ResourcesTab } from "./ResourcesTab";

vi.mock("@/lib/resourcesApi", () => ({ fetchResources: vi.fn(), endResourceTools: vi.fn() }));
vi.mock("@/store/tiling", () => ({ isSectionOnScreen: () => true }));
// The chart is the charting library's business; what this suite pins is which
// metric it is asked to draw.
vi.mock("./ResourceChart", () => ({
  ResourceChart: ({ metric }: { metric: string }) => <div data-testid="resources-chart" data-metric={metric} />,
}));

function load(cpu: number, memory: number, extra: Partial<ResourceLoad> = {}): ResourceLoad {
  return { cpu_percent: cpu, memory_mb: memory, processes: 2, threads: 8, gpu_memory_mb: 0, gpu_percent: 0, ...extra };
}

function snapshot(overrides: Partial<ResourceSnapshot> = {}): ResourceSnapshot {
  return {
    ts: 1000,
    interval_s: 2,
    platform: "win32",
    system: {
      cpu_percent: 37.4,
      per_core: [80, 20, 5, 45],
      cores_logical: 4,
      cores_physical: 2,
      memory_total_mb: 32768,
      memory_used_mb: 16384,
      memory_percent: 50,
      swap_total_mb: 0,
      swap_used_mb: 0,
      processes: 400,
      gpu: { name: "Test Card", util_percent: 12, memory_used_mb: 4096, memory_total_mb: 16384, per_process: true },
    },
    groups: {
      agents: load(25.5, 3072),
      linked: load(4, 2048),
      app: load(2, 1024),
      other: load(5.9, 10240),
    },
    agents: [
      {
        ...load(0.5, 2600),
        id: "thread:s1",
        kind: "thread",
        agent: "codex",
        agent_label: "Codex",
        label: "Review the PR",
        detail: "",
        workspace: "api",
        pid: 51,
        started_at: 1,
        runtime: load(0.5, 2600),
        tools: [],
        linked: [],
      },
      {
        ...load(25, 1300, { processes: 9, gpu_memory_mb: 512, gpu_percent: 3 }),
        id: "pane:abc",
        kind: "pane",
        agent: "claude",
        agent_label: "Claude Code",
        label: "T1",
        detail: "Fix the login test",
        workspace: "web",
        pid: 30,
        started_at: 1,
        runtime: load(3, 400),
        tools: [
          { ...load(0.1, 43), ids: ["32:1"], category: "mcp", label: "blender", instances: 1, started_at: 1 },
          { ...load(21.9, 800, { processes: 3 }), ids: ["35:1"], category: "test", label: "pytest", instances: 1, started_at: 1 },
          { ...load(0, 2), ids: ["38:1", "39:1"], category: "shell", label: "bash", instances: 2, started_at: 1 },
        ],
        linked: [
          { ...load(31, 2100, { gpu_memory_mb: 1500 }), id: "50:1", label: "Blender", port: 9876, via: "blender", via_category: "mcp", shared_with: 1 },
        ],
      },
    ],
    app: { ...load(2, 1024), parts: [{ ...load(1.5, 600), role: "core" }, { ...load(0.5, 424), role: "appshot.picker" }] },
    other: { ...load(4, 9000), top: [{ ...load(3, 700), name: "Chrome" }] },
    history: {
      t: [996, 998, 1000],
      series: { cpu: [10, 30, 37.4], memory: [50, 50, 50], gpu: [0, 5, 12] },
      agents: { "pane:abc": { cpu: [null, 20, 25], memory: [null, 1200, 1300] } },
    },
    ...overrides,
  };
}

const fetchMock = vi.mocked(fetchResources);
const endMock = vi.mocked(endResourceTools);

beforeEach(() => {
  localStorage.clear();
  fetchMock.mockReset();
  endMock.mockReset();
  fetchMock.mockResolvedValue(snapshot());
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

async function shown() {
  render(<ResourcesTab />);
  await screen.findByTestId("resources-tile-cpu");
}

function agentOrder(): string[] {
  return screen.getAllByTestId("resources-agent").map((row) => row.getAttribute("data-agent-id") ?? "");
}

describe("ResourcesTab", () => {
  it("says it is measuring until the first reading arrives", async () => {
    let resolve: (value: ResourceSnapshot) => void = () => {};
    fetchMock.mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<ResourcesTab />);
    expect(screen.getByTestId("resources-loading")).toBeTruthy();
    await act(async () => resolve(snapshot()));
    expect(screen.queryByTestId("resources-loading")).toBeNull();
  });

  it("shows the three meters with the machine's own figures", async () => {
    await shown();
    expect(screen.getByTestId("resources-tile-cpu").textContent).toContain("37 %");
    expect(screen.getByTestId("resources-tile-cpu").textContent).toContain("4 cores");
    expect(screen.getByTestId("resources-tile-memory").textContent).toContain("50 %");
    expect(screen.getByTestId("resources-tile-memory").textContent).toContain("16 GB of 32 GB");
    expect(screen.getByTestId("resources-tile-gpu").textContent).toContain("12 %");
    expect(screen.getByTestId("resources-tile-gpu").textContent).toContain("4 GB of 16 GB");
    expect(screen.getByTestId("resources-tile-cpu").getAttribute("aria-pressed")).toBe("true");
  });

  it("lists agents heaviest first and opens the heaviest", async () => {
    await shown();
    expect(agentOrder()).toEqual(["pane:abc", "thread:s1"]);
    expect(screen.getByTestId("resources-agent-count").textContent).toBe("2");
    const [pane, thread] = screen.getAllByTestId("resources-agent");
    expect(pane.textContent).toContain("T1 · Fix the login test");
    expect(pane.textContent).toContain("Claude Code · Pane · web · 9 processes");
    expect(thread.textContent).toContain("Review the PR");
    expect(thread.textContent).toContain("Codex · Thread · api");
    expect(within(pane).getByTestId("resources-runtime").textContent).toContain("The agent itself");
    expect(within(thread).queryByTestId("resources-runtime")).toBeNull();
  });

  it("breaks an agent into its tools and the apps connected to them", async () => {
    await shown();
    const pane = screen.getAllByTestId("resources-agent")[0];
    const tools = within(pane).getAllByTestId("resources-tool");
    expect(tools.map((tool) => tool.textContent)).toEqual([
      expect.stringContaining("pytest"),
      expect.stringContaining("blender"),
      expect.stringContaining("bash"),
    ]);
    expect(tools[0].textContent).toContain("Tests · 3 processes");
    expect(tools[0].textContent).toContain("22 %");
    expect(tools[1].textContent).toContain("MCP server");
    expect(tools[2].textContent).toContain("×2");
    const linked = within(pane).getByTestId("resources-linked");
    expect(linked.textContent).toContain("Blender");
    expect(linked.textContent).toContain("through blender on port 9876");
    expect(linked.textContent).toContain("also used by 1 more");
    expect(linked.textContent).toContain("2.1 GB");
  });

  it("turns the whole view to memory when that meter is chosen, and remembers it", async () => {
    await shown();
    expect(screen.getByTestId("resources-chart").getAttribute("data-metric")).toBe("cpu");
    expect(within(screen.getByTestId("resources-legend")).getByText("26 %")).toBeTruthy();

    fireEvent.click(screen.getByTestId("resources-tile-memory"));

    expect(screen.getByTestId("resources-chart").getAttribute("data-metric")).toBe("memory");
    expect(agentOrder()).toEqual(["thread:s1", "pane:abc"]);
    expect(within(screen.getByTestId("resources-legend")).getByText("3 GB")).toBeTruthy();
    expect(screen.queryByTestId("resources-cores")).toBeNull();
    expect(localStorage.getItem("jarvis.agenticIde.resources.metric")).toBe("memory");

    cleanup();
    await shown();
    expect(screen.getByTestId("resources-tile-memory").getAttribute("aria-pressed")).toBe("true");
  });

  it("shows graphics memory per agent under the graphics meter", async () => {
    await shown();
    fireEvent.click(screen.getByTestId("resources-tile-gpu"));
    expect(screen.getByTestId("resources-chart").getAttribute("data-metric")).toBe("gpu");
    expect(screen.queryByTestId("resources-legend")).toBeNull();
    const pane = screen.getAllByTestId("resources-agent")[0];
    expect(pane.getAttribute("data-agent-id")).toBe("pane:abc");
    expect(pane.textContent).toContain("512 MB");
    expect(within(pane).getByTestId("resources-linked").textContent).toContain("1.5 GB");
  });

  it("does not offer the graphics meter where the card cannot be read", async () => {
    localStorage.setItem("jarvis.agenticIde.resources.metric", "gpu");
    const base = snapshot();
    fetchMock.mockResolvedValue({ ...base, system: { ...base.system, gpu: null } });
    await shown();
    const tile = screen.getByTestId("resources-tile-gpu") as HTMLButtonElement;
    expect(tile.disabled).toBe(true);
    expect(tile.textContent).toContain("No reading here");
    expect(screen.getByTestId("resources-chart").getAttribute("data-metric")).toBe("cpu");
  });

  it("draws one cell per core under the processor chart", async () => {
    await shown();
    const cells = screen.getByTestId("resources-cores").querySelectorAll("[title]");
    expect(cells).toHaveLength(4);
    expect(cells[0].getAttribute("title")).toBe("Core 1: 80 %");
  });

  it("opens this app and everything else on request", async () => {
    await shown();
    const app = screen.getByTestId("resources-app");
    expect(app.textContent).not.toContain("appshot.picker");
    fireEvent.click(within(app).getByRole("button"));
    expect(app.textContent).toContain("Core");
    expect(app.textContent).toContain("appshot.picker");
    const other = screen.getByTestId("resources-other");
    // The remainder of the machine's figure, not the sum of listed processes.
    expect(other.textContent).toContain("5.9 %");
    expect(other.textContent).toContain("10 GB");
    fireEvent.click(within(other).getByRole("button"));
    expect(other.textContent).toContain("Chrome");
  });

  it("ends a tool only after the reader confirms, then measures again", async () => {
    endMock.mockResolvedValue(3);
    await shown();
    const pane = screen.getAllByTestId("resources-agent")[0];
    fireEvent.click(within(pane).getAllByTestId("resources-end")[2]);
    expect(endMock).not.toHaveBeenCalled();
    expect(within(pane).getByRole("alertdialog").textContent).toContain("End bash?");

    const before = fetchMock.mock.calls.length;
    await act(async () => {
      fireEvent.click(within(pane).getByTestId("resources-end-confirm"));
    });

    expect(endMock).toHaveBeenCalledWith(["38:1", "39:1"]);
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(before));
    expect(within(pane).queryByRole("alertdialog")).toBeNull();
  });

  it("leaves the tool alone when the reader cancels, and reports a failed end", async () => {
    endMock.mockRejectedValue(new Error("Only available on this computer."));
    await shown();
    const pane = screen.getAllByTestId("resources-agent")[0];
    fireEvent.click(within(pane).getAllByTestId("resources-end")[0]);
    fireEvent.click(within(pane).getByText("Cancel"));
    expect(endMock).not.toHaveBeenCalled();

    fireEvent.click(within(pane).getAllByTestId("resources-end")[0]);
    await act(async () => {
      fireEvent.click(within(pane).getByTestId("resources-end-confirm"));
    });
    expect(screen.getByText("It could not be ended: Only available on this computer.")).toBeTruthy();
  });

  it("says so when no agent is running", async () => {
    fetchMock.mockResolvedValue(snapshot({ agents: [] }));
    await shown();
    expect(screen.getByText("No coding agent is running.")).toBeTruthy();
    expect(screen.getByTestId("resources-agent-count").textContent).toBe("0");
  });

  it("reports a first reading that failed", async () => {
    fetchMock.mockRejectedValue(new Error("HTTP 500"));
    render(<ResourcesTab />);
    expect((await screen.findByRole("alert")).textContent).toContain("The reading failed: HTTP 500");
  });

  it("polls every two seconds and keeps the last reading when a poll fails", async () => {
    vi.useFakeTimers();
    render(<ResourcesTab />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const next = snapshot();
    next.system.cpu_percent = 81;
    fetchMock.mockResolvedValueOnce(next);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("resources-tile-cpu").textContent).toContain("81 %");

    fetchMock.mockRejectedValueOnce(new Error("HTTP 503"));
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByTestId("resources-tile-cpu").textContent).toContain("81 %");
    expect(screen.getByRole("alert").textContent).toContain("HTTP 503");

    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("asks nothing while the window is hidden", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    try {
      render(<ResourcesTab />);
      await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
      expect(fetchMock).not.toHaveBeenCalled();
      hidden.mockReturnValue(false);
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
      expect(fetchMock).toHaveBeenCalledTimes(1);
    } finally {
      hidden.mockRestore();
    }
  });
});
