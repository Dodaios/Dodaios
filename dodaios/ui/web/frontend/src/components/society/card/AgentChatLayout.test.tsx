import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentChatLayout, useDetailsPane } from "./AgentChatLayout";
import { CHAT_MIN, ROSTER_DEFAULT, ROSTER_RAIL } from "./shellLayout";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useLocaleChunk: () => true }));

const STORE = "society.shell.layout.v2";

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

/** The pane's own close button, as the details pane renders it. */
function PaneProbe() {
  const pane = useDetailsPane();
  return <aside aria-label="Details">details<button type="button" onClick={pane?.close}>close pane</button></aside>;
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
      header={(details) => (
        <header aria-label="Chat header">
          <button ref={details.ref} type="button" onClick={details.toggle} aria-expanded={details.open} aria-controls={details.controlsId}>
            Name pill
          </button>
        </header>
      )}
      options={<PaneProbe />}
    >
      <textarea aria-label="Draft" />
    </AgentChatLayout>,
  );
  return rosterState;
}

const pill = () => screen.getByRole("button", { name: "Name pill" });

describe("AgentChatLayout", () => {
  it("opens on a plain chat: the details pane is closed until the name pill opens it", () => {
    mount();
    const shell = screen.getByTestId("agent-shell");
    expect(shell.style.gridTemplateColumns).toBe(`${ROSTER_DEFAULT}px minmax(0, 1fr) 0px`);
    expect(screen.getByTestId("shell-details").hidden).toBe(true);
    expect(pill().getAttribute("aria-expanded")).toBe("false");
    expect(pill().getAttribute("aria-controls")).toBe(screen.getByTestId("shell-details").id);

    fireEvent.click(pill());
    expect(shell.style.gridTemplateColumns).toBe(`${ROSTER_DEFAULT}px minmax(0, 1fr) 320px`);
    expect(pill().getAttribute("aria-expanded")).toBe("true");
    expect(JSON.parse(localStorage.getItem(STORE) ?? "{}").paneOpen).toBe(true);
  });

  it("remembers an opened pane, and closes it from inside without unmounting anything", () => {
    mount();
    const draft = screen.getByLabelText("Draft") as HTMLTextAreaElement;
    fireEvent.change(draft, { target: { value: "unsent" } });
    fireEvent.click(pill());
    cleanup();

    mount();
    expect(screen.getByTestId("shell-details").hidden).toBe(false);
    const again = screen.getByLabelText("Draft") as HTMLTextAreaElement;
    fireEvent.change(again, { target: { value: "unsent" } });
    fireEvent.click(screen.getByRole("button", { name: "close pane" }));
    expect(screen.getByTestId("shell-details").hidden).toBe(true);
    expect(screen.getByLabelText("Draft")).toBe(again);
    expect(again.value).toBe("unsent");
    expect(document.activeElement).toBe(pill());
    expect(JSON.parse(localStorage.getItem(STORE) ?? "{}").paneOpen).toBe(false);
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

  it("gives way in order on a narrow window and shows the pane as a sheet", () => {
    localStorage.setItem(STORE, JSON.stringify({ rosterWidth: ROSTER_DEFAULT, rosterCollapsed: false, paneOpen: true, paneWidth: 320 }));
    frameWidth(ROSTER_DEFAULT + CHAT_MIN + 100);
    mount();
    const shell = screen.getByTestId("agent-shell");
    // The pane could not fit: it closed, the roster kept its width.
    expect(shell.style.gridTemplateColumns).toBe(`${ROSTER_DEFAULT}px minmax(0, 1fr) 0px`);
    expect(screen.getByTestId("shell-details").hidden).toBe(true);
    // Opening it now lays it over the chat instead of squeezing the chat.
    fireEvent.click(pill());
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

  it("keeps a slim bar with a text toggle when no header is given", () => {
    render(<AgentChatLayout options={<aside>details</aside>}><div>chat</div></AgentChatLayout>);
    const toggle = screen.getByRole("button", { name: "society.card.options_expand" });
    expect(toggle.textContent).toContain("society.card.options");
    fireEvent.click(toggle);
    expect(screen.getByTestId("agent-shell").style.gridTemplateColumns).toBe("minmax(0, 1fr) 320px");
  });
});
