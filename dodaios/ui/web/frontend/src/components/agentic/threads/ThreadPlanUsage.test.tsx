import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AccountUsage, AgentAccountsResponse } from "@/lib/agentAccountsApi";

const api = vi.hoisted(() => ({ fetchAgentAccounts: vi.fn(), fetchAgentUsage: vi.fn() }));
vi.mock("@/lib/agentAccountsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/agentAccountsApi")>()), ...api,
}));
vi.mock("@/store/tiling", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/store/tiling")>()),
  isSectionOnScreen: () => true,
}));

import { ThreadPlanUsage } from "./ThreadPlanUsage";

function account(id: string, email: string) {
  return { id, platform: "claude", label: id, config_dir: `/seats/${id}`, builtin: id === "default",
    connected: true, mode: "subscription", message: "", email, tier: null };
}

const accounts: AgentAccountsResponse = {
  platforms: [{ platform: "claude", display_name: "Claude Code", active_account: "second",
    accounts: [account("default", "one@example.com"), account("second", "two@example.com")] }],
};

function reading(id: string, session: number, weekly: number): AccountUsage {
  return { account_id: id, platform: "claude", status: "ok", source: "live", as_of: 0, message: "", plan: "Max 20x",
    windows: [
      { kind: "session", percent: session, severity: session >= 95 ? "critical" : "normal", resets_at: null, window_minutes: 300, scope_label: null, raw_label: null },
      { kind: "weekly", percent: weekly, severity: "normal", resets_at: null, window_minutes: 10080, scope_label: null, raw_label: null },
    ] };
}

beforeEach(() => {
  api.fetchAgentAccounts.mockResolvedValue(accounts);
  api.fetchAgentUsage.mockResolvedValue({ accounts: [reading("default", 10, 20), reading("second", 97, 40)], ttl_seconds: 60, generated_at: 0 });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("ThreadPlanUsage", () => {
  it("shows the active seat's limit closest to running out, and every limit on click", async () => {
    render(<ThreadPlanUsage platform="claude" className="" />);
    const chip = await screen.findByTestId("thread-plan-usage");
    expect(chip.textContent).toContain("Max 20x");
    expect(chip.textContent).toContain("5 h 97%");
    expect(chip.dataset.severity).toBe("critical");
    fireEvent.click(chip);
    const details = await screen.findByTestId("thread-plan-usage-details");
    expect(details.querySelectorAll("[data-testid=subscription-window]")).toHaveLength(2);
    expect(screen.getByText("two@example.com")).toBeTruthy();
  });

  it("draws nothing for a thread without a CLI plan", async () => {
    const { container } = render(<ThreadPlanUsage platform="" className="" />);
    await Promise.resolve();
    expect(container.innerHTML).toBe("");
    expect(api.fetchAgentUsage).not.toHaveBeenCalled();
  });

  it("draws nothing when the plan cannot be read", async () => {
    api.fetchAgentUsage.mockResolvedValue({ accounts: [{ ...reading("second", 0, 0), status: "unavailable", windows: [] }], ttl_seconds: 60, generated_at: 0 });
    render(<ThreadPlanUsage platform="claude" className="" />);
    await vi.waitFor(() => expect(api.fetchAgentUsage).toHaveBeenCalled());
    expect(screen.queryByTestId("thread-plan-usage")).toBeNull();
  });
});
