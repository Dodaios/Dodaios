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

function draft(permissionMode: string): ComposerDraft {
  return { permissionMode } as unknown as ComposerDraft;
}

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
});
