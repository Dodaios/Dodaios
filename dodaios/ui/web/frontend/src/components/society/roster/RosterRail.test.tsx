import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SocietyAgent } from "@/components/society/data";
import { useRetireStore } from "@/components/society/world/retireStore";
import { useEventStore } from "@/store/events";
import { RosterRail, type RosterRailProps } from "./RosterRail";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useUiLanguage: () => "en" }));

afterEach(() => {
  useRetireStore.getState().cutShort();
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  useEventStore.setState({ assistantName: "Assistant" });
});
function agent(over: Partial<SocietyAgent> & Pick<SocietyAgent, "agentId" | "name">): SocietyAgent {
  return {
    title: "Title",
    description: "",
    tier: "specialist",
    provider: "",
    providerLabel: "",
    model: "",
    effort: "",
    figure: null,
    palette: { primary: "#000", secondary: "#111", accent: "#222" },
    grantMode: "all",
    toolGrants: [],
    focus: [],
    denies: [],
    approvalRules: { requireApproval: [], alwaysAllow: [] },
    permissionCeiling: "ask",
    dailyBudgetUsd: 0,
    checkpoint: "idle",
    state: "idle",
    lifecycle: "active",
    createdMs: 0,
    maxConcurrentRuns: 1,
    workspaceDir: "",
    wikiNamespace: "",
    chatSessionId: null,
    routines: [],
    stats: { runs: 0, totalCostUsd: 0, spentTodayUsd: 0, lastActiveMs: null },
    ...over,
  };
}

const baseProps = {
  loading: false,
  sample: false,
  onOpen: () => undefined,
  onCreate: () => undefined,
};

