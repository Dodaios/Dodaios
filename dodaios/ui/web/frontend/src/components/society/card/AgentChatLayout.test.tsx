import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentChatLayout } from "./AgentChatLayout";
import { CHAT_MIN, ROSTER_DEFAULT, ROSTER_RAIL } from "./shellLayout";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useLocaleChunk: () => true }));

const STORE = "society.shell.layout.v1";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
});

/** jsdom has no layout: pretend the frame is `width` pixels wide. */
function frameWidth(width: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const w = this.dataset.testid === "agent-shell" ? width : 0;
    return { x: 0, y: 0, top: 0, left: 0, right: w, bottom: 600, width: w, height: 600, toJSON: () => ({}) } as DOMRect;
  });
}

function mount() {
  const rosterState: { collapsed?: boolean; toggle?: () => void } = {};
  render(
    <AgentChatLayout
      resetKey="a"
      roster={({ collapsed, onToggleCollapsed }) => {
        rosterState.collapsed = collapsed;
        rosterState.toggle = onToggleCollapsed;
        return <nav aria-label="Roster" data-collapsed={String(collapsed)}>roster</nav>;
      }}
      header={(toggle) => <header aria-label="Chat header">{toggle}</header>}
      options={<aside aria-label="Details">details</aside>}
    >
      <textarea aria-label="Draft" />
    </AgentChatLayout>,
  );
  return rosterState;
}

describe("AgentChatLayout", () => {
  it("lays out roster | chat | details and puts the details toggle into the header", () => {
    mount();
    const shell = screen.getByTestId("agent-shell");
    expect(shell.style.gridTemplateColumns).toBe(`${ROSTER_DEFAULT}px minmax(0, 1fr) 320px`);
    const toggle = screen.getByRole("button", { name: "society.card.options_collapse" });
    expect(screen.getByRole("banner", { name: "Chat header" }).contains(toggle)).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("folds the details pane without unmounting anything and remembers it", () => {
    mount();
    const draft = screen.getByLabelText("Draft") as HTMLTextAreaElement;
    fireEvent.change(draft, { target: { value: "unsent" } });
    fireEvent.click(screen.getByRole("button", { name: "society.card.options_collapse" }));
    expect(screen.getByTestId("shell-details").hidden).toBe(true);
    expect(screen.getByLabelText("Draft")).toBe(draft);
    expect(draft.value).toBe("unsent");
    expect(JSON.parse(localStorage.getItem(STORE) ?? "{}").paneOpen).toBe(false);

    cleanup();
    mount();
    expect(screen.getByTestId("shell-details").hidden).toBe(true);
    expect(screen.getByRole("button", { name: "society.card.options_expand" })).toBeTruthy();
  });

  it("resizes the roster from the keyboard and keeps the width across reloads", () => {
    mount();
    const handle = screen.getByRole("separator", { name: "society.shell.resize_roster" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(JSON.parse(localStorage.getItem(STORE) ?? "{}").rosterWidth).toBe(ROSTER_DEFAULT + 32);
    cleanup();
    mount();
    expect(screen.getByTestId("agent-shell").style.gridTemplateColumns.startsWith(`${ROSTER_DEFAULT + 32}px`)).toBe(true);
  });

  it("folds the roster to the rail on request", () => {
    const roster = mount();
    act(() => roster.toggle?.());
    expect(screen.getByRole("navigation", { name: "Roster" }).dataset.collapsed).toBe("true");
    expect(screen.getByTestId("agent-shell").style.gridTemplateColumns.startsWith(`${ROSTER_RAIL}px`)).toBe(true);
  });

  it("gives way in order on a narrow window and shows a closed pane as a sheet", () => {
    frameWidth(ROSTER_DEFAULT + CHAT_MIN + 100);
    mount();
    const shell = screen.getByTestId("agent-shell");
    // The pane could not fit: it closed, the roster kept its width.
    expect(shell.style.gridTemplateColumns).toBe(`${ROSTER_DEFAULT}px minmax(0, 1fr) 0px`);
    expect(screen.getByTestId("shell-details").hidden).toBe(true);
    // Opening it now lays it over the chat instead of squeezing the chat.
    fireEvent.click(screen.getByRole("button", { name: "society.card.options_expand" }));
    const pane = screen.getByTestId("shell-details");
    expect(pane.hidden).toBe(false);
    expect(pane.dataset.overlay).toBe("true");
    expect(shell.style.gridTemplateColumns).toBe(`${ROSTER_DEFAULT}px minmax(0, 1fr) 0px`);
    // The person's own choice was not overwritten by the window.
    expect(JSON.parse(localStorage.getItem(STORE) ?? "{}").paneOpen).toBe(true);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByTestId("shell-details").hidden).toBe(true);
  });

  it("folds the roster to the rail when even the pane is gone and the chat still needs room", () => {
    frameWidth(200 + CHAT_MIN);
    const roster = mount();
    expect(roster.collapsed).toBe(true);
    expect(screen.getByTestId("agent-shell").style.gridTemplateColumns).toBe(`${ROSTER_RAIL}px minmax(0, 1fr) 0px`);
  });

  it("keeps a slim bar with the toggle when no header is given", () => {
    render(<AgentChatLayout options={<aside>details</aside>}><div>chat</div></AgentChatLayout>);
    expect(screen.getByRole("button", { name: "society.card.options_collapse" }).textContent).toContain("society.card.options");
    expect(screen.getByTestId("agent-shell").style.gridTemplateColumns).toBe("minmax(0, 1fr) 320px");
  });
});
