/**
 * Self-improvement: a new installation says plainly that nothing is measured
 * yet and draws nothing; a measured area shows its advantage with the scores
 * and range behind it and never words an uncertain number as a win; a change
 * is taken back in one click; the stop reaches its route; a change opens into
 * its case file with the stored reasons; the nights fold after three.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { SelfImprovementView } from "@/views/SelfImprovementView";
import { loadLocaleChunk, setUiLanguage } from "@/i18n";
import { certainty, effectWords, fmtPoints } from "@/views/selfImprovement/words";
import type {
  AdvantagePoint,
  LearnedChange,
  Measurement,
  Night,
  SelfImprovementOverview,
} from "@/lib/selfImprovementApi";

const NOW = Date.now();
const DAY = 86_400_000;

const LIMITS = { idle_after_s: 900, every_s: 72_000, budget_share: 0.2, max_model_calls: 8 };

function emptyOverview(): SelfImprovementOverview {
  return {
    status: { app: "5.7.0", paused: false, readonly: false, last_night_ms: 0, next_night_ms: 0, decides_on: ["mined", "made"], own_tasks: true },
    limits: LIMITS,
    domains: [
      { domain: "recall", tasks: { practice: 0, select: 0, guard: 0, sealed: 0 }, tasks_total: 0, all_tasks: {}, measured: false, point: null },
    ],
    series: [],
    stack: [],
    candidates: [],
    nights: [],
    resting: [],
    now_ms: NOW,
  };
}

function point(daysAgo: number, diff: number, low: number, high: number, app = "5.7.0"): AdvantagePoint {
  return {
    ts_ms: NOW - daysAgo * DAY,
    app,
    domain: "recall",
    split: "sealed",
    source: "own",
    now_score: 0.836,
    factory_score: 0.815,
    diff,
    low,
    high,
    n: 54,
    now_tokens: 61,
    factory_tokens: 116,
  };
}

function measurement(step: string, diff: number, low: number, high: number, n: number, cost: number, reason: string): Measurement {
  return { ts_ms: NOW - 2 * DAY, step, verdict: "accept", split: step === "admit" ? "select" : "guard", reason, domain: "recall", diff, low, high, n, cost_diff: cost };
}

function change(overrides: Partial<LearnedChange>): LearnedChange {
  return {
    id: "c",
    surface: "parameter",
    target: "recall.min_score",
    state: "live",
    author: "tuner",
    reason: "on the practice tasks: +0.638 score",
    since_ms: NOW - 2 * DAY,
    before: null,
    after: 4,
    default: 0,
    doc: "How well a memory must match.",
    admitted: null,
    last_check: null,
    ...overrides,
  };
}

function night(daysAgo: number, overrides: Partial<Night> = {}): Night {
  return {
    ts_ms: NOW - daysAgo * DAY,
    app: "5.7.0",
    paused: false,
    updated_from: "",
    settled: [],
    proposed: [],
    decided: [],
    measured: [],
    ...overrides,
  };
}

function fullOverview(): SelfImprovementOverview {
  const points = [point(4, 0.004, -0.03, 0.04, "5.6.0"), point(3, 0.012, -0.02, 0.045, "5.6.0"), point(1, 0.021, -0.01, 0.05)];
  return {
    ...emptyOverview(),
    status: { ...emptyOverview().status, last_night_ms: NOW - 3 * 3_600_000, next_night_ms: NOW + 17 * 3_600_000 },
    domains: [
      {
        domain: "recall",
        tasks: { practice: 108, select: 84, guard: 50, sealed: 54 },
        tasks_total: 296,
        all_tasks: {},
        measured: true,
        point: points[2],
      },
    ],
    series: points,
    stack: [
      change({
        id: "c1",
        target: "recall.min_score",
        state: "trial",
        after: 4,
        admitted: measurement("admit", 0.119, 0.02, 0.21, 84, 12, "better on 84 tasks"),
      }),
      change({
        id: "c2",
        target: "recall.turn_limit",
        state: "live",
        before: null,
        after: 2,
        default: 6,
        admitted: measurement("admit", 0, -0.04, 0.04, 150, -55, "as good on 150 tasks, and 47% cheaper"),
        last_check: measurement("settle", 0, -0.05, 0.05, 50, -55, "held on 50 new tasks"),
      }),
    ],
    nights: [
      night(1, {
        updated_from: "5.6.0",
        decided: [
          {
            change_id: "c1",
            target: "recall.min_score",
            outcome: "admitted",
            was: "proposed",
            evidence: { verdict: "accept", split: "select", reason: "better on 84 tasks", target: { domain: "recall", diff: 0.119, low: 0.02, high: 0.21, n: 84, cost_diff: 12 } },
          },
        ],
        measured: [points[2]],
      }),
      night(2),
      night(3, { paused: true }),
      night(4),
      night(5),
    ],
  };
}

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function installFetch(overview: SelfImprovementOverview | null, status = 200) {
  const calls: Call[] = [];
  let current = overview;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (status !== 200 || !current) {
      return { ok: false, status, json: async () => ({ detail: "self-improvement is not running" }) } as Response;
    }
    if (method === "GET" && url === "/api/self-improvement") {
      const payload = current;
      return { ok: true, status: 200, json: async () => payload } as Response;
    }
    if (method === "POST" && url === "/api/self-improvement/pause") {
      const paused = (body as { paused: boolean }).paused;
      current = { ...current, status: { ...current.status, paused } };
      return { ok: true, status: 200, json: async () => ({ ok: true, paused }) } as Response;
    }
    const undo = /^\/api\/self-improvement\/changes\/([^/]+)\/undo$/.exec(url);
    if (method === "POST" && undo) {
      current = { ...current, stack: current.stack.filter((c) => c.id !== undo[1]) };
      return { ok: true, status: 200, json: async () => ({ ok: true, reverted: [undo[1]] }) } as Response;
    }
    return { ok: false, status: 404, json: async () => ({ detail: "nope" }) } as Response;
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
  return calls;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SelfImprovementView />
    </QueryClientProvider>,
  );
}

describe("SelfImprovementView", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_improvement");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("says plainly that nothing is measured yet on a new installation, and draws nothing", async () => {
    installFetch(emptyOverview());
    renderView();
    const empty = await screen.findByTestId("si-empty");
    expect(empty.textContent).toContain("Nothing is measured yet");
    expect(empty.textContent).toContain("builds test tasks from your own memory and messages");
    expect(screen.queryByTestId("si-area")).toBeNull();
    expect(screen.queryByTestId("si-curve")).toBeNull();
    expect(screen.queryByTestId("si-headline")).toBeNull();
    expect(screen.getByTestId("si-state").dataset.state).toBe("running");
    expect(screen.getByTestId("si-state").textContent).toContain("15 minutes");
    expect(screen.getByTestId("si-stop")).toBeTruthy();
    expect(screen.getByTestId("si-limits").textContent).toContain("at most 8 times a night");
    expect(screen.getByTestId("si-limits").textContent).toContain("never on a key that is billed per token");
    expect(screen.getByTestId("si-limits").textContent).toContain("Measuring itself asks no model.");
    expect(screen.getByTestId("si-limits").textContent).not.toContain("Today it asks no model");
    expect(screen.getByTestId("si-privacy").textContent).toContain("Memories marked sensitive are never sent");
  });

  it("names the larger allowance of the first nights when the backend reports one", async () => {
    const data = emptyOverview();
    data.limits = { ...data.limits, ramp_model_calls: 24 };
    installFetch(data);
    renderView();
    await screen.findByTestId("si-empty");
    const limits = screen.getByTestId("si-limits").textContent ?? "";
    expect(limits).toContain("at most 8 times a night (24 in the first nights, while there are too few tasks to decide on)");
    expect(limits).toContain("never on a key that is billed per token");
  });

  it("splits the scores into tasks that need a memory and tasks that need none", async () => {
    const data = fullOverview();
    const shown = data.domains[0].point!;
    data.domains[0].point = {
      ...shown,
      parts: {
        needs_memory: { n: 19, now_score: 0.95, factory_score: 0.97, now_tokens: 80, factory_tokens: 120 },
        needs_none: { n: 17, now_score: 0.6, factory_score: 0.18, now_tokens: 10, factory_tokens: 104 },
        something_new: { n: 3, now_score: 1, factory_score: 1, now_tokens: 1, factory_tokens: 1 },
      },
    };
    installFetch(data);
    renderView();
    const memory = await screen.findByTestId("si-part-needs_memory");
    expect(memory.textContent).toBe("now 95.0%, as shipped 97.0% (19 tasks)");
    expect(screen.getByTestId("si-part-needs_none").textContent).toBe("now 60.0%, as shipped 18.0% (17 tasks)");
    expect(screen.getByText("Memory needed")).toBeTruthy();
    expect(screen.getByText("No memory needed")).toBeTruthy();
    expect(screen.queryByTestId("si-part-something_new")).toBeNull();
  });

  it("shows no part rows for a point measured before parts existed", async () => {
    installFetch(fullOverview());
    renderView();
    await screen.findByTestId("si-scores");
    expect(screen.queryByTestId("si-part-needs_memory")).toBeNull();
  });

  it("shows the advantage with the scores behind it, and calls an uncertain number not certain", async () => {
    installFetch(fullOverview());
    renderView();
    const headline = await screen.findByTestId("si-headline");
    expect(headline.dataset.certainty).toBe("unclear");
    expect(headline.textContent).toContain("+2.1");
    expect(within(headline).getByTestId("si-certainty").textContent).toBe("not certain yet");
    expect(headline.textContent).toContain("includes zero");
    expect(screen.getByTestId("si-scores").textContent).toContain("83.6%");
    expect(screen.getByTestId("si-scores").textContent).toContain("54 tasks");
    // A shorter prompt at an uncertain quality is a result of its own, in the headline.
    expect(screen.getByTestId("si-saving").textContent).toBe("47%shorter");
    expect(headline.textContent).toContain("116 → 61 tokens");
    expect(screen.queryByTestId("si-cost")).toBeNull();
    const range = screen.getByTestId("si-range").textContent ?? "";
    expect(range).toContain("as good as shipped");
    expect(range).toContain("47% shorter");
    expect(range).not.toMatch(/gain|better/);
    expect(screen.queryByTestId("si-empty")).toBeNull();
    expect(screen.getByTestId("si-curve")).toBeTruthy();
  });

  it("words each change with its measured effect", async () => {
    installFetch(fullOverview());
    renderView();
    const rows = await screen.findAllByTestId("si-change-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("Minimum match for a memory");
    expect(rows[0].textContent).toContain("0 → 4");
    expect(rows[0].textContent).toContain("On trial");
    expect(rows[0].textContent).toContain("+11.9 points on 84 tasks (between +2.0 and +21.0)");
    expect(rows[1].textContent).toContain("Memories per message");
    expect(rows[1].textContent).toContain("6 → 2");
    expect(rows[1].textContent).toContain("Kept");
    expect(rows[1].textContent).toContain("as good on 150 tasks, prompt 55 tokens shorter");
    expect(rows[1].textContent).toContain("held again on 50 tasks");
  });

  it("takes a change back in one click, without asking again", async () => {
    const calls = installFetch(fullOverview());
    renderView();
    const rows = await screen.findAllByTestId("si-change-row");
    fireEvent.click(within(rows[0]).getByTestId("si-undo"));
    await waitFor(() => expect(screen.getAllByTestId("si-change-row")).toHaveLength(1));
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/self-improvement/changes/c1/undo")).toBe(true);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("stops and resumes through the one button", async () => {
    const calls = installFetch(fullOverview());
    renderView();
    fireEvent.click(await screen.findByTestId("si-stop"));
    await screen.findByTestId("si-resume");
    expect(screen.getByTestId("si-state").dataset.state).toBe("stopped");
    expect(calls.find((c) => c.url === "/api/self-improvement/pause")?.body).toEqual({ paused: true });
    fireEvent.click(screen.getByTestId("si-resume"));
    await screen.findByTestId("si-stop");
    expect(calls.filter((c) => c.url === "/api/self-improvement/pause").at(-1)?.body).toEqual({ paused: false });
  });

  it("opens a change into its case file with the stored reasons as they are", async () => {
    installFetch(fullOverview());
    renderView();
    const rows = await screen.findAllByTestId("si-change-row");
    fireEvent.click(rows[1]);
    const detail = await screen.findByTestId("si-change-detail");
    expect(within(detail).getByTestId("si-detail-values").textContent).toBe("6 → 2");
    expect(within(detail).getByTestId("si-detail-reason-admitted").textContent).toBe("as good on 150 tasks, and 47% cheaper");
    expect(within(detail).getByTestId("si-detail-reason-checked").textContent).toBe("held on 50 new tasks");
    expect(detail.textContent).toContain("The tuner");
    fireEvent.click(within(detail).getByTestId("si-detail-undo"));
    await waitFor(() => expect(screen.queryByTestId("si-change-detail")).toBeNull());
  });

  it("shows three nights, folds the rest, and marks an update", async () => {
    installFetch(fullOverview());
    renderView();
    const nights = await screen.findAllByTestId("si-night");
    expect(nights).toHaveLength(3);
    expect(nights[0].textContent).toContain("updated from 5.6.0 to 5.7.0");
    expect(nights[0].textContent).toContain("Measured Minimum match for a memory: let in on trial, +11.9 points on 84 tasks");
    expect(nights[1].textContent).toContain("found nothing to measure yet");
    expect(nights[2].textContent).toContain("Stopped: nothing was done.");
    const toggle = screen.getByTestId("si-nights-toggle");
    expect(toggle.textContent).toContain("Show 2 earlier nights");
    fireEvent.click(toggle);
    expect(screen.getAllByTestId("si-night")).toHaveLength(5);
  });

  it("draws no curve from fewer than two points", async () => {
    const one = fullOverview();
    one.series = one.series.slice(-1);
    installFetch(one);
    renderView();
    expect((await screen.findByTestId("si-curve-few")).textContent).toContain("second night");
    expect(screen.queryByTestId("si-curve")).toBeNull();
  });

  it("puts every number of the curve in its table, with the app versions", async () => {
    installFetch(fullOverview());
    renderView();
    const curve = await screen.findByTestId("si-curve");
    fireEvent.click(within(curve).getByRole("button", { name: "Table" }));
    const table = within(curve).getByTestId("si-curve-table");
    const cells = within(table).getAllByRole("row");
    expect(cells).toHaveLength(4); // head + three nights
    expect(table.textContent).toContain("5.6.0");
    expect(table.textContent).toContain("+2.1");
  });

  it("says what to do when the loop is not running", async () => {
    installFetch(null, 503);
    renderView();
    expect((await screen.findByTestId("si-error")).textContent).toContain("Restart Dodaios");
  });
});

describe("SelfImprovementView, before and while tasks are built", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_improvement");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("keeps the prompt in small print when it is not shorter by 5 % or more", async () => {
    const same = fullOverview();
    const p = same.domains[0].point!;
    same.domains[0].point = { ...p, now_tokens: 112, factory_tokens: 116 };
    installFetch(same);
    renderView();
    await screen.findByTestId("si-headline");
    expect(screen.queryByTestId("si-saving")).toBeNull();
    expect(screen.getByTestId("si-cost").textContent).toBe("116 → 112 tokens");
    expect(screen.getByTestId("si-range").textContent).toContain("includes zero");
  });

  it("says how many tasks exist and how many it needs while it is still building them", async () => {
    const building = emptyOverview();
    building.domains = [
      { domain: "recall", tasks: { practice: 18, select: 11, guard: 7, sealed: 0 }, tasks_total: 36, all_tasks: {}, measured: false, point: null },
    ];
    building.nights = [night(1, { made: { questions: 24, messages: 12, forgotten: 0, calls: 3, deferred: false } })];
    installFetch(building);
    renderView();
    const waiting = await screen.findByTestId("si-area-waiting");
    expect(waiting.textContent).toBe(
      "36 test tasks from your own memory and messages so far. Measuring starts when there are enough to decide on: 30 in the part it decides on, which holds 11 now.",
    );
    expect(screen.queryByTestId("si-empty")).toBeNull();
    expect(screen.queryByTestId("si-curve")).toBeNull();
    expect(screen.getAllByTestId("si-night")[0].textContent).toContain("Built 36 test tasks from your own memory and messages.");
  });

  it("lists what the nights built, stored, erased, or could not build", async () => {
    const data = fullOverview();
    data.nights = [
      night(1, { made: { questions: 80, messages: 25, forgotten: 3, calls: 8, deferred: false, past_work: 261 } }),
      night(2, { made: { questions: 0, messages: 0, forgotten: 0, calls: 0, deferred: true } }),
      night(3, { made: {} }),
    ];
    installFetch(data);
    renderView();
    const nights = await screen.findAllByTestId("si-night");
    expect(nights[0].textContent).toContain("Built 105 test tasks from your own memory and messages.");
    expect(nights[0].textContent).toContain("Erased 3 tasks about memories that are gone.");
    expect(nights[0].textContent).toContain("Stored 261 tasks from your past coding work.");
    expect(nights[1].textContent).toBe(nights[1].querySelector("time")!.textContent + "No model could be asked, so no tasks were built.");
    expect(nights[2].textContent).toContain("found nothing to measure yet");
  });

  it("shows the nights under the empty card when no model could be asked", async () => {
    const data = emptyOverview();
    data.status = { ...data.status, last_night_ms: NOW - DAY };
    data.nights = [night(1, { made: { deferred: true, questions: 0, messages: 0, forgotten: 0, calls: 0 } })];
    installFetch(data);
    renderView();
    await screen.findByTestId("si-empty");
    expect(screen.getAllByTestId("si-night")[0].textContent).toContain("No model could be asked");
  });
});

describe("SelfImprovementView, in daily use", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_improvement");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const WEEKS = [
    { start_ms: NOW - 5 * 7 * DAY, turns: 25, rated: true, score: 1 },
    { start_ms: NOW - 4 * 7 * DAY, turns: 3, rated: true, score: 0.45 },
    { start_ms: NOW - 3 * 7 * DAY, turns: 60, rated: true, score: 0.9 },
    { start_ms: NOW - 2 * 7 * DAY, turns: 6, rated: true, score: 0.68 },
    { start_ms: NOW - 1 * 7 * DAY, turns: 122, rated: false, score: null },
  ];

  it("says the overall figure, that it is not a proof of cause, and every week beside its count", async () => {
    const data = fullOverview();
    data.daily_use = { weeks: WEEKS, turns: 216, score: 0.84 };
    installFetch(data);
    renderView();
    const section = await screen.findByTestId("si-daily");
    expect(screen.getByTestId("si-daily-summary").textContent).toBe(
      "84% of your 216 requests in the last 5 weeks went through without a correction, a repeat or a stop.",
    );
    expect(screen.getByTestId("si-daily-caveat").textContent).toContain("not what caused it");
    const rows = within(section).getAllByTestId("si-daily-week");
    expect(rows).toHaveLength(5);
    expect(rows[0].textContent).toContain("122");
    expect(rows[0].textContent).toContain("no figure");
    expect(rows[3].textContent).toContain("3");
    expect(rows[3].textContent).toContain("45%");
    // It sits below the measured area and above what was changed, with no chart and no colour.
    const area = screen.getByTestId("si-area");
    const stack = screen.getByTestId("shelf-si-stack");
    expect(area.compareDocumentPosition(section) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(section.compareDocumentPosition(stack) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(section.querySelector("svg")).toBeNull();
    expect(section.innerHTML).not.toMatch(/text-success|text-destructive|text-warning/);
  });

  it("leaves the section out without a chat record or without a rated week", async () => {
    const none = fullOverview();
    none.daily_use = null;
    installFetch(none);
    renderView();
    await screen.findByTestId("si-headline");
    expect(screen.queryByTestId("si-daily")).toBeNull();
    cleanup();

    const unrated = fullOverview();
    unrated.daily_use = { weeks: [WEEKS[4]], turns: 122, score: null };
    installFetch(unrated);
    renderView();
    await screen.findByTestId("si-headline");
    expect(screen.queryByTestId("si-daily")).toBeNull();
  });
});

describe("SelfImprovementView, notes it wrote for itself", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_improvement");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const NOTE = "The calendar tool needs the date as 2026-03-14, not as 14 March.";

  function withNotes(): SelfImprovementOverview {
    const data = fullOverview();
    const note = (id: string, text: string): LearnedChange =>
      change({
        id,
        surface: "lesson",
        target: `lesson:${id}`,
        state: "live",
        author: "memory-learner",
        reason: "",
        text,
        measured: false,
        before: null,
        after: null,
        default: null,
        doc: "",
        admitted: null,
        last_check: null,
      });
    data.stack = [note("n1", NOTE), note("n2", ""), ...data.stack];
    return data;
  }

  it("shows a note's words in full, says when one is gone, and never a value or an arrow", async () => {
    installFetch(withNotes());
    renderView();
    const rows = await screen.findAllByTestId("si-change-row");
    expect(rows).toHaveLength(4);
    const [withText, gone] = rows;
    expect(withText.dataset.surface).toBe("lesson");
    expect(withText.textContent).toContain("A note it wrote for itself");
    expect(within(withText).getByTestId("si-note-text").textContent).toBe(NOTE);
    expect(within(withText).getByTestId("si-change-proof").textContent).toBe("not measured yet");
    expect(withText.textContent).toContain("Kept");
    expect(within(gone).getByTestId("si-note-gone").textContent).toBe("This note is gone from the memory.");
    for (const row of [withText, gone]) {
      expect(row.textContent).not.toMatch(/null|undefined|→|lesson:/);
      expect(within(row).getByTestId("si-undo")).toBeTruthy();
    }
    // Parameter rows keep their look.
    expect(rows[2].textContent).toContain("0 → 4");
    expect(screen.getByTestId("si-stack-kinds").textContent).toContain("notes it wrote for itself");
  });

  it("takes a note back like any change, and its sheet says it is not measured", async () => {
    const calls = installFetch(withNotes());
    renderView();
    const rows = await screen.findAllByTestId("si-change-row");
    fireEvent.click(rows[0]);
    const detail = await screen.findByTestId("si-change-detail");
    expect(within(detail).getByTestId("si-detail-note").textContent).toBe(NOTE);
    expect(within(detail).getByTestId("si-detail-unmeasured").textContent).toContain("Not measured yet");
    expect(within(detail).queryByTestId("si-detail-values")).toBeNull();
    expect(detail.textContent).not.toMatch(/null|undefined|→/);
    fireEvent.click(within(detail).getByTestId("si-detail-undo"));
    await waitFor(() => expect(screen.getAllByTestId("si-change-row")).toHaveLength(3));
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/self-improvement/changes/n1/undo")).toBe(true);
  });
});

describe("SelfImprovementView, the lead's first move", () => {
  beforeEach(async () => {
    setUiLanguage("en");
    await loadLocaleChunk("self_improvement");
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  function withLead(): SelfImprovementOverview {
    const data = fullOverview();
    data.limits = { ...data.limits, first_move_calls: 40 };
    data.domains = [
      ...data.domains,
      { domain: "first_move", tasks: { practice: 0, select: 0, guard: 0, sealed: 0 }, tasks_total: 0, all_tasks: {}, measured: false, point: null },
    ];
    data.stack = [
      change({
        id: "l1",
        target: "lead.first_line",
        state: "trial",
        author: "lines",
        reason: "on the practice tasks: +0.000 score, 9% cheaper (True -> False, best of 1 moves)",
        before: null,
        after: false,
        default: true,
        doc: "Beside every request: write one short line that takes the task on before the first tool call.",
        admitted: { ...measurement("admit", 0, -0.04, 0.04, 150, -66, "as good on 150 tasks, and 9% cheaper"), domain: "first_move" },
      }),
      ...data.stack,
    ];
    return data;
  }

  it("is an area of its own with its name, its question and where its tasks come from", async () => {
    installFetch(withLead());
    renderView();
    const areas = await screen.findAllByTestId("si-area");
    const lead = areas.find((a) => a.dataset.domain === "first_move");
    expect(lead?.textContent).toContain("First move");
    expect(lead?.textContent).toContain("reach for the right tool first");
    expect(lead?.textContent).toContain("answers the assistant got right after you corrected it");
    const limits = screen.getByTestId("si-limits").textContent ?? "";
    expect(limits).toContain("at most 40 model calls a night for both together");
    expect(limits).toContain("never more than 20 % of a window in one night");
    expect(limits).not.toContain("Measuring itself asks no model.");
  });

  it("reads a dropped line as one plain sentence in what it changed, with no values", async () => {
    installFetch(withLead());
    renderView();
    const [row] = await screen.findAllByTestId("si-change-row");
    expect(within(row).getByTestId("si-line-sentence").textContent).toBe(
      "Dropped the line beside your messages that asks for a short opening line before the first tool.",
    );
    expect(row.textContent).not.toMatch(/→|true|false|lead\.first_line/);
    expect(within(row).getByTestId("si-change-proof").textContent).toContain("as good on 150 tasks");
    expect(within(row).getByTestId("si-undo")).toBeTruthy();
    fireEvent.click(row);
    const detail = await screen.findByTestId("si-change-detail");
    expect(detail.textContent).toContain("Dropped the line beside your messages");
    expect(within(detail).getByTestId("si-detail-values").textContent).toBe("on → off");
    expect(detail.textContent).not.toMatch(/true|false/);
  });
});

describe("self-improvement words", () => {
  const t = (key: string) => key;

  it("calls a range across zero unclear, whatever the sign of the mean", () => {
    expect(certainty(0.01, 0.2)).toBe("better");
    expect(certainty(-0.2, -0.01)).toBe("worse");
    expect(certainty(-0.01, 0.2)).toBe("unclear");
    expect(certainty(0, 0.2)).toBe("unclear");
  });

  it("formats points with a sign and one decimal", () => {
    expect(fmtPoints(0.021, "en")).toBe("+2.1");
    expect(fmtPoints(-0.0004, "en")).toBe("0.0");
    expect(fmtPoints(-0.119, "en")).toBe("-11.9");
    expect(fmtPoints(0.021, "de")).toBe("+2,1");
  });

  it("never words an uncertain gain as a win", () => {
    const found: Measurement = {
      ts_ms: 0, step: "admit", verdict: "accept", split: "select", reason: "", domain: "recall",
      diff: 0.05, low: -0.01, high: 0.11, n: 84, cost_diff: 0,
    };
    expect(effectWords(t, found, "en")).toBe("self_improvement.effect.unclear");
  });
});
