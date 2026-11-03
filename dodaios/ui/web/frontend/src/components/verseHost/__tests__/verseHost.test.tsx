import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { handleVerseOpen, VERSE_OPEN_GROUP_EVENT, VERSE_STATUS_EVENT } from "../openRequest";
import { LAUNCHER_STRINGS } from "../strings";
import { resetLauncherImportForTests, VerseLauncherCard } from "../VerseLauncherCard";
import { parseStatus } from "../verseHostApi";

function respond(map: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const key = `${init?.method ?? "GET"} ${url}`;
    const body = map[key] ?? map[url];
    if (body === undefined) return new Response("{}", { status: 404 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

const running = { status: "running", state: "visible", pid: 41, vram_mb: 4200, fps: 120, crash_report: null };
const stopped = { status: "stopped", state: null, pid: null, vram_mb: null, fps: null, crash_report: null };

describe("parseStatus", () => {
  it("falls back to stopped for an unknown status", () => {
    expect(parseStatus({ status: "weird" }).status).toBe("stopped");
    expect(parseStatus(running)).toEqual(running);
  });
});

describe("launcher strings", () => {
  it("every language has every key", () => {
    const keys = Object.keys(LAUNCHER_STRINGS.en).sort();
    for (const table of Object.values(LAUNCHER_STRINGS)) expect(Object.keys(table).sort()).toEqual(keys);
  });
});

describe("VerseLauncherCard", () => {
  beforeEach(() => resetLauncherImportForTests());
  afterEach(() => vi.unstubAllGlobals());

  it("shows the status, opens the Verse and a quick duel", async () => {
    const fetchMock = respond({
      "GET /api/verse/status": stopped,
      "POST /api/verse/show": running,
      "POST /api/verse/settings/import": { imported: [] },
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<VerseLauncherCard />);
    await screen.findByText("Ready to start.");
    fireEvent.click(screen.getByText("Quick duel"));
    await screen.findByText(/Running · on screen/);
    const show = fetchMock.mock.calls.find(([u, i]) => String(u) === "/api/verse/show" && i?.method === "POST");
    expect(JSON.parse(String(show?.[1]?.body)).reason).toBe("quick_start_duel");
    expect(screen.getByText("Close")).toBeTruthy();
  });

  it("re-reads on a VerseStatusChanged and offers a restart after a crash loop", async () => {
    let body: unknown = stopped;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/verse/status") return new Response(JSON.stringify(body));
      return new Response(JSON.stringify({ imported: [] }));
    }));
    render(<VerseLauncherCard />);
    await screen.findByText("Ready to start.");
    body = { ...stopped, status: "crashed", crash_report: "C:/data/verse/crashes/1" };
    act(() => { window.dispatchEvent(new CustomEvent(VERSE_STATUS_EVENT)); });
    await screen.findByText("The Verse stopped after repeated crashes.");
    expect(screen.getByText("Start again")).toBeTruthy();
  });

  it("says so on a machine that cannot run it", async () => {
    vi.stubGlobal("fetch", respond({ "GET /api/verse/status": { ...stopped, status: "unsupported" }, "POST /api/verse/settings/import": { imported: [] } }));
    render(<VerseLauncherCard />);
    await waitFor(() => expect(screen.getByTestId("verse-launcher-status").textContent).toMatch(/graphics card/));
    expect(screen.queryByText("Open the Verse")).toBeNull();
  });
});

describe("handleVerseOpen", () => {
  it("opens a pane maximised in the IDE, with its changes view on request", () => {
    const requestPane = vi.fn();
    useIdeChatStore.setState({ requestPane } as never);
    useEventStore.setState({ solo: false } as never);
    expect(handleVerseOpen({ target: "pane", workspace_id: "ws_91", name: "T1", open: "changes" })).toBe(true);
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
    expect(requestPane).toHaveBeenCalledWith("ws_91", "T1", { maximize: true, open: "changes" });
  });

  it("opens the agents section and names the group", () => {
    useEventStore.setState({ solo: false } as never);
    const seen: unknown[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(VERSE_OPEN_GROUP_EVENT, on);
    expect(handleVerseOpen({ target: "group", group_id: "grp_a" })).toBe(true);
    window.removeEventListener(VERSE_OPEN_GROUP_EVENT, on);
    expect(useEventStore.getState().activeSection).toBe("agents");
    expect(seen).toEqual([{ groupId: "grp_a" }]);
  });

  it("ignores unknown targets and detached windows", () => {
    expect(handleVerseOpen({ target: "bogus" }, false)).toBe(false);
    expect(handleVerseOpen({ target: "ide" }, true)).toBe(false);
  });
});
