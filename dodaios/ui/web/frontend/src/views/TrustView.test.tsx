import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { TrustView } from "@/views/TrustView";
import { useEventStore } from "@/store/events";

const RULES = {
  rules: [
    { id: "r1", tool: "Bash", kind: "command", target: "npm test", label: "npm test", app: "", source: "card", created_ms: 1 },
    { id: "r2", tool: "Edit", kind: "folder", target: "C:\\p\\src", label: "src", app: "", source: "card", created_ms: 2 },
  ],
  agent_rules: [{ agent_id: "ada", agent: "Ada", pattern: "plugin:gmail:send", app: "gmail", verb: "send", label: "Always allow send with gmail" }],
  hard_limits: ["money", "credentials", "permanent_delete", "new_recipient"],
};

const PRIVACY = {
  accounts: [{ id: "gmail", label: "Gmail", category: "mail", status: "connected" }],
  memory: { available: true, count: 12, learning_paused: false, paused_until: null },
  providers: [
    { role: "brain", provider: "gemini", label: "Gemini", local: false },
    { role: "stt", provider: "faster-whisper", label: "Local Whisper", local: true },
  ],
  cloud: [{ role: "brain", provider: "gemini", label: "Gemini", local: false }],
  channels: ["telegram"],
  screen_context: true,
  known_recipients: 3,
};

function stubApi(calls: string[]) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url.endsWith("/api/trust/rules")) return json(RULES);
    if (url.endsWith("/api/trust/recipients")) return json({ recipients: [{ recipient: "ada@example.com", first_ms: 1 }] });
    if (url.endsWith("/api/trust/privacy")) return json(PRIVACY);
    if (url.startsWith("/api/trust/rules/")) return json({ ok: true, rule: RULES.rules[0] });
    if (url.startsWith("/api/trust/agent-rules/")) return json({ ok: true });
    if (url.endsWith("/api/memory/vault/pause")) return json({ paused: true, until: "forever" });
    if (url.endsWith("/api/screen-context/settings")) return json({ enabled: false });
    return new Response("{}", { status: 404 });
  }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useEventStore.setState({ toasts: [] });
});

describe("Settings → Trust and privacy", () => {
  it("lists the standing rules as sentences with Revoke, the agents' rules, the hard limits and the recipients", async () => {
    const calls: string[] = [];
    stubApi(calls);
    await loadLocaleChunk("trust");
    render(<TrustView />);
    await waitFor(() => expect(screen.getByTestId("trust-rules")).toBeTruthy());
    const rules = screen.getAllByTestId("trust-rule").map((li) => li.textContent);
    expect(rules[0]).toContain("The command “npm test”");
    expect(rules[1]).toContain("Edit inside src");
    expect(screen.getByTestId("trust-agent-rule").textContent).toContain("Ada: Always allow send with gmail");
    expect(screen.getByTestId("trust-hard-limits").textContent).toContain("Deleting for good.");
    expect(screen.getByTestId("trust-recipients").textContent).toContain("ada@example.com");

    fireEvent.click(screen.getAllByTestId("trust-rule-revoke")[0]);
    await waitFor(() => expect(calls).toContain("DELETE /api/trust/rules/r1"));
    await waitFor(() => expect(useEventStore.getState().toasts.some((t) => t.message === "Revoked.")).toBe(true));
    fireEvent.click(screen.getByTestId("trust-agent-rule-revoke"));
    await waitFor(() => expect(calls.some((c) => c.startsWith("DELETE /api/trust/agent-rules/ada?pattern=plugin%3Agmail%3Asend"))).toBe(true));
  });

  it("shows what it knows and where it goes, with the learning and screen switches", async () => {
    const calls: string[] = [];
    stubApi(calls);
    await loadLocaleChunk("trust");
    render(<TrustView initialTab="privacy" />);
    await waitFor(() => expect(screen.getByTestId("privacy-overview")).toBeTruthy());
    expect(screen.getByTestId("privacy-accounts").textContent).toContain("Gmail");
    expect(screen.getByTestId("privacy-learned").textContent).toContain("12 memories");
    expect(screen.getByTestId("privacy-provider-brain").textContent).toContain("Cloud");
    expect(screen.getByTestId("privacy-provider-stt").textContent).toContain("On this computer");
    expect(screen.getByTestId("privacy-channels").textContent).toContain("telegram");
    expect(screen.getByTestId("privacy-overview").textContent).toContain("3 recipients written to from here");

    fireEvent.click(screen.getByRole("switch", { name: "Learn from conversations" }));
    await waitFor(() => expect(calls).toContain("PUT /api/memory/vault/pause"));
    fireEvent.click(screen.getByRole("switch", { name: "May look at the screen when you ask" }));
    await waitFor(() => expect(calls).toContain("PUT /api/screen-context/settings"));
  });

  it("switches between the two tabs", async () => {
    stubApi([]);
    await loadLocaleChunk("trust");
    render(<TrustView />);
    await waitFor(() => expect(screen.getByTestId("trust-rules")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "What it knows" }));
    await waitFor(() => expect(screen.getByTestId("privacy-overview")).toBeTruthy());
  });
});
