import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { TrustView } from "@/views/TrustView";

const ENTRY = {
  seq: 2, id: "a2", ts_ms: 1_700_000_000_000, day: "2026-11-11", tool: "gmail", action: "send_message",
  origin: "routine", origin_detail: "task:morning", approval: "owner_click", approval_by: "user", tier: "ask",
  effect: "outbound", outcome: "executed", error: "", duration_ms: 5, args_preview: "",
  receipt: { id: "a2", state: "backed", kind: "mail_sent", summary: "Mail sent (message m1)", evidence: {}, links: ["https://mail.google.com/mail/u/0/#all/t1"] },
};
const PAGE = {
  entries: [ENTRY, { ...ENTRY, seq: 1, id: "a1", tool: "remember", action: "", origin: "owner", origin_detail: "chat", approval: "auto_tier", receipt: { id: "a1", state: "none", kind: "none", summary: "no external evidence", evidence: {}, links: [] } }],
  next_before: null, days: ["2026-11-11"], tools: ["gmail", "remember"], chain: { ok: true, rows: 2, broken_at: null },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Trust: activity log", () => {
  it("lists every action with origin, approval, outcome and receipt, and filters by origin", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(input)}`);
      return new Response(JSON.stringify(PAGE), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    await loadLocaleChunk("trust");
    render(<TrustView initialTab="audit" />);
    await waitFor(() => expect(screen.getAllByTestId("audit-row")).toHaveLength(2));
    const first = screen.getAllByTestId("audit-row")[0].textContent ?? "";
    expect(first).toContain("Routine");
    expect(first).toContain("Your approval");
    expect(first).toContain("Mail sent (message m1)");
    expect(screen.getAllByTestId("audit-row")[1].textContent).toContain("No external evidence");
    expect(screen.getByTestId("audit-chain").textContent).toContain("2 entries");
    fireEvent.change(screen.getByLabelText("Started by"), { target: { value: "routine" } });
    await waitFor(() => expect(calls.some((c) => c.includes("origin=routine"))).toBe(true));
    // Read-only: nothing but GETs ever leaves this view.
    expect(calls.every((c) => c.startsWith("GET "))).toBe(true);
  });
});
