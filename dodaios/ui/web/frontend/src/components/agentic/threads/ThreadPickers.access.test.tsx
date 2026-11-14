import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ComposerDraft, ProviderOption } from "@/store/agentChat";

import { AccessPicker } from "./ThreadPickers";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));

afterEach(cleanup);

const provider = {
  permission_modes: [
    { id: "default", label: "Ask before acting", description: "Edits and commands wait for an approval card." },
    { id: "bypassPermissions", label: "Bypass permissions", description: "Everything runs without asking." },
  ],
} as unknown as ProviderOption;

function draft(permissionMode: string, buildMode = ""): ComposerDraft {
  return { permissionMode, buildMode } as unknown as ComposerDraft;
}

const withPlan = {
  default_permission_mode: "bypassPermissions",
  permission_modes: [
    { id: "default", label: "Ask before edits", description: "Edits and commands wait for an approval card." },
    { id: "auto", label: "Auto", description: "Approves routine actions itself." },
    { id: "plan", label: "Plan", description: "Reads and plans, changes nothing." },
    { id: "bypassPermissions", label: "Bypass permissions", description: "Everything runs without asking." },
  ],
} as unknown as ProviderOption;

describe("AccessPicker", () => {
  it("draws the pick as plain words: no glyph and no warning colour, whatever the stance", () => {
    render(<AccessPicker provider={provider} draft={draft("bypassPermissions")} onPick={() => undefined} />);
    const trigger = screen.getByTestId("thread-access-picker");
    expect(trigger.textContent).toContain("Bypass permissions");
    expect(trigger.className).not.toContain("text-warning");
    // The one drawing on the trigger is its chevron.
    expect(trigger.querySelectorAll("svg")).toHaveLength(1);
  });

  it("lists each mode as a name with one line under it and no glyph of its own", () => {
    const onPick = vi.fn();
    render(<AccessPicker provider={provider} draft={draft("default")} onPick={onPick} />);
    fireEvent.click(screen.getByTestId("thread-access-picker"));
    const rows = screen.getAllByRole("option");
    expect(rows.map((row) => row.getAttribute("data-value"))).toEqual(["default", "bypassPermissions"]);
    expect(rows[1].textContent).toContain("Everything runs without asking.");
    // Only the picked row draws anything: its check mark.
    expect(rows[0].querySelectorAll("svg")).toHaveLength(1);
    expect(rows[1].querySelectorAll("svg")).toHaveLength(0);
    fireEvent.click(rows[1]);
    expect(onPick).toHaveBeenCalledWith("bypassPermissions");
  });

  it("is absent for an agent that offers no modes", () => {
    const { container } = render(
      <AccessPicker provider={{ permission_modes: [] } as unknown as ProviderOption} draft={draft("")} onPick={() => undefined} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("never lists Plan as a permission; it is the Plan Mode pick below", () => {
    render(<AccessPicker provider={withPlan} draft={draft("default")} onPick={() => undefined} onPlan={() => undefined} />);
    fireEvent.click(screen.getByTestId("thread-access-picker"));
    expect(screen.getAllByRole("option").map((row) => row.getAttribute("data-value"))).toEqual([
      "default", "auto", "bypassPermissions", "plan:off", "plan:on",
    ]);
  });

  it("shows the mode Build returns to and the plan mark while Plan is on", () => {
    render(<AccessPicker provider={withPlan} draft={draft("plan", "auto")} onPick={() => undefined} onPlan={() => undefined} />);
    const trigger = screen.getByTestId("thread-access-picker");
    expect(trigger.textContent).toContain("Auto");
    expect(screen.getByTestId("thread-plan-mark")).toBeTruthy();
  });

  it("turns Plan Mode on and off from the menu", () => {
    const onPlan = vi.fn();
    const onPick = vi.fn();
    const { rerender } = render(<AccessPicker provider={withPlan} draft={draft("default")} onPick={onPick} onPlan={onPlan} />);
    expect(screen.queryByTestId("thread-plan-mark")).toBeNull();
    fireEvent.click(screen.getByTestId("thread-access-picker"));
    const row = (value: string) => screen.getAllByRole("option").find((option) => option.getAttribute("data-value") === value)!;
    fireEvent.click(row("plan:on"));
    expect(onPlan).toHaveBeenLastCalledWith(true);
    rerender(<AccessPicker provider={withPlan} draft={draft("plan", "default")} onPick={onPick} onPlan={onPlan} />);
    if (!screen.queryAllByRole("option").length) fireEvent.click(screen.getByTestId("thread-access-picker"));
    fireEvent.click(row("plan:off"));
    expect(onPlan).toHaveBeenLastCalledWith(false);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("has no Plan Mode section for an agent without a plan mode", () => {
    render(<AccessPicker provider={provider} draft={draft("default")} onPick={() => undefined} onPlan={() => undefined} />);
    fireEvent.click(screen.getByTestId("thread-access-picker"));
    expect(screen.getAllByRole("option").map((row) => row.getAttribute("data-value"))).toEqual(["default", "bypassPermissions"]);
  });
});
