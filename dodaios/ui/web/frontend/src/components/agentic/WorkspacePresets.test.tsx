import { useState } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentStatus, LaunchPreset } from "@/lib/agenticIdeApi";
import * as api from "@/lib/agenticIdeApi";
import { WorkspacePresets, expandPreset, lineupOf } from "./WorkspacePresets";

vi.mock("@/lib/agenticIdeApi", () => ({
  fetchLaunchPresets: vi.fn(),
  saveLaunchPresets: vi.fn(),
}));

const agents: AgentStatus[] = [
  { name: "claude", display_name: "Claude Code", installed: true, version: null, install_command: null },
  { name: "codex", display_name: "Codex", installed: true, version: null, install_command: null },
  { name: "kimi", display_name: "Kimi Code", installed: true, version: null, install_command: null },
];

const team: LaunchPreset = {
  id: "team",
  name: "Team",
  agents: [{ agent: "claude", count: 2 }, { agent: "codex", count: 1 }, { agent: "kimi", count: 1 }],
};

function Harness({ start = ["claude"] }: { start?: string[] }) {
  const [sessions, setSessions] = useState(start);
  return <><WorkspacePresets agents={agents} sessions={sessions} onChange={setSessions} />
    <output data-testid="plan">{sessions.join(",")}</output></>;
}

beforeEach(() => {
  vi.mocked(api.saveLaunchPresets).mockImplementation(async (presets) => ({ presets, stored: true }));
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe("Workspace presets", () => {
  it("groups and expands lineups", () => {
    expect(lineupOf(["claude", "codex", "claude"])).toEqual([{ agent: "claude", count: 2 }, { agent: "codex", count: 1 }]);
    expect(expandPreset(team)).toEqual(["claude", "claude", "codex", "kimi"]);
  });

  it("fills the lineup from a saved preset in one click", async () => {
    vi.mocked(api.fetchLaunchPresets).mockResolvedValue({ presets: [team], stored: true });
    render(<Harness />);
    fireEvent.click(await screen.findByRole("button", { name: /Use preset Team/ }));
    expect(screen.getByTestId("plan").textContent).toBe("claude,claude,codex,kimi");
    expect(screen.getByRole("button", { name: /Use preset Team/ }).getAttribute("aria-pressed")).toBe("true");
  });

  it("offers starters on a first run without writing them", async () => {
    vi.mocked(api.fetchLaunchPresets).mockResolvedValue({ presets: [], stored: false });
    render(<Harness />);
    fireEvent.click(await screen.findByRole("button", { name: /Use preset Squad/ }));
    expect(screen.getByTestId("plan").textContent).toBe("claude,claude,codex,kimi");
    expect(api.saveLaunchPresets).not.toHaveBeenCalled();
  });

  it("saves the current lineup under a name", async () => {
    vi.mocked(api.fetchLaunchPresets).mockResolvedValue({ presets: [], stored: true });
    render(<Harness start={["codex", "claude", "codex"]} />);
    fireEvent.click(await screen.findByRole("button", { name: /Save as preset/ }));
    fireEvent.change(screen.getByRole("textbox", { name: "Preset name" }), { target: { value: "Review" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.saveLaunchPresets).toHaveBeenCalled());
    const saved = vi.mocked(api.saveLaunchPresets).mock.calls[0][0];
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ name: "Review", agents: [{ agent: "codex", count: 2 }, { agent: "claude", count: 1 }] });
    expect(await screen.findByRole("button", { name: /Use preset Review/ })).toBeTruthy();
  });

  it("deletes a preset after a confirming click", async () => {
    vi.mocked(api.fetchLaunchPresets).mockResolvedValue({ presets: [team], stored: true });
    render(<Harness />);
    fireEvent.click(await screen.findByRole("button", { name: "Delete preset Team" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(api.saveLaunchPresets).toHaveBeenCalledWith([]));
    expect(screen.queryByRole("button", { name: /Use preset Team/ })).toBeNull();
  });

  it("disables a preset whose agent is not available", async () => {
    vi.mocked(api.fetchLaunchPresets).mockResolvedValue({
      presets: [{ id: "g", name: "Grok pair", agents: [{ agent: "grok-build", count: 2 }] }],
      stored: true,
    });
    render(<Harness />);
    const card = await screen.findByRole("button", { name: /Use preset Grok pair/ });
    expect((card as HTMLButtonElement).disabled).toBe(true);
    expect(card.getAttribute("title")).toContain("grok-build");
  });
});
