/**
 * The HUD's dialogs are real modals: focus lands inside on open, Escape
 * closes the dialog and nothing behind it, focus goes back to the opener,
 * and the launcher runs one batch at a time and stops it when it closes.
 */
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  fetchIdeState: vi.fn(async () => ({ workspaces: [{ id: "w1", name: "One" }], active_id: "w1" })),
  fetchIdeAgents: vi.fn(async () => ({ agents: [{ name: "cli-a", installed: true, kind: "cli" }] })),
  fetchWorkspacePanes: vi.fn(async () => ({ panes: [] })),
  openTerminal: vi.fn(),
  promptTerminal: vi.fn(async () => ({})),
  startTerminal: vi.fn(async () => undefined),
}));
vi.mock("@/lib/agenticIdeApi", () => api);
vi.mock("@/store/workspacePanes", () => ({ useWorkspacePanesStore: { getState: () => ({ load: async () => undefined }) } }));
// A plain stand-in for the themed picker, so a test can pick an option by its words.
vi.mock("@/components/ui/select", () => ({
  BrandedSelect: ({ options, onValueChange, ariaLabel }: {
    options: { value: string; label: string }[]; onValueChange: (value: string) => void; ariaLabel: string;
  }) => (
    <div role="group" aria-label={ariaLabel}>
      {options.map((option) => <button key={option.value} type="button" onClick={() => onValueChange(option.value)}>{option.label}</button>)}
    </div>
  ),
}));

import { LauncherPanel } from "./LauncherPanel";
import { LiftPanel } from "./LiftPanel";

const t = (key: string) => key;
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 5)); });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function LiftHost({ onRide }: { onRide: (deck: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>opener</button>
      {open && <LiftPanel current="ops" t={t} onRide={onRide} onClose={() => setOpen(false)} />}
    </div>
  );
}

describe("LiftPanel", () => {
  it("traps focus on the current deck, closes on Escape alone and hands focus back", async () => {
    const stage = vi.fn();
    window.addEventListener("keydown", stage);
    try {
      render(<LiftHost onRide={vi.fn()} />);
      const opener = screen.getByText("opener");
      opener.focus();
      fireEvent.click(opener);
      const dialog = screen.getByRole("dialog");
      expect(dialog.getAttribute("aria-labelledby")).toBeTruthy();
      expect(document.activeElement?.getAttribute("aria-current")).toBe("true");
      expect(dialog.contains(document.activeElement)).toBe(true);

      fireEvent.keyDown(document.activeElement!, { key: "Escape" });
      expect(screen.queryByRole("dialog")).toBeNull();
      // The stage's own Escape (it also clears the selection) never sees the key.
      expect(stage).not.toHaveBeenCalled();
      await settle();
      expect(document.activeElement).toBe(opener);
    } finally {
      window.removeEventListener("keydown", stage);
    }
  });
});

describe("LauncherPanel", () => {
  it("allows one batch at a time and stops it when the panel closes", async () => {
    let resolveOpen: (value: { name: string }) => void = () => undefined;
    api.openTerminal.mockImplementation(() => new Promise((r) => { resolveOpen = r; }));
    const say = vi.fn();
    const onClose = vi.fn();
    const first = render(<LauncherPanel t={t} say={say} onClose={onClose} onOpenIde={vi.fn()} />);
    await settle();
    fireEvent.click(within(screen.getByRole("group", { name: "verse.launcher.count" })).getByText("3"));
    fireEvent.click(screen.getByText("verse.launcher.start"));
    expect(api.openTerminal).toHaveBeenCalledTimes(1);

    // A second launcher (the other stage, or the panel reopened) cannot start a batch of its own.
    first.unmount();
    const second = render(<LauncherPanel t={t} say={say} onClose={vi.fn()} onOpenIde={vi.fn()} />);
    await settle();
    const start = () => screen.getByText("verse.launcher.start") as HTMLButtonElement;
    expect(start().disabled).toBe(true);

    // The pane already asked for still opens; the closed panel's batch opens no more.
    await act(async () => { resolveOpen({ name: "pane-1" }); });
    await settle();
    expect(api.openTerminal).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
    expect(say).toHaveBeenCalledWith("verse.launcher.started");
    expect(start().disabled).toBe(false);
    second.unmount();
  });
});
