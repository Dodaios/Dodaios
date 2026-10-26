import { afterEach, describe, expect, it } from "vitest";

import {
  CHAT_MIN,
  DEFAULT_SHELL_PREFS,
  PANE_MAX,
  PANE_MIN,
  ROSTER_MAX,
  ROSTER_MIN,
  ROSTER_RAIL,
  readShellPrefs,
  resolveShellLayout,
  shellPrefsReducer,
  writeShellPrefs,
  type ShellPrefs,
} from "./shellLayout";

const prefs = (over: Partial<ShellPrefs> = {}): ShellPrefs => ({ ...DEFAULT_SHELL_PREFS, ...over });

afterEach(() => localStorage.clear());

describe("resolveShellLayout", () => {
  it("gives every region its preferred width when the window is wide", () => {
    const layout = resolveShellLayout(1600, prefs({ rosterWidth: 300, paneWidth: 360 }));
    expect(layout).toMatchObject({ roster: "full", rosterWidth: 300, paneOpen: true, paneWidth: 360, chatWidth: 940 });
    expect(layout.paneForced).toBe(false);
    expect(layout.rosterForced).toBe(false);
  });

  it("shrinks the pane first, so the chat keeps its minimum", () => {
    const layout = resolveShellLayout(280 + CHAT_MIN + 300, prefs({ rosterWidth: 280, paneWidth: 400 }));
    expect(layout.rosterWidth).toBe(280);
    expect(layout.paneWidth).toBe(300);
    expect(layout.chatWidth).toBe(CHAT_MIN);
  });

  it("closes the pane once it cannot shrink further, before the roster gives anything", () => {
    const layout = resolveShellLayout(280 + CHAT_MIN + PANE_MIN - 1, prefs({ rosterWidth: 280 }));
    expect(layout.paneOpen).toBe(false);
    expect(layout.paneForced).toBe(true);
    expect(layout.rosterWidth).toBe(280);
    expect(layout.chatWidth).toBeGreaterThanOrEqual(CHAT_MIN);
  });

  it("then shrinks the roster, then folds it to the rail", () => {
    const shrunk = resolveShellLayout(ROSTER_MIN + CHAT_MIN + 10, prefs({ rosterWidth: 320 }));
    expect(shrunk).toMatchObject({ roster: "full", rosterWidth: ROSTER_MIN + 10, paneOpen: false });

    const railed = resolveShellLayout(ROSTER_MIN + CHAT_MIN - 1, prefs({ rosterWidth: 320 }));
    expect(railed).toMatchObject({ roster: "rail", rosterWidth: ROSTER_RAIL, rosterForced: true, paneOpen: false });
    expect(railed.chatWidth).toBeGreaterThanOrEqual(CHAT_MIN);
  });

  it("never lets the chat drop below its minimum while something else can give way", () => {
    for (let width = ROSTER_RAIL + CHAT_MIN; width <= 1800; width += 7) {
      const layout = resolveShellLayout(width, prefs({ rosterWidth: ROSTER_MAX, paneWidth: PANE_MAX }));
      expect(layout.chatWidth, `at ${width}px`).toBeGreaterThanOrEqual(CHAT_MIN);
      expect(layout.rosterWidth + layout.paneWidth + layout.chatWidth).toBe(width);
    }
  });

  it("honours a roster the person folded and a pane the person closed", () => {
    const layout = resolveShellLayout(1600, prefs({ rosterCollapsed: true, paneOpen: false }));
    expect(layout).toMatchObject({ roster: "rail", rosterWidth: ROSTER_RAIL, rosterForced: false, paneOpen: false, paneForced: false });
  });

  it("has no pane where nothing is open", () => {
    expect(resolveShellLayout(1600, prefs(), false).paneWidth).toBe(0);
  });
});

describe("shell preferences", () => {
  it("clamps widths into their bounds", () => {
    let state = shellPrefsReducer(prefs(), { type: "resize-roster", width: 10 });
    expect(state.rosterWidth).toBe(ROSTER_MIN);
    state = shellPrefsReducer(state, { type: "resize-roster", width: 9999 });
    expect(state.rosterWidth).toBe(ROSTER_MAX);
    state = shellPrefsReducer(state, { type: "resize-pane", width: 10 });
    expect(state.paneWidth).toBe(PANE_MIN);
    state = shellPrefsReducer(state, { type: "resize-pane", width: 9999 });
    expect(state.paneWidth).toBe(PANE_MAX);
  });

  it("toggles the regions and unfolds the roster on a resize", () => {
    let state = shellPrefsReducer(prefs(), { type: "toggle-pane" });
    expect(state.paneOpen).toBe(false);
    state = shellPrefsReducer(state, { type: "toggle-roster" });
    expect(state.rosterCollapsed).toBe(true);
    state = shellPrefsReducer(state, { type: "resize-roster", width: 300 });
    expect(state.rosterCollapsed).toBe(false);
  });

  it("persists across reloads and survives bad storage", () => {
    writeShellPrefs(prefs({ rosterWidth: 333, paneWidth: 401, paneOpen: false, rosterCollapsed: true }));
    expect(readShellPrefs()).toEqual({ rosterWidth: 333, paneWidth: 401, paneOpen: false, rosterCollapsed: true });

    localStorage.setItem("society.shell.layout.v1", "{not json");
    expect(readShellPrefs()).toEqual(DEFAULT_SHELL_PREFS);

    localStorage.setItem("society.shell.layout.v1", JSON.stringify({ rosterWidth: 5000, paneWidth: "wide" }));
    expect(readShellPrefs()).toMatchObject({ rosterWidth: ROSTER_MAX, paneWidth: DEFAULT_SHELL_PREFS.paneWidth });
  });
});
