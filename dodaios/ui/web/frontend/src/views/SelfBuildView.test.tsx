/**
 * "Built for you": builds sit on the shelf of what they ask of the person, a
 * proposal is built or turned down in one click, a trial is kept or undone in
 * one click, the pause and the society stop reach their routes, a build opens
 * into its case file, and the "built by" badge links back to its build.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { SelfBuildView } from "@/views/SelfBuildView";
import { BuiltByBadge } from "@/components/selfBuild/BuiltByBadge";
import { BuildDetail } from "@/views/selfBuild/BuildDetail";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { loadLocaleChunk, setUiLanguage } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useSelfBuildFocus } from "@/store/selfBuildFocus";
import type { Build, Noticed, SelfBuildStatus } from "@/lib/selfBuildApi";

const NOW = Date.now();

function build(overrides: Partial<Build>): Build {
  return {
    id: "b",
    kind: "skill",
    state: "proposed",
    signature: "s",
    title: "A build",
    case: "",
    evidence: [],
    proof: {},
    artefact: {},
    uses: 0,
    outcomes: {},
    note: "",
    created_ms: NOW - 3_600_000,
    updated_ms: NOW - 3_600_000,
    trial_started_ms: 0,
    last_used_ms: 0,
    undoable: true,
    ...overrides,
  };
}

const BUILDS: Build[] = [
  build({ id: "p1", title: "Rename invoice PDFs", evidence: ["t1", "t2", "t3"] }),
  build({ id: "p2", kind: "agent", title: "A release-notes writer" }),
  build({
    id: "t1",
    kind: "routine",
    state: "trial",
    title: "A standup digest",
    trial_started_ms: NOW - 3 * 86_400_000,
    uses: 4,
    outcomes: { accepted: 3, corrected: 1 },
    proof: { passed: true, judge: "shadow run", detail: "5 of 5" },
    artefact: { type: "routine", id: "task-1" },
    case: "You summarised the PR list every morning.",
  }),
  build({ id: "k1", state: "kept", title: "Mail humanizer", artefact: { type: "skill", id: "humanizer" } }),
  build({
    id: "u1",
    kind: "code",
    state: "undone",
    title: "Fix the flaky test",
    artefact: { type: "code", id: "https://github.com/octo/app/pull/7", repo: "octo/app", number: 7, draft: true, url: "https://github.com/octo/app/pull/7" },
  }),
];

const STATUS: SelfBuildStatus = {
  enabled: true,
  paused: false,
  silent: false,
  autonomy: { memory: "trial", skill: "suggest", routine: "suggest", agent: "suggest", code: "suggest" },
  builders: ["skill", "routine", "memory"],
};

interface Call {
  url: string;
  method: string;
  body: unknown;
}

const NOTICED: Noticed = {
  needs: [
    { id: 1, label: "Did I get any important emails?", times: 4, days: 2, first_ms: NOW - 2 * 86_400_000, last_ms: NOW - 3_600_000, stage: "counting", build_id: "" },
    { id: 2, label: "Summarise the open pull requests", times: 3, days: 3, first_ms: NOW - 3 * 86_400_000, last_ms: NOW - 7_200_000, stage: "proposed", build_id: "p1" },
  ],
  once: 5,
  more: 0,
  threshold: { times: 3, days: 3, window_days: 28 },
  quiet_start: { days: 7, since_ms: NOW - 2.5 * 86_400_000, until_ms: NOW + 4.5 * 86_400_000 },
};

function installFetch(status: SelfBuildStatus = STATUS, kill = false, builds: Build[] = BUILDS, noticed: Noticed = NOTICED) {
  const calls: Call[] = [];
  const routes: Record<string, (body: unknown) => unknown> = {
    "GET /api/self-build": () => ({ builds, status }),
    "GET /api/self-build/digest?hours=24": () => ({
      since_ms: NOW - 86_400_000,
      until_ms: NOW,
      counts: { proposed: 2, trial: 1 },
      live: 2,
      items: [],
    }),
    "GET /api/self-build/settings": () => ({
      settings: { trial_days: 14, trial_uses: 10 },
      levels: ["off", "suggest", "trial", "full"],
      bounds: {},
    }),
    "GET /api/self-build/provenance": () => ({
      items: { "skill:humanizer": { build_id: "k1", type: "skill", id: "humanizer", state: "kept", title: "Mail humanizer" } },
    }),
    "GET /api/self-build/t1": () => ({
      build: BUILDS[2],
      history: [
        { ts_ms: NOW - 5 * 86_400_000, from: "", to: "building", note: "" },
        { ts_ms: NOW - 4 * 86_400_000, from: "building", to: "proving", note: "built" },
        { ts_ms: NOW - 3 * 86_400_000, from: "proving", to: "trial", note: "proved" },
      ],
      cost: { tokens: 1200, usd: 0 },
    }),
    "GET /api/society/status": () => ({ kill_switch: kill }),
    "GET /api/self-build/noticed": () => noticed,
    "POST /api/self-build/p1/accept": () => ({ build: { ...BUILDS[0], state: "building" } }),
    "POST /api/self-build/p2/undo": () => ({ build: { ...BUILDS[1], state: "rejected" } }),
    "POST /api/self-build/t1/keep": () => ({ build: { ...BUILDS[2], state: "kept" } }),
    "POST /api/self-build/t1/undo": () => ({ build: { ...BUILDS[2], state: "undone" } }),
    "POST /api/self-build/pause": (body) => ({ ...status, paused: (body as { paused: boolean }).paused }),
    "POST /api/society/kill-switch": () => ({ engaged: true }),
  };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const handler = routes[`${method} ${url}`];
    if (!handler) return { ok: false, status: 404, json: async () => ({ detail: "nope" }) } as Response;
    const payload = handler(body);
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
  return calls;
}

function renderWith(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("SelfBuildView", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_build");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("puts every build on the shelf of what it asks of the person", async () => {
    installFetch();
    renderWith(<SelfBuildView />);
    const waiting = await screen.findByTestId("shelf-waiting");
    expect(within(waiting).getAllByTestId("build-row").map((r) => r.dataset.buildId)).toEqual(["p1", "p2"]);
    // Trials and kept helpers read as one "Active" list.
    const live = screen.getByTestId("shelf-live");
    expect(within(live).getByText("A standup digest")).toBeTruthy();
    expect(within(live).getByText("Mail humanizer")).toBeTruthy();
    // The past shelf is folded until asked for.
    const past = screen.getByTestId("shelf-past");
    expect(within(past).queryByTestId("build-row")).toBeNull();
    fireEvent.click(within(past).getByRole("button", { name: /show 1/i }));
    expect(within(past).getByText("Fix the flaky test")).toBeTruthy();
    // Simply watching is nothing to report: no banner.
    expect(screen.queryByTestId("self-build-banner")).toBeNull();
  });

  it("builds a proposal or turns it down in one click; a kind without a builder cannot be built", async () => {
    const calls = installFetch();
    renderWith(<SelfBuildView />);
    const first = (await screen.findAllByTestId("build-row"))[0];
    fireEvent.click(within(first).getByTestId("build-accept"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/self-build/p1/accept")).toBe(true));

    const agentRow = screen.getAllByTestId("build-row").find((r) => r.dataset.buildId === "p2")!;
    expect((within(agentRow).getByTestId("build-accept") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(agentRow).getByTestId("build-undo"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/self-build/p2/undo")).toBe(true));
  });

  it("opens a build into its case file and keeps or undoes a trial", async () => {
    const calls = installFetch();
    renderWith(<SelfBuildView />);
    const row = (await screen.findAllByTestId("build-row")).find((r) => r.dataset.buildId === "t1")!;
    fireEvent.click(row);
    const detail = await screen.findByTestId("build-detail");
    expect(within(detail).getByText("You summarised the PR list every morning.")).toBeTruthy();
    expect(within(detail).getByText("Passed")).toBeTruthy();
    expect(within(detail).getByText(/Day 3 of 14 · 4 of 10 uses/)).toBeTruthy();
    expect(within(detail).getByTestId("build-rail").dataset.reached).toBe("3");
    await waitFor(() => expect(within(detail).getAllByText(/Trial|On trial/).length).toBeGreaterThan(0));
    await waitFor(() => expect(within(detail).getByTestId("build-history").children.length).toBe(3));
    fireEvent.click(within(detail).getByTestId("build-keep"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/self-build/t1/keep")).toBe(true));
  });

  it("pauses the loop, and stops every agent only after a confirm", async () => {
    const calls = installFetch();
    renderWith(<SelfBuildView />);
    // Every page option sits behind the status pill.
    await screen.findAllByTestId("build-row");
    fireEvent.click(screen.getByTestId("self-build-menu"));
    fireEvent.click(screen.getByTestId("self-build-pause"));
    await waitFor(() =>
      expect(calls.find((c) => c.url === "/api/self-build/pause")?.body).toEqual({ paused: true }),
    );
    fireEvent.click(screen.getByTestId("self-build-menu"));
    fireEvent.click(screen.getByTestId("society-stop-all"));
    expect(calls.some((c) => c.url === "/api/society/kill-switch")).toBe(false);
    fireEvent.click(screen.getByTestId("stop-all-ok"));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url === "/api/society/kill-switch")).toBe(true));
  });

  it("says plainly when building is paused, quiet or every agent is stopped", async () => {
    installFetch({ ...STATUS, paused: true }, true);
    renderWith(<SelfBuildView />);
    expect(await screen.findByTestId("note-paused")).toBeTruthy();
    expect(await screen.findByTestId("note-stopped")).toBeTruthy();
    expect(screen.getByTestId("self-build-banner").dataset.tone).toBe("stopped");
    fireEvent.click(screen.getByTestId("self-build-menu"));
    expect(screen.queryByTestId("society-stop-all")).toBeNull();
    // Accepting would start a build, so it waits while building is paused.
    const first = (await screen.findAllByTestId("build-row"))[0];
    expect((within(first).getByTestId("build-accept") as HTMLButtonElement).disabled).toBe(true);
  });

  it("teaches the idea and shows what it is counting during the quiet start", async () => {
    installFetch({ ...STATUS, silent: true }, false, []);
    renderWith(<SelfBuildView />);
    const banner = await screen.findByTestId("self-build-banner");
    expect(banner.dataset.tone).toBe("silent");
    await waitFor(() => expect(banner.textContent).toMatch(/Learning how you work · day 3 of 7/));
    // The three steps sit behind one quiet toggle.
    const how = screen.getByTestId("self-build-how");
    fireEvent.click(within(how).getByRole("button", { name: /how does this work/i }));
    expect(how.textContent).toMatch(/It notices/);
    const needs = await screen.findAllByTestId("noticed-need");
    expect(needs[0].textContent).toMatch(/Did I get any important emails\?/);
    expect(needs[0].textContent).toMatch(/Asked 4 times · on 2 days/);
    expect(needs[0].textContent).toMatch(/1 more day to go/);
    expect(screen.getByTestId("self-build-noticed").textContent).toMatch(/5 requests noted once/);
  });

  it("links a need that became a suggestion to it", async () => {
    installFetch();
    renderWith(<SelfBuildView />);
    const needs = await screen.findAllByTestId("noticed-need");
    fireEvent.click(within(needs[1]).getByRole("button", { name: /see the suggestion/i }));
    expect((await screen.findByTestId("build-detail")).dataset.buildId).toBe("p1");
  });

  it("says nothing repeated yet when the miner has nothing", async () => {
    installFetch(STATUS, false, [], { ...NOTICED, needs: [], once: 0 });
    renderWith(<SelfBuildView />);
    const empty = await screen.findByTestId("noticed-empty");
    expect(empty.textContent).toMatch(/Nothing here yet/);
    expect(empty.textContent).toMatch(/on 3 different days/);
  });

  it("opens on the build a badge asked for", async () => {
    installFetch();
    useSelfBuildFocus.getState().request("t1");
    renderWith(<SelfBuildView />);
    expect((await screen.findByTestId("build-detail")).dataset.buildId).toBe("t1");
  });
});

describe("BuiltByBadge", () => {
  beforeEach(() => setUiLanguage("en"));
  afterEach(() => cleanup());

  it("marks only what a build made, and links to that build", async () => {
    installFetch();
    renderWith(
      <>
        <BuiltByBadge type="skill" id="humanizer" />
        <BuiltByBadge type="skill" id="my-own-skill" />
      </>,
    );
    const badge = await screen.findByTestId("built-by-badge");
    expect(screen.getAllByTestId("built-by-badge")).toHaveLength(1);
    fireEvent.click(badge);
    expect(useEventStore.getState().activeSection).toBe("self-build");
    expect(useSelfBuildFocus.getState().buildId).toBe("k1");
  });
});

describe("BuildDetail for code", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_build");
  });
  afterEach(() => cleanup());

  it("names the pull request, not its URL, and links to it", async () => {
    installFetch();
    useSelfBuildFocus.getState().request("u1");
    renderWith(<SelfBuildView />);
    const detail = await screen.findByTestId("build-detail");
    expect(within(detail).getByText("octo/app#7")).toBeTruthy();
    expect(within(detail).getByText("draft pull request")).toBeTruthy();
    expect(within(detail).getByRole("link", { name: /open/i }).getAttribute("href")).toBe("https://github.com/octo/app/pull/7");
  });

  it("opens the build's coding thread in the Agentic IDE", async () => {
    installFetch();
    const coding = build({
      id: "c1",
      kind: "code",
      state: "proving",
      title: "Add a greeting",
      artefact: { type: "code", id: "", repo: "octo/app", branch: "dodaios/issue-3-add-a-greeting", stage: "pushed", thread: "sess-42" },
    });
    renderWith(
      <BuildDetail build={coding} limits={undefined} canBuild busy={false} onAction={() => {}} onClose={() => {}} />,
    );
    const open = await screen.findByTestId("build-open-thread");
    expect(open.textContent).toContain("Open the coding thread");
    fireEvent.click(open);
    expect(useIdeThreadsStore.getState().selection.sessionId).toBe("sess-42");
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
  });

  it("offers no thread link for a code build without a coding thread", async () => {
    installFetch();
    renderWith(
      <BuildDetail build={BUILDS[4]} limits={undefined} canBuild busy={false} onAction={() => {}} onClose={() => {}} />,
    );
    await screen.findByTestId("build-detail");
    expect(screen.queryByTestId("build-open-thread")).toBeNull();
  });
});