describe("RosterRail status", () => {
  it("shows a team as one row and keeps its members out of the sidebar", () => {
    const openGroup = vi.fn();
    render(<RosterRail {...baseProps} activeAgentId={null}
      agents={[agent({ agentId: "scout", name: "Scout" }), agent({ agentId: "writer", name: "Writer" })]}
      groups={[{ group_id: "team", name: "Launch team", members: ["scout", "writer"], created_ms: 1, updated_ms: 1 }]}
      onOpenGroup={openGroup} />);
    expect(screen.queryByText("Scout")).toBeNull();
    expect(screen.queryByText("Writer")).toBeNull();
    expect(screen.getByText("Scout, Writer")).toBeTruthy();
    fireEvent.click(screen.getByTestId("society-group-team"));
    expect(openGroup).toHaveBeenCalledWith("team");
  });
  it("lists nobody on their own until the teams have answered", () => {
    const agents = [agent({ agentId: "scout", name: "Scout" }), agent({ agentId: "writer", name: "Writer" }), agent({ agentId: "solo", name: "Solo" })];
    const view = render(<RosterRail {...baseProps} activeAgentId={null} agents={agents} teamsPending />);
    // Not one frame shows a team member as a loose agent.
    expect(screen.queryByText("Scout")).toBeNull();
    expect(screen.queryByText("Solo")).toBeNull();
    expect(screen.getByText("society.roster.loading")).toBeTruthy();

    view.rerender(<RosterRail {...baseProps} activeAgentId={null} agents={agents} onOpenGroup={() => undefined}
      groups={[{ group_id: "team", name: "Launch team", members: ["scout", "writer"], created_ms: 1, updated_ms: 1 }]} />);
    expect(screen.getByTestId("society-group-team")).toBeTruthy();
    expect(screen.queryByText("Scout")).toBeNull();
    expect(screen.getByText("Solo")).toBeTruthy();
    expect(screen.queryByText("society.roster.loading")).toBeNull();
  });
  it("opens team actions on right-click and only ungroups after confirmation", async () => {
    const request = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    vi.stubGlobal("fetch", request);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><RosterRail {...baseProps} activeAgentId={null}
      agents={[agent({ agentId: "scout", name: "Scout" }), agent({ agentId: "writer", name: "Writer" })]}
      groups={[{ group_id: "team", name: "Launch team", members: ["scout", "writer"], created_ms: 1, updated_ms: 1 }]}
      onOpenGroup={() => undefined} /></QueryClientProvider>);

    const row = screen.getByTestId("society-group-team");
    fireEvent.contextMenu(row, { clientX: 32, clientY: 56 });
    expect(screen.getByRole("menu", { name: "Launch team" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "society.groups.edit" })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: "society.groups.delete" }));
    expect(screen.getByRole("dialog", { name: "society.groups.delete" })).toBeTruthy();
    expect(request).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "society.groups.cancel" }));
    expect(request).not.toHaveBeenCalled();

    fireEvent.contextMenu(row, { clientX: 32, clientY: 56 });
    fireEvent.click(screen.getByRole("menuitem", { name: "society.groups.delete" }));
    fireEvent.click(screen.getByRole("button", { name: "society.groups.delete" }));
    await waitFor(() => expect(request).toHaveBeenCalledWith("/api/society/chat-groups/team", { method: "DELETE" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
  it("shows a loading spinner while an agent is thinking", () => {
    render(
      <RosterRail
        {...baseProps}
        agents={[agent({ agentId: "a", name: "A", state: "working" })]}
        activeAgentId={null}
      />,
    );
    expect(screen.getByRole("status", { name: "society.roster.thinking" })).toBeTruthy();
    expect(screen.queryByLabelText("society.roster.unread")).toBeNull();
  });

  it("shows a grey idle dot with no unseen results", () => {
    render(
      <RosterRail
        {...baseProps}
        agents={[agent({ agentId: "a", name: "A", state: "idle" })]}
        activeAgentId={null}
      />,
    );
    expect(screen.getByLabelText("society.state.idle")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("marks a finished agent green until it is opened", () => {
    const working = [agent({ agentId: "a", name: "A", state: "working" })];
    const done = [agent({ agentId: "a", name: "A", state: "idle" })];
    const { rerender } = render(
      <RosterRail {...baseProps} agents={working} activeAgentId={null} />,
    );
    rerender(<RosterRail {...baseProps} agents={done} activeAgentId={null} />);
    expect(screen.getByLabelText("society.roster.unread")).toBeTruthy();

    rerender(<RosterRail {...baseProps} agents={done} activeAgentId="a" />);
    expect(screen.queryByLabelText("society.roster.unread")).toBeNull();
    expect(screen.getByLabelText("society.state.idle")).toBeTruthy();
  });

  it("does not mark the open agent unread when it finishes in front of you", () => {
    const working = [agent({ agentId: "a", name: "A", state: "working" })];
    const done = [agent({ agentId: "a", name: "A", state: "idle" })];
    const { rerender } = render(
      <RosterRail {...baseProps} agents={working} activeAgentId="a" />,
    );
    rerender(<RosterRail {...baseProps} agents={done} activeAgentId="a" />);
    expect(screen.queryByLabelText("society.roster.unread")).toBeNull();
  });
});

describe("RosterRail agent actions", () => {
  const renderRail = (agents: SocietyAgent[]) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}>
      <RosterRail {...baseProps} agents={agents} activeAgentId={null} />
    </QueryClientProvider>);
  };

  it("opens the pin, read, rename, hide and delete actions on right click", () => {
    renderRail([agent({ agentId: "a", name: "A" })]);
    fireEvent.contextMenu(screen.getByText("A"));
    expect(screen.getAllByRole("menuitem")).toHaveLength(5);
    expect(screen.getByRole("menuitem", { name: "society.shell.pin" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "society.shell.mark_unread" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "society.roster.rename" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "society.roster.hide" })).toBeTruthy();
    expect(screen.getByRole("menuitem", { name: "society.roster.delete" })).toBeTruthy();
    expect(screen.queryByText(/copy|kopieren/i)).toBeNull();
  });

  it("hides an agent persistently and restores it from the hidden list", () => {
    const agents = [agent({ agentId: "a", name: "A" })];
    const { unmount } = renderRail(agents);
    fireEvent.contextMenu(screen.getByText("A"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.roster.hide" }));
    expect(screen.queryByText("A")).toBeNull();
    unmount();

    renderRail(agents);
    expect(screen.queryByText("A")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "society.roster.show_hidden" }));
    fireEvent.contextMenu(screen.getByText("A"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.roster.show" }));
    expect(JSON.parse(localStorage.getItem("society.roster.hidden-agent-ids") ?? "[]")).toEqual([]);
    expect(screen.getByText("A")).toBeTruthy();
  });

  it("renames via the existing roster API and confirms before deleting", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    renderRail([agent({ agentId: "a", name: "A" })]);
    fireEvent.contextMenu(screen.getByText("A"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.roster.rename" }));
    fireEvent.change(screen.getByRole("textbox", { name: "society.roster.name" }), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: "society.roster.save" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/society/agents/a", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "Renamed" }) })));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    fireEvent.contextMenu(screen.getByText("A"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.roster.delete" }));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "society.roster.cancel" }));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("archives only after the delete confirmation", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true });
    vi.stubGlobal("fetch", fetchMock);
    renderRail([agent({ agentId: "a", name: "A" })]);
    fireEvent.contextMenu(screen.getByText("A"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.roster.delete" }));
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "society.roster.delete" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/society/agents/a", { method: "DELETE" }));
  });
});

