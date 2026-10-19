import { act, cleanup, render, renderHook, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetConnectBudgetForTests } from "@/lib/connectBudget";
import { DoneGateLabel } from "./PaneDoneGateBadge";
import { themeFor } from "./terminalThemes";
import { POLL_MS, resetPaneDoneGateForTests, usePaneDoneGate, type PaneDoneGate } from "./usePaneDoneGate";

function gate(extra: Partial<PaneDoneGate> = {}): PaneDoneGate {
  return {
    verdict: "WAIT", reason: "CI is running on PR #12", next: "Wait for the checks.", pr: 12,
    branch: "claude/feature", at: "2026-10-19T17:10:47+00:00", matched: "session", ...extra,
  };
}

describe("done gate label", () => {
  afterEach(cleanup);

  it("shows nothing without a verdict", () => {
    const { container } = render(<DoneGateLabel gate={null} appearance="dark" name="t1" />);
    expect(container.innerHTML).toBe("");
  });

  it.each([
    ["WAIT", "waiting", "yellow"],
    ["FIX", "fix", "red"],
    ["STUCK", "stuck", "red"],
    ["DONE", "landed", "green"],
  ] as const)("words %s quietly in its own colour, in both appearances", (verdict, label, slot) => {
    for (const appearance of ["dark", "light"] as const) {
      render(<DoneGateLabel gate={gate({ verdict })} appearance={appearance} name="t1" />);
      const badge = screen.getByTestId("pane-done-gate-t1");
      expect(badge.textContent).toBe(label);
      expect(badge.dataset.verdict).toBe(verdict);
      expect(badge.getAttribute("aria-label")).toBe(`t1: done gate ${label}`);
      const color = themeFor(appearance)[slot] as string;
      const swatch = document.createElement("span");
      swatch.style.color = color;
      expect(badge.style.color).toBe(swatch.style.color);
      // Only STUCK wears an outline.
      expect(badge.style.borderColor).toBe(verdict === "STUCK" ? swatch.style.color : "transparent");
      cleanup();
    }
  });

  it("puts the reason and the next step in the tooltip", () => {
    render(<DoneGateLabel gate={gate({ verdict: "FIX", matched: "folder" })} appearance="light" name="t2" />);
    const title = screen.getByTestId("pane-done-gate-t2").title;
    expect(title).toContain("Done gate: something needs fixing before this agent may stop");
    expect(title).toContain("CI is running on PR #12");
    expect(title).toContain("Next: Wait for the checks.");
    expect(title).toContain("Pull request #12");
    expect(title).toContain("Matched by this pane's folder or branch");
  });
});

describe("done gate poll", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetConnectBudgetForTests();
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
  });
  afterEach(() => {
    cleanup();
    resetPaneDoneGateForTests();
    resetConnectBudgetForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("shares one local read per workspace and drops quiet or unknown verdicts", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ panes: { t1: gate(), t2: null, t3: { ...gate(), verdict: "HOLD" } } }),
    });
    vi.stubGlobal("fetch", fetcher);
    const a = renderHook(() => usePaneDoneGate("w", "t1"));
    const b = renderHook(() => usePaneDoneGate("w", "t2"));
    const c = renderHook(() => usePaneDoneGate("w", "t3"));
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(String(fetcher.mock.calls[0][0])).toBe("/api/agentic-ide/git/done-gate?workspace_id=w");
    expect(a.result.current?.verdict).toBe("WAIT");
    expect(b.result.current).toBeNull();
    expect(c.result.current).toBeNull();

    fetcher.mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: gate({ verdict: "DONE" }) } }) });
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 1.5));
    expect(a.result.current?.verdict).toBe("DONE");

    // A failed read keeps the gate's last word.
    fetcher.mockRejectedValue(new Error("offline"));
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 1.5));
    expect(a.result.current?.verdict).toBe("DONE");

    a.unmount(); b.unmount(); c.unmount();
    const calls = fetcher.mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 4));
    expect(fetcher.mock.calls.length).toBe(calls);
  });

  it("asks nothing without a workspace", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const hook = renderHook(() => usePaneDoneGate(undefined, "t1"));
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS));
    expect(fetcher).not.toHaveBeenCalled();
    expect(hook.result.current).toBeNull();
  });
});
