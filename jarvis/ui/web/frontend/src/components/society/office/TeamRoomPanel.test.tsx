import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import type { SocietyAgent } from "../data";
import type { SocietyChatGroup } from "@/lib/societyChatGroups";
import { buildOfficeLayout } from "./officeLayout";
import { buildNavGrid } from "./officeNav";
import { useOfficeStore } from "./officeStore";
import { emptyRound, useTeamwork } from "./teamwork";
import { TeamRoomPanel } from "./TeamRoomPanel";

const agents = [
  { agentId: "a1", name: "Ada Lovelace", title: "Research", state: "idle", palette: { primary: "#4f7cac" } },
  { agentId: "a2", name: "Bo", title: "Writer", state: "working", palette: { primary: "#c8553d" } },
  { agentId: "a3", name: "Cy", title: "", state: "idle", palette: { primary: "#5e9c76" } },
] as SocietyAgent[];
const layout = buildOfficeLayout(agents.map((a, i) => ({
  agentId: a.agentId, name: a.name, tier: "specialist" as const, providerLabel: "Codex", state: a.state, createdMs: i,
})));

beforeAll(async () => { await loadLocaleChunk("society"); });

let groups: SocietyChatGroup[];
const calls: { method: string; url: string; body: unknown }[] = [];

beforeEach(() => {
  groups = [{ group_id: "g1", name: "Launch crew", members: ["a1", "a2"], created_ms: 1, updated_ms: 1 }];
  calls.length = 0;
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ method, url, body });
    if (method === "POST") {
      const group = { group_id: "g2", name: body.name, members: body.members, created_ms: 2, updated_ms: 2 };
      groups = [...groups, group];
      return new Response(JSON.stringify({ group }));
    }
    if (method === "PATCH") {
      groups = groups.map((g) => (url.endsWith(g.group_id) ? { ...g, name: body.name, members: body.members } : g));
      return new Response(JSON.stringify({ group: groups.find((g) => url.endsWith(g.group_id)) }));
    }
    if (method === "DELETE") {
      groups = groups.filter((g) => !url.endsWith(g.group_id));
      return new Response("{}");
    }
    return new Response(JSON.stringify({ groups }));
  });
  useOfficeStore.setState({ meeting: null, summons: {}, teamDraft: [], selection: null, walkTo: null });
  useTeamwork.setState({ rounds: {} });
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function mount(props: Partial<Parameters<typeof TeamRoomPanel>[0]> = {}, onOpenGroup = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <TeamRoomPanel agents={agents} layout={layout} sample={false} actions={{ onOpenAgent: vi.fn(), onOpenLedger: vi.fn(), onOpenGroup }} {...props} />
    </QueryClientProvider>,
  );
  return onOpenGroup;
}

