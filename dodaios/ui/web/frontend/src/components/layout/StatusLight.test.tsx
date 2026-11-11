import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEventStore } from "@/store/events";
import { useAgentNavigation } from "@/views/society/agentNavigation";
import { StatusLight } from "./StatusLight";
import { useStatusLightStore, type StatusLightData } from "./statusLightStore";

const LIGHT: StatusLightData = {
  counts: { running: 2, needs_you: 1 },
  running: [
    { kind: "pane", id: "t1", title: "Agent 1 (api)", state: "busy", link: { section: "agentic-ide" } },
    { kind: "mission", id: "m1", title: "Write the report", state: "RUNNING", link: { section: "board" } },
  ],
  needs_you: [
    {
      kind: "question",
      id: "q1",
      title: "Which database?",
      state: "waiting",
      link: { agent_id: "jarvis", session_id: "s1", ref_id: "q1" },
    },
  ],
  trouble: [],
  findings: [],
  tone: "calm",
};

function answer(body: StatusLightData) {
  return vi.fn(async () => new Response(JSON.stringify(body), { status: 200 }));
}

beforeEach(() => {
  useStatusLightStore.setState({ light: null, error: false });
  useAgentNavigation.setState({ request: null, onScreen: null });
  useEventStore.setState({ activeSection: "chats" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("StatusLight", () => {
  it("says how many run and how many need you", async () => {
    vi.stubGlobal("fetch", answer(LIGHT));
    render(<StatusLight />);
    await act(async () => {});
    const chip = screen.getByTestId("status-light");
    expect(chip.getAttribute("data-running")).toBe("2");
    expect(chip.getAttribute("data-needs-you")).toBe("1");
    expect(screen.getByTestId("status-light-text").textContent).toBe("2 running · 1 need you");
    expect(chip.getAttribute("data-tone")).toBe("calm");
  });

  it("shows a quiet idle chip when nothing runs", async () => {
    vi.stubGlobal("fetch", answer({ ...LIGHT, counts: { running: 0, needs_you: 0 }, running: [], needs_you: [] }));
    render(<StatusLight />);
    await act(async () => {});
    expect(screen.getByTestId("status-light-text").textContent).toBe("All quiet");
  });

  it("takes a warning tone when a seat is in trouble", async () => {
    vi.stubGlobal(
      "fetch",
      answer({
        ...LIGHT,
        tone: "warn",
        trouble: [{ provider: "openai", account: "", class: "quota", reason: "x", blocked: false }],
      }),
    );
    render(<StatusLight />);
    await act(async () => {});
    expect(screen.getByTestId("status-light").getAttribute("data-tone")).toBe("warn");
    expect(screen.getByTestId("status-light-dot").className).toContain("bg-warning");
    fireEvent.click(screen.getByTestId("status-light"));
    expect(screen.getByTestId("status-light-trouble").textContent).toContain("usage limit reached");
  });

  it("never opens by itself and lists rows when clicked", async () => {
    vi.stubGlobal("fetch", answer(LIGHT));
    render(<StatusLight />);
    await act(async () => {});
    expect(screen.queryByTestId("status-light-panel")).toBeNull();
    fireEvent.click(screen.getByTestId("status-light"));
    expect(screen.getByTestId("status-light-panel")).toBeTruthy();
    expect(screen.getAllByTestId("status-light-row")).toHaveLength(3);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("status-light-panel")).toBeNull();
  });

  it("opens a needs-you card in the agent's chat", async () => {
    vi.stubGlobal("fetch", answer(LIGHT));
    render(<StatusLight />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId("status-light"));
    fireEvent.click(screen.getByText("Which database?"));
    const request = useAgentNavigation.getState().request;
    expect(request).toMatchObject({ agentId: "jarvis", sessionId: "s1", cardRef: "q1", kind: "question" });
    expect(useEventStore.getState().activeSection).toBe("agents");
    expect(screen.queryByTestId("status-light-panel")).toBeNull();
  });

  it("takes a running row to its section", async () => {
    vi.stubGlobal("fetch", answer(LIGHT));
    render(<StatusLight />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId("status-light"));
    fireEvent.click(screen.getByText("Write the report"));
    expect(useEventStore.getState().activeSection).toBe("board");
  });

  it("keeps the chip and says so in the panel when the read fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("no", { status: 500 })));
    render(<StatusLight />);
    await act(async () => {});
    fireEvent.click(screen.getByTestId("status-light"));
    expect(screen.getByRole("alert").textContent).toContain("not available");
  });
  it("lists watchdog findings and warns", async () => {
    vi.stubGlobal(
      "fetch",
      answer({ ...LIGHT, tone: "warn", findings: [{ id: "f1", kind: "silent_turn", title: "Turn is silent" }] }),
    );
    render(<StatusLight />);
    await act(async () => {});
    expect(screen.getByTestId("status-light").getAttribute("data-tone")).toBe("warn");
    fireEvent.click(screen.getByTestId("status-light"));
    expect(screen.getByTestId("status-light-finding").textContent).toContain("Turn is silent");
  });
});