describe("RosterRail reorder", () => {
  const ORDER_KEY = "society.roster.order";
  const renderRail = (agents: SocietyAgent[]) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}>
      <RosterRail {...baseProps} agents={agents} activeAgentId={null} />
    </QueryClientProvider>);
  };

  const trio = () => [
    agent({ agentId: "a", name: "A" }),
    agent({ agentId: "b", name: "B" }),
    agent({ agentId: "c", name: "C" }),
  ];

  const rowOrder = () =>
    [...document.querySelectorAll("div[data-agent-id]")].map((el) =>
      el.getAttribute("data-agent-id"),
    );

  const rowOf = (name: string): HTMLElement => {
    const row = screen.getByText(name).closest("div[data-agent-id]");
    if (!(row instanceof HTMLElement)) throw new Error(`no row for ${name}`);
    return row;
  };

  it("leaves HTML dragging off so pointer reordering owns the gesture", () => {
    renderRail(trio());
    expect(rowOf("A").hasAttribute("draggable")).toBe(false);
  });

  it("restores the persisted order on mount", () => {
    localStorage.setItem(ORDER_KEY, JSON.stringify(["c", "a", "b"]));
    renderRail(trio());
    expect(rowOrder()).toEqual(["c", "a", "b"]);
  });

  it("moves a row with Alt + Shift + Arrow keys", () => {
    renderRail(trio());
    fireEvent.keyDown(rowOf("A"), { key: "ArrowDown", altKey: true, shiftKey: true });
    expect(rowOrder()).toEqual(["b", "a", "c"]);
    expect(JSON.parse(localStorage.getItem(ORDER_KEY) ?? "[]")).toEqual(["b", "a", "c"]);
    fireEvent.keyDown(rowOf("A"), { key: "ArrowUp", altKey: true, shiftKey: true });
    expect(rowOrder()).toEqual(["a", "b", "c"]);
  });

  it("ignores plain arrow keys without Alt", () => {
    renderRail(trio());
    fireEvent.keyDown(rowOf("A"), { key: "ArrowDown" });
    expect(rowOrder()).toEqual(["a", "b", "c"]);
    expect(localStorage.getItem(ORDER_KEY)).toBeNull();
  });

  it("locks rows while searching so the excerpt cannot file the order", () => {
    renderRail(trio());
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "a" } });
    expect(rowOf("A").className).not.toContain("cursor-grab");
    expect(localStorage.getItem(ORDER_KEY)).toBeNull();
  });
});