describe("team room panel", () => {
  test("shows each team with its members and seats them at the table on Meet", async () => {
    mount();
    expect(await screen.findByText("Launch crew")).toBeTruthy();
    expect(screen.getByText(/2 members · 1 working/)).toBeTruthy();
    // Every member shows as a face that names the agent and its state.
    expect(screen.getByTitle("Ada Lovelace · Idle")).toBeTruthy();
    expect(screen.getByTitle("Bo · Working")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Meet with Launch crew at the table" }));
    const { meeting, summons } = useOfficeStore.getState();
    expect(meeting?.groupId).toBe("g1");
    expect(summons.a1.spotId).toMatch(/^meeting-/);
    expect(summons.a2.spotId).toMatch(/^meeting-/);
    // The running meeting shows up top, and ending it releases everyone.
    // The gathering is named for what it is, with no live mark: nothing was posted and no round runs.
    expect(await screen.findByText("Launch crew · called to the table")).toBeTruthy();
    expect(screen.getByText(/nothing is posted to the team's chat/)).toBeTruthy();
    expect(screen.queryByText("Live")).toBeNull();
    expect((screen.getByRole("button", { name: "Meet with Launch crew at the table" }) as HTMLButtonElement).textContent).toBe("Called");
    expect(screen.getByText(/Working, so they stay at their desk: Bo/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send them back" }));
    expect(useOfficeStore.getState().meeting).toBeNull();
    expect(useOfficeStore.getState().summons).toEqual({});
  });

  test("renames a team and changes its members", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByDisplayValue("Launch crew"), { target: { value: "Crew two" } });
    fireEvent.click(screen.getAllByRole("checkbox", { name: /Cy/ })[0]);
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PATCH")).toBe(true));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ name: "Crew two", members: ["a1", "a2", "a3"] });
  });

  test("deletes a team only after a second, explicit click", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete team" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Really delete?" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url.endsWith("/g1"))).toBe(true));
  });

  test("puts a new team together from the free agents and starts its meeting", async () => {
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New team" }));
    fireEvent.click(screen.getByRole("button", { name: "All free agents" }));
    expect(screen.getByText("2 selected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Create team and meet (2)" }));
    await waitFor(() => expect(useOfficeStore.getState().meeting?.groupId).toBe("g2"));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "Ada Lovelace + Cy", members: ["a1", "a3"] });
    expect(useOfficeStore.getState().teamDraft).toEqual([]);
  });

  test("with no team yet it opens straight on the new-team form, with nothing to cancel back to", async () => {
    groups = [];
    mount();
    expect(await screen.findByRole("region", { name: "New team" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "New team" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    const create = screen.getByRole("button", { name: "Create team and meet (0)" }) as HTMLButtonElement;
    expect(create.disabled).toBe(true);
    expect(screen.getByText("Pick at least two agents to create a team.")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /Ada Lovelace/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Cy/ }));
    expect((screen.getByRole("button", { name: "Create team and meet (2)" }) as HTMLButtonElement).disabled).toBe(false);
  });

  test("eight teams are eight rows, and the new-team form takes the sheet to itself", async () => {
    groups = Array.from({ length: 8 }, (_, i) => ({ group_id: `g${i}`, name: `Team ${i}`, members: ["a1", "a2"], created_ms: i, updated_ms: i }));
    mount();
    expect(await screen.findByText("Team 7")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(8);
    expect(screen.getAllByRole("button", { name: /^Meet with Team \d at the table$/ })).toHaveLength(8);
    fireEvent.click(screen.getByRole("button", { name: "New team" }));
    // One job at a time: the list steps aside, so the form's buttons are never pushed off the sheet.
    expect(screen.queryByText("Team 7")).toBeNull();
    expect(screen.getByRole("button", { name: "Create team and meet (0)" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Team 7")).toBeTruthy();
  });

  test("forty agents: the picker scrolls on its own, searches, and the buttons stay outside the list", async () => {
    const many = Array.from({ length: 40 }, (_, i) => ({
      agentId: `m${i}`, name: `Agent ${String(i).padStart(2, "0")}`, title: i % 2 ? "Writer" : "Research",
      state: i % 4 === 0 ? "working" : "idle", palette: { primary: "#4f7cac" },
    })) as SocietyAgent[];
    groups = [];
    mount({ agents: many });
    const list = await screen.findByRole("group", { name: "Members" });
    expect(list.className).toContain("team-picker-list");
    expect(within(list).getAllByRole("checkbox")).toHaveLength(40);
    // The buttons are not inside the scrolling list: they sit in the footer that stays at the sheet's edge.
    const create = screen.getByRole("button", { name: "Create team and meet (0)" });
    expect(list.contains(create)).toBe(false);
    expect(create.closest(".team-footer")).toBeTruthy();

    fireEvent.change(screen.getByRole("searchbox", { name: "Find an agent" }), { target: { value: "agent 07" } });
    expect(within(list).getAllByRole("checkbox")).toHaveLength(1);
    fireEvent.click(within(list).getByRole("checkbox", { name: /Agent 07/ }));
    fireEvent.change(screen.getByRole("searchbox", { name: "Find an agent" }), { target: { value: "nobody" } });
    expect(screen.getByText("No agent matches.")).toBeTruthy();
    // The pick survives the search.
    expect(screen.getByText("1 selected")).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox", { name: "Find an agent" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "All free agents" }));
    expect(screen.getByText("30 selected")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create team and meet (30)" })).toBeTruthy();
  });

  test("a working agent's face is its symbol, never the three thinking dots", async () => {
    mount();
    await screen.findByText("Launch crew");
    // A face is the agent's pixel creature, or its shape as a symbol or a 3D figure.
    const drawn = "[data-agent-creature], [data-agent-symbol], [data-agent-figure]";
    const face = screen.getByTitle("Bo · Working");
    expect(face.querySelector(drawn)).toBeTruthy();
    expect(face.querySelector("[data-thinking='true']")).toBeNull();
    expect(face.querySelector("[data-creature-state]")?.getAttribute("data-creature-state") ?? "idle").toBe("idle");
    // Every face sits on the neutral tile, so a white or black symbol never vanishes into the dialog.
    expect(face.querySelector(".office-face")?.querySelector(drawn)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const picker = screen.getByRole("group", { name: "Members" });
    expect([...picker.querySelectorAll(".office-face")].filter(tile => tile.querySelector(drawn))).toHaveLength(agents.length);
  });

  test("opened to start a team it shows the new-team form at once, and Cancel leads to the teams", async () => {
    mount({ compose: true });
    expect(await screen.findByRole("region", { name: "New team" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Create team and meet (0)" })).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeTruthy());
    expect(screen.queryByText("Launch crew")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Launch crew")).toBeTruthy();
  });

  test("a team is marked live only while the backend says its round is answering", async () => {
    mount();
    await screen.findByText("Launch crew");
    expect(screen.queryByText("Live")).toBeNull();
    act(() => useTeamwork.getState().setRound({ ...emptyRound("g1"), running: true }));
    expect(screen.getByText("Live")).toBeTruthy();
    // The round ended: the mark goes, whatever the person has called together on the map.
    act(() => useTeamwork.getState().setRound({ ...emptyRound("g1"), running: false }));
    fireEvent.click(screen.getByRole("button", { name: "Meet with Launch crew at the table" }));
    expect(await screen.findByText("Launch crew · called to the table")).toBeTruthy();
    expect(screen.queryByText("Live")).toBeNull();
  });

  test("opens the real team chat from a team's row", async () => {
    const onOpenGroup = mount();
    fireEvent.click(await screen.findByRole("button", { name: "Open the chat of Launch crew" }));
    expect(onOpenGroup).toHaveBeenCalledWith("g1");
  });

  test("steps aside when a team is sent to the table, so the person sees it gather", async () => {
    const onMeet = vi.fn();
    mount({ onMeet });
    fireEvent.click(await screen.findByRole("button", { name: "Meet with Launch crew at the table" }));
    expect(onMeet).toHaveBeenCalledOnce();
  });

  test("a studio board opens its own team with every member, and the other teams one step away", async () => {
    groups = [...groups, { group_id: "g9", name: "Night shift", members: ["a2", "a3"], created_ms: 3, updated_ms: 3 }];
    mount({ focus: { teamId: "g1", members: ["a1", "a2"] } });
    expect(await screen.findByText("Launch crew")).toBeTruthy();
    expect(screen.getByText("This team")).toBeTruthy();
    expect(screen.queryByText("Night shift")).toBeNull();
    // The members are listed by name, each with a way to talk to them.
    fireEvent.click(screen.getByRole("button", { name: "Talk to Ada Lovelace" }));
    expect(useOfficeStore.getState().selection).toEqual({ kind: "agent", id: "a1" });
    fireEvent.click(screen.getByRole("button", { name: "All teams (2)" }));
    expect(screen.getByText("Night shift")).toBeTruthy();
    expect(screen.getByText("Your teams")).toBeTruthy();
  });

  test("from its own studio board a team meets at that board, not at the team room's table", async () => {
    const campus = buildOfficeLayout(agents.map((a, i) => ({
      agentId: a.agentId, name: a.name, tier: "specialist" as const, providerLabel: "Codex", state: a.state, createdMs: i,
    })), { teams: [{ id: "g1", name: "Launch crew", members: ["a1", "a2"], createdMs: 1 }] });
    const studio = campus.studios!.find((s) => s.teamId === "g1")!;
    expect(studio.board).toBeTruthy();
    groups = [...groups, { group_id: "g9", name: "Night shift", members: ["a2", "a3"], created_ms: 3, updated_ms: 3 }];
    mount({ layout: campus, focus: { teamId: "g1", members: studio.members, studio, grid: buildNavGrid(campus) } });
    expect(await screen.findByText("Launch crew")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Meet with Launch crew at the table" })).toBeNull();
    // Another team, reached through "All teams", has no board here: it still meets at the table.
    fireEvent.click(screen.getByRole("button", { name: "All teams (2)" }));
    expect(screen.getByRole("button", { name: "Meet with Night shift at the table" })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Meet with Launch crew at the board" }));
    const { meeting, summons } = useOfficeStore.getState();
    expect(meeting).toMatchObject({ groupId: "g1", boardId: studio.board!.id });
    // Each member is called to a standing place in the arcs in front of the studio's board.
    expect(summons.a1.spotId).toMatch(new RegExp(`^fan:${studio.deptId}:`));
    expect(summons.a2.spotId).toMatch(new RegExp(`^fan:${studio.deptId}:`));
    expect(summons.a1.spotId).not.toBe(summons.a2.spotId);
    // The running meeting says where it is, and "go there" walks to that board.
    expect(await screen.findByText(/of 2 at the board/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Go to the board" }));
    const goal = useOfficeStore.getState().walkTo!.point;
    expect(Math.hypot(goal.x - studio.board!.x, goal.z - studio.board!.z)).toBeLessThan(2);
  });

  test("the board of agents without a team offers to make them one", async () => {
    mount({ focus: { teamId: null, members: ["a2", "a3"] } });
    expect(await screen.findByText(/not in a team yet/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "New team" }));
    // The people sitting there are picked already.
    expect(useOfficeStore.getState().teamDraft).toEqual(["a2", "a3"]);
    expect(screen.getByRole("button", { name: "Create team and meet (2)" })).toBeTruthy();
  });
});
