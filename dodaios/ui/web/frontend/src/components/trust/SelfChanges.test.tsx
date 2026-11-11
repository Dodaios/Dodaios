import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { TrustView } from "@/views/TrustView";

const BASE = {
  surface: "instructions",
  target: "me.md",
  version: 1,
  diff: "-old\n+new\n",
  author: "agent:lead",
  turn: "t1",
  reason: "the owner prefers short answers",
  core: false,
  core_reasons: [],
  gate: { status: "pass", checks: [{ name: "lead_routing", status: "pass", detail: "routing accuracy 90.0% -> 90.0%" }] },
  note: "",
  created_ms: 1_700_000_000_000,
  updated_ms: 1_700_000_000_000,
};
const ROWS = [
  { ...BASE, id: "c3", surface: "prompt", target: "persona", state: "proposed", core: true, core_reasons: ["it rewrites the persona"] },
  { ...BASE, id: "c2", state: "trial" },
  { ...BASE, id: "c1", surface: "skill", target: "tidy-desk", state: "blocked", note: "routing accuracy fell from 90.0% to 80.0%" },
];
const SUMMARY = { total: 3, waiting: 1, on_trial: 1, live: 0, reverted: 0, blocked: 1 };

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Trust: self-changes", () => {
  it("lists changes with state and reason, asks approval for core ones, and rolls back", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${String(input)}`);
        const body = init?.method === "POST" ? { ok: true, change: ROWS[1] } : { changes: ROWS, summary: SUMMARY };
        return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
      }),
    );
    await loadLocaleChunk("trust");
    render(<TrustView initialTab="changes" />);
    await waitFor(() => expect(screen.getAllByTestId("self-change")).toHaveLength(3));
    const rows = screen.getAllByTestId("self-change");
    expect(rows[0].textContent).toContain("Waiting for you");
    expect(rows[0].textContent).toContain("it rewrites the persona");
    expect(rows[2].textContent).toContain("routing accuracy fell");
    expect(screen.getByTestId("self-changes-counts").textContent).toContain("1 waiting, 1 on trial");

    fireEvent.click(screen.getAllByTestId("self-change-diff-toggle")[1]);
    expect(screen.getByTestId("self-change-detail").textContent).toContain("+new");

    fireEvent.click(screen.getByTestId("self-change-approve"));
    await waitFor(() => expect(calls).toContain("POST /api/self-change/c3/approve"));
    fireEvent.click(screen.getByTestId("self-change-rollback"));
    await waitFor(() => expect(calls).toContain("POST /api/self-change/c2/rollback"));

    // Reverting everything since a time takes a second click.
    fireEvent.click(screen.getByTestId("self-changes-since-day"));
    expect(calls.some((c) => c.includes("rollback-since"))).toBe(false);
    fireEvent.click(await screen.findByTestId("self-changes-revert-confirm"));
    await waitFor(() => expect(calls.some((c) => c === "POST /api/self-change/rollback-since")).toBe(true));
  });

  it("says so when nothing was changed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ changes: [], summary: { ...SUMMARY, total: 0, waiting: 0, on_trial: 0, blocked: 0 } }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    await loadLocaleChunk("trust");
    render(<TrustView initialTab="changes" />);
    expect(await screen.findByTestId("self-changes-empty")).toBeTruthy();
  });
});