describe("RosterRail press-drag", () => {
  const ORDER_KEY = "society.roster.order";
  const renderRail = (agents: SocietyAgent[], props: Partial<RosterRailProps> = {}) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}>
      <RosterRail {...baseProps} {...props} agents={agents} activeAgentId={null} />
    </QueryClientProvider>);
  };

  const trio = () => [
    agent({ agentId: "a", name: "A" }),
    agent({ agentId: "b", name: "B" }),
    agent({ agentId: "c", name: "C" }),
  ];

  const rowOrder = () =>
    [...document.querySelectorAll("div[data-agent-id]")].map((el) =>
      el.getAttribute("data-agent-id"),
    );

  const rowOf = (name: string): HTMLElement => {
    const row = screen.getByText(name).closest("div[data-agent-id]");
    if (!(row instanceof HTMLElement)) throw new Error(`no row for ${name}`);
    return row;
  };

  /** Fake vertical layout so pointer heights resolve to real rows. */
  const mockLayout = (tops: Record<string, number>, height = 48) => {
    document.querySelectorAll("div[data-agent-id]").forEach((el) => {
      const id = el.getAttribute("data-agent-id") ?? "";
      const top = tops[id] ?? 0;
      vi.spyOn(el, "getBoundingClientRect").mockReturnValue({
        x: 0,
        y: top,
        top,
        left: 0,
        bottom: top + height,
        right: 200,
        width: 200,
        height,
        toJSON: () => ({}),
      } as DOMRect);
    });
  };

  /**
   * jsdom has no PointerEvent constructor, so testing-library drops
   * coordinates on pointer events. Dispatch real mouse events typed as
   * pointer events instead — the rail reads button/clientX/clientY off
   * them exactly like the browser does.
   */
  const pressRow = (el: Element, x: number, y: number) => {
    act(() => {
      el.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, cancelable: true, button: 0, clientX: x, clientY: y }));
    });
  };
  const movePointer = (x: number, y: number) => {
    act(() => {
      window.dispatchEvent(new MouseEvent("pointermove", { bubbles: true, cancelable: true, button: 0, clientX: x, clientY: y }));
    });
  };
  const releasePointer = (x: number, y: number) => {
    act(() => {
      window.dispatchEvent(new MouseEvent("pointerup", { bubbles: true, cancelable: true, button: 0, clientX: x, clientY: y }));
    });
  };

  it("starts from a press on the name itself and files the row at the drop point", () => {
    const onOpen = vi.fn();
    renderRail(trio(), { onOpen });
    mockLayout({ a: 0, b: 48, c: 96 });
    // Press on the inner name button, not the grip: this is the gesture that
    // did nothing before press-drag existed.
    pressRow(screen.getByText("A"), 10, 10);
    movePointer(10, 80);
    releasePointer(10, 80);
    expect(rowOrder()).toEqual(["b", "a", "c"]);
    expect(JSON.parse(localStorage.getItem(ORDER_KEY) ?? "[]")).toEqual(["b", "a", "c"]);
    // The click that follows a drag must not open the chat.
    fireEvent.click(screen.getByText("A"));
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("keeps a quick drop as a reorder even when grouping is available", () => {
    const onGroupAgents = vi.fn();
    renderRail(trio(), { onGroupAgents });
    mockLayout({ a: 0, b: 48, c: 96 });
    pressRow(rowOf("A"), 10, 10);
    movePointer(10, 80);
    releasePointer(10, 80);
    expect(rowOrder()).toEqual(["b", "a", "c"]);
    expect(onGroupAgents).not.toHaveBeenCalled();
  });

  it("groups two agents only after holding over the target row", () => {
    const onGroupAgents = vi.fn();
    renderRail(trio(), { onGroupAgents });
    mockLayout({ a: 0, b: 48, c: 96 });
    vi.useFakeTimers();
    pressRow(rowOf("A"), 10, 10);
    movePointer(10, 80);
    expect(screen.getByTestId("society-group-drop-hint").textContent).toBe("society.groups.hold_to_group");
    act(() => vi.advanceTimersByTime(760));
    expect(screen.getByTestId("society-group-drop-hint").textContent).toBe("society.groups.release_to_group");
    releasePointer(10, 80);
    expect(onGroupAgents).toHaveBeenCalledWith("a", "b");
    expect(rowOrder()).toEqual(["a", "b", "c"]);
  });

  it("adds an agent to a team by holding over its single sidebar row", () => {
    const onAddAgentToGroup = vi.fn();
    renderRail(trio(), {
      groups: [{ group_id: "team", name: "Team", members: ["b", "c"], created_ms: 1, updated_ms: 1 }],
      onAddAgentToGroup,
    });
    mockLayout({ a: 100 });
    vi.spyOn(screen.getByTestId("society-group-team"), "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, top: 0, left: 0, bottom: 48, right: 200,
      width: 200, height: 48, toJSON: () => ({}),
    } as DOMRect);
    vi.useFakeTimers();
    pressRow(rowOf("A"), 10, 110);
    movePointer(10, 20);
    act(() => vi.advanceTimersByTime(760));
    releasePointer(10, 20);
    expect(onAddAgentToGroup).toHaveBeenCalledWith("a", "team");
  });

  it("drops after the last row when released below the list", () => {
    renderRail(trio());
    mockLayout({ a: 0, b: 48, c: 96 });
    pressRow(rowOf("B"), 10, 60);
    movePointer(10, 220);
    releasePointer(10, 220);
    expect(rowOrder()).toEqual(["a", "c", "b"]);
    expect(JSON.parse(localStorage.getItem(ORDER_KEY) ?? "[]")).toEqual(["a", "c", "b"]);
  });

  it("treats a tiny press as a click so the chat still opens", () => {
    const onOpen = vi.fn();
    renderRail(trio(), { onOpen });
    mockLayout({ a: 0, b: 48, c: 96 });
    pressRow(rowOf("A"), 10, 10);
    releasePointer(11, 11);
    fireEvent.click(screen.getByText("A"));
    expect(onOpen).toHaveBeenCalledWith("a");
    expect(localStorage.getItem(ORDER_KEY)).toBeNull();
  });

  it("renders no grip handles; the whole row is the drag surface", () => {
    const { container } = renderRail(trio());
    expect(container.querySelector(".lucide-grip-vertical")).toBeNull();
    expect(rowOf("A").className).toContain("cursor-grab");
  });
});

