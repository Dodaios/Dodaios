import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { loadLocaleChunk } from "@/i18n";
import { TrustView } from "@/views/TrustView";

const OVERVIEW = {
  backend: "local",
  backends: [
    { name: "local", installed: true, unlocked: true, state: "ready" },
    { name: "bitwarden", installed: true, unlocked: false, state: "locked" },
    { name: "1password", installed: false, unlocked: false, state: "not_installed" },
  ],
  handles: [
    { handle: "cred:github.com/owner", domain: "github.com", account: "owner", label: "GitHub", backend: "local", has_totp: false, agent_id: "ada", agent: "Ada" },
  ],
  rules: [{ id: "r1", agent_id: "ada", agent: "Ada", domain: "github.com", handle: "cred:github.com/owner", otp_from_mail: false, created_ms: 1 }],
  error: "",
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Trust: credentials", () => {
  it("shows handles and states, never a value, and revokes a site rule", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(input)}`);
      return new Response(JSON.stringify(OVERVIEW), { status: 200, headers: { "Content-Type": "application/json" } });
    }));
    await loadLocaleChunk("trust");
    render(<TrustView initialTab="credentials" />);
    await waitFor(() => expect(screen.getAllByTestId("credentials-handle")).toHaveLength(1));
    expect(screen.getByTestId("credentials-handle").textContent).toContain("cred:github.com/owner");
    const states = screen.getAllByTestId("credentials-backend-state").map((n) => n.textContent);
    expect(states).toEqual(["Unlocked", "Locked", "Not installed"]);
    // No master-password field: the only secret input takes the manager's session key.
    expect(screen.getAllByTestId("credentials-session-key")).toHaveLength(1);
    expect(screen.getByTestId("credentials-rule").textContent).toContain("Ada may sign in to github.com");
    fireEvent.click(screen.getByTestId("credentials-rule-revoke"));
    await waitFor(() => expect(calls).toContain("DELETE /api/trust/credentials/rules/r1"));
  });
});