it("shows and finds the lead by the wake-word name", () => {
  useEventStore.setState({ assistantName: "Hanna" });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <RosterRail {...baseProps} agents={[agent({ agentId: "jarvis", name: "Jarvis", tier: "lead" })]} activeAgentId={null} />
  </QueryClientProvider>);
  expect(screen.getByText("Hanna")).toBeTruthy();
  fireEvent.change(screen.getByRole("searchbox"), { target: { value: "hanna" } });
  expect(screen.getByText("Hanna")).toBeTruthy();
});

describe("RosterRail shell", () => {
  const renderRail = (agents: SocietyAgent[], props: Partial<RosterRailProps> = {}) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(<QueryClientProvider client={client}>
      <RosterRail {...baseProps} activeAgentId={null} {...props} agents={agents} />
    </QueryClientProvider>);
  };
  const waiting = (over: Partial<SocietyAgent> & Pick<SocietyAgent, "agentId" | "name">) =>
    ({ ...agent({ state: "waiting", ...over }), waiting_reason: { kind: "question", summary: "Which folder?" } }) as SocietyAgent;

  it("groups agents that wait on the person under Needs you, with the reason as the preview", () => {
    renderRail([agent({ agentId: "a", name: "A" }), waiting({ agentId: "b", name: "B" })]);
    const section = screen.getByTestId("roster-needs-you");
    expect(section.textContent).toContain("B");
    expect(section.textContent).toContain("society.shell.preview_needs_you · Which folder?");
    expect(section.textContent).not.toContain("A");
    expect(screen.getByLabelText("society.shell.status_needs_you")).toBeTruthy();
  });

  it("previews a draft before the last message, then the last message with its time", () => {
    const now = Date.now();
    renderRail([agent({ agentId: "a", name: "A" }), agent({ agentId: "b", name: "B" })], {
      activity: new Map([
        ["a", { draft: "check the invoices", lastMessage: "Done.", lastMs: now - 5 * 60_000 }],
        ["b", { lastMessage: "All **three** reports are in.", lastMs: now - 3 * 3_600_000 }],
      ]),
    });
    const previews = screen.getAllByTestId("roster-preview");
    expect(previews[0].dataset.kind).toBe("draft");
    expect(previews[0].textContent).toBe("society.shell.preview_draft check the invoices");
    expect(previews[1].dataset.kind).toBe("message");
    expect(previews[1].textContent).toBe("All three reports are in.");
    expect(screen.getByText(/^5\s?m/)).toBeTruthy();
  });

  it("pins an agent into the face grid and remembers it", () => {
    const agents = [agent({ agentId: "a", name: "A" }), agent({ agentId: "b", name: "B" })];
    const { unmount } = renderRail(agents);
    fireEvent.contextMenu(screen.getByText("B"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.shell.pin" }));
    expect(screen.getByTestId("roster-pins").textContent).toContain("B");
    expect(JSON.parse(localStorage.getItem("society.roster.pinned.v1") ?? "[]")).toEqual(["b"]);
    unmount();
    renderRail(agents);
    expect(screen.getByTestId("roster-pins").textContent).toContain("B");
  });

  it("filters to the agents that need the person and offers a way back when none do", () => {
    renderRail([agent({ agentId: "a", name: "A" }), waiting({ agentId: "b", name: "B" })]);
    fireEvent.click(screen.getByTestId("roster-filter-needs-you"));
    expect(screen.queryByText("A")).toBeNull();
    expect(screen.getByText("B")).toBeTruthy();
    fireEvent.click(screen.getByTestId("roster-filter-unread"));
    expect(screen.getByTestId("roster-empty").textContent).toContain("society.shell.empty_unread");
    fireEvent.click(screen.getByRole("button", { name: "society.shell.show_all" }));
    expect(screen.getByText("A")).toBeTruthy();
    expect(localStorage.getItem("society.roster.filter.v1")).toBe("all");
  });

  it("marks an agent unread from its menu", () => {
    renderRail([agent({ agentId: "a", name: "A" })]);
    fireEvent.contextMenu(screen.getByText("A"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.shell.mark_unread" }));
    expect(screen.getByLabelText("society.roster.unread")).toBeTruthy();
    fireEvent.contextMenu(screen.getByText("A"));
    fireEvent.click(screen.getByRole("menuitem", { name: "society.shell.mark_read" }));
    expect(screen.queryByLabelText("society.roster.unread")).toBeNull();
  });

  it("steps between agents with Alt + Arrow and jumps with Ctrl + digit, pinned first", () => {
    localStorage.setItem("society.roster.pinned.v1", JSON.stringify(["c"]));
    const onOpen = vi.fn();
    renderRail([agent({ agentId: "a", name: "A" }), agent({ agentId: "b", name: "B" }), agent({ agentId: "c", name: "C" })],
      { keyboard: true, activeAgentId: "a", onOpen });
    // Visible order: C (pinned), A, B.
    fireEvent.keyDown(window, { key: "ArrowDown", altKey: true });
    expect(onOpen).toHaveBeenLastCalledWith("b");
    fireEvent.keyDown(window, { key: "ArrowUp", altKey: true });
    expect(onOpen).toHaveBeenLastCalledWith("c");
    fireEvent.keyDown(window, { key: "1", code: "Digit1", ctrlKey: true });
    expect(onOpen).toHaveBeenLastCalledWith("c");
    fireEvent.keyDown(window, { key: "3", code: "Digit3", ctrlKey: true });
    expect(onOpen).toHaveBeenLastCalledWith("b");
    expect(onOpen).toHaveBeenCalledTimes(4);
  });

  it("leaves the keyboard alone when the shortcuts are off or a dialog is open", () => {
    const onOpen = vi.fn();
    const { unmount } = renderRail([agent({ agentId: "a", name: "A" }), agent({ agentId: "b", name: "B" })], { activeAgentId: "a", onOpen });
    fireEvent.keyDown(window, { key: "ArrowDown", altKey: true });
    expect(onOpen).not.toHaveBeenCalled();
    unmount();
    renderRail([agent({ agentId: "a", name: "A" }), agent({ agentId: "b", name: "B" })], { activeAgentId: "a", onOpen, keyboard: true });
    const modal = document.createElement("div");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    document.body.appendChild(modal);
    fireEvent.keyDown(window, { key: "ArrowDown", altKey: true });
    expect(onOpen).not.toHaveBeenCalled();
    modal.remove();
  });

  it("folds to an avatar rail that still opens agents", () => {
    const onOpen = vi.fn();
    const onToggleCollapsed = vi.fn();
    renderRail([agent({ agentId: "a", name: "A" }), waiting({ agentId: "b", name: "B" })], { collapsed: true, onToggleCollapsed, onOpen });
    expect(screen.getByTestId("society-roster-rail").dataset.collapsed).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "A" }));
    expect(onOpen).toHaveBeenCalledWith("a");
    fireEvent.click(screen.getByTestId("roster-expand"));
    expect(onToggleCollapsed).toHaveBeenCalled();
  });

  it("lists everyone on the folded rail even while a filter is chosen", () => {
    localStorage.setItem("society.roster.filter.v1", "needs-you");
    renderRail([agent({ agentId: "a", name: "A" }), waiting({ agentId: "b", name: "B" })], { collapsed: true });
    expect(screen.getByRole("button", { name: "A" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "B" })).toBeTruthy();
    // The choice itself is kept for when the rows come back.
    expect(localStorage.getItem("society.roster.filter.v1")).toBe("needs-you");
  });

  it("does not let pins of retired agents fill the pinned places", () => {
    localStorage.setItem("society.roster.pinned.v1", JSON.stringify(["gone1", "gone2", "gone3", "gone4", "gone5", "gone6", "gone7", "gone8"]));
    renderRail([agent({ agentId: "a", name: "A" })]);
    fireEvent.contextMenu(screen.getByText("A"));
    const pin = screen.getByRole("menuitem", { name: "society.shell.pin" }) as HTMLButtonElement;
    expect(pin.disabled).toBe(false);
    fireEvent.click(pin);
    expect(JSON.parse(localStorage.getItem("society.roster.pinned.v1") ?? "[]")).toEqual(["a"]);
  });

  it("shows no misleading empty state when every agent is hidden", () => {
    localStorage.setItem("society.roster.hidden-agent-ids", JSON.stringify(["a"]));
    renderRail([agent({ agentId: "a", name: "A" })]);
    expect(screen.queryByTestId("roster-empty")).toBeNull();
    expect(screen.getByText("society.roster.show_hidden")).toBeTruthy();
  });

  it("says what to do when there are no agents yet", () => {
    const onCreate = vi.fn();
    renderRail([], { onCreate });
    expect(screen.getByTestId("roster-empty").textContent).toContain("society.shell.empty_agents");
    fireEvent.click(screen.getByRole("button", { name: "society.shell.new_agent" }));
    expect(onCreate).toHaveBeenCalled();
  });

  it("offers a visible New team action", () => {
    renderRail([agent({ agentId: "a", name: "A" })], { onOpenGroup: () => undefined });
    expect(screen.getByTestId("society-create-group-button").textContent).toContain("society.groups.create");
  });
});
