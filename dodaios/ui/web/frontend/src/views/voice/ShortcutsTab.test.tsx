import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { KeybindsConfig } from "@/hooks/useHotkey";
import { loadLocaleChunk, useI18nStore } from "@/i18n";
import { ShortcutsTab } from "@/views/voice/ShortcutsTab";

const hook = vi.hoisted(() => ({
  state: {
    config: null as unknown,
    loading: false,
    error: null as string | null,
    refetch: vi.fn(),
    saveKeybind: vi.fn(),
  },
}));

// Only the data hook is replaced; the check against other actions and the key
// handling are the real ones.
vi.mock("@/hooks/useHotkey", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useHotkey")>()),
  useKeybinds: () => hook.state,
}));

/** What the fake backend answers; a test changes it before rendering. */
const backend = {
  status: { mode: "hold", insertion: { can_insert: true } } as unknown,
  statusOk: true,
  settingsOk: true,
};

const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = String(input);
  if (url === "/api/dictation/status") {
    return { ok: backend.statusOk, status: backend.statusOk ? 200 : 500, json: async () => backend.status };
  }
  if (url === "/api/dictation/settings" && init?.method === "PUT") {
    if (backend.settingsOk) backend.status = { ...(backend.status as object), mode: "hold" };
    return { ok: backend.settingsOk, status: backend.settingsOk ? 200 : 500, json: async () => ({}) };
  }
  // The recorder's question about held modifier keys: this host cannot tell.
  return { ok: true, status: 200, json: async () => ({ available: false }) };
});

function config(keybinds: KeybindsConfig["keybinds"]): KeybindsConfig {
  return { keybinds, defaults: {}, suggestions: [], restart_required: false };
}

function settingsCalls() {
  return fetchMock.mock.calls.filter(([url]) => String(url) === "/api/dictation/settings");
}

function keys(action: string): HTMLButtonElement {
  return screen.getByTestId(`shortcut-keys-${action}`) as HTMLButtonElement;
}

function keycaps(action: string): string[] {
  return [...keys(action).querySelectorAll("kbd")].map((cap) => cap.textContent ?? "");
}

/** Press the given keys together, then let go of all of them. */
function chord(...codes: string[]) {
  const shift = codes.some((code) => code.startsWith("Shift"));
  for (const code of codes) fireEvent.keyDown(window, { code, key: code, shiftKey: shift });
  const down = [...codes];
  while (down.length > 0) {
    const code = down.pop() as string;
    fireEvent.keyUp(window, {
      code,
      key: code,
      shiftKey: down.some((held) => held.startsWith("Shift")),
    });
  }
}

beforeAll(async () => {
  useI18nStore.setState({ ui: "en" });
  await loadLocaleChunk("voice");
});

beforeEach(() => {
  backend.status = { mode: "hold", insertion: { can_insert: true } };
  backend.statusOk = true;
  backend.settingsOk = true;
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
  hook.state.config = config({
    dictate: "f9",
    dictate_toggle: "f10",
    paste_last: "shift+f11",
    call: "f3+f4",
  });
  hook.state.loading = false;
  hook.state.error = null;
  hook.state.refetch = vi.fn().mockResolvedValue(undefined);
  hook.state.saveKeybind = vi.fn(async (action: string, hotkey: string) => ({
    ok: true,
    action,
    hotkey,
    persisted: true,
    restart_required: false,
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Render and wait until the dictation state has been read. */
async function renderTab() {
  const view = render(<ShortcutsTab />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/dictation/status"));
  await waitFor(() => undefined);
  return view;
}

describe("ShortcutsTab states", () => {
  it("shows a loading group while the shortcuts load", async () => {
    hook.state.config = null;
    hook.state.loading = true;
    await renderTab();
    expect(screen.getByTestId("shortcuts-loading")).toBeTruthy();
    expect(screen.queryByTestId("shortcuts")).toBeNull();
  });

  it("says in one sentence that loading failed and loads again on retry", async () => {
    hook.state.config = null;
    hook.state.error = "HTTP 500";
    await renderTab();
    expect(screen.getByTestId("shortcuts-load-failed").textContent).toContain(
      "Your shortcuts could not be loaded.",
    );
    expect(screen.queryByText(/HTTP 500/)).toBeNull();
    expect(screen.queryByTestId("shortcuts")).toBeNull();
    fireEvent.click(screen.getByTestId("shortcuts-retry"));
    expect(hook.state.refetch).toHaveBeenCalledTimes(1);
  });

  it("shows three rows with their combinations as keys", async () => {
    const { container } = await renderTab();
    expect(screen.getByTestId("shortcut-row-dictate").textContent).toContain("Push to talk");
    expect(screen.getByTestId("shortcut-row-dictate_toggle").textContent).toContain("Hands-free");
    expect(screen.getByTestId("shortcut-row-paste_last").textContent).toContain("Paste again");
    expect(keycaps("dictate")).toEqual(["F9"]);
    expect(keycaps("dictate_toggle")).toEqual(["F10"]);
    expect(keycaps("paste_last")).toEqual(["Shift", "F11"]);
    expect(container.querySelectorAll('[data-testid^="shortcut-row-"]').length).toBe(3);
    expect(container.innerHTML).not.toContain("voiceui.");
    // No notice without a reason for one.
    expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull();
    expect(screen.queryByTestId("shortcuts-paste-notice")).toBeNull();
  });

  it("shows a word in place of keys for a shortcut that has none", async () => {
    hook.state.config = config({ dictate: "f9", dictate_toggle: "" });
    await renderTab();
    expect(keycaps("dictate_toggle")).toEqual([]);
    expect(keys("dictate_toggle").textContent).toBe("None");
    // An action the backend does not report at all reads the same.
    expect(keys("paste_last").textContent).toBe("None");
  });
});

describe("ShortcutsTab recording", () => {
  it("records on click and saves the moment the keys are let go", async () => {
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    expect(keys("dictate_toggle").textContent).toBe("Press keys");
    expect(keys("dictate_toggle").getAttribute("data-keybind-recording")).toBe("true");

    fireEvent.keyDown(window, { code: "ShiftLeft", key: "Shift", shiftKey: true });
    fireEvent.keyDown(window, { code: "F7", key: "F7", shiftKey: true });
    // The chord shows while it is held, and nothing is saved yet.
    expect(keycaps("dictate_toggle")).toEqual(["Shift", "F7"]);
    expect(hook.state.saveKeybind).not.toHaveBeenCalled();

    fireEvent.keyUp(window, { code: "F7", key: "F7", shiftKey: true });
    fireEvent.keyUp(window, { code: "ShiftLeft", key: "Shift", shiftKey: false });
    expect(hook.state.saveKeybind).toHaveBeenCalledWith("dictate_toggle", "shift+f7");
    await waitFor(() => expect(keycaps("dictate_toggle")).toEqual(["Shift", "F7"]));
    expect(keys("dictate_toggle").getAttribute("data-keybind-recording")).toBeNull();
    expect(screen.queryByTestId("shortcut-fault-dictate_toggle")).toBeNull();
  });

  it("leaves the shortcut as it was on Escape", async () => {
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    fireEvent.keyDown(window, { code: "F7", key: "F7" });
    fireEvent.keyDown(window, { code: "Escape", key: "Escape" });
    expect(hook.state.saveKeybind).not.toHaveBeenCalled();
    expect(keycaps("dictate_toggle")).toEqual(["F10"]);
    expect(keys("dictate_toggle").getAttribute("data-keybind-recording")).toBeNull();
  });

  it("leaves the shortcut as it was on a second click", async () => {
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    fireEvent.click(keys("dictate_toggle"));
    expect(keycaps("dictate_toggle")).toEqual(["F10"]);
    chord("F7");
    expect(hook.state.saveKeybind).not.toHaveBeenCalled();
  });

  it("does not save the combination the shortcut already has", async () => {
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    chord("F10");
    expect(hook.state.saveKeybind).not.toHaveBeenCalled();
    expect(screen.queryByTestId("shortcut-fault-dictate_toggle")).toBeNull();
  });

  it("records in one row at a time", async () => {
    await renderTab();
    fireEvent.click(keys("dictate"));
    fireEvent.click(keys("paste_last"));
    expect(keys("dictate").getAttribute("data-keybind-recording")).toBeNull();
    expect(keys("paste_last").getAttribute("data-keybind-recording")).toBe("true");
    chord("F7");
    expect(hook.state.saveKeybind).toHaveBeenCalledTimes(1);
    expect(hook.state.saveKeybind).toHaveBeenCalledWith("paste_last", "f7");
  });

  it("says at the row which shortcut already uses a combination, and does not save it", async () => {
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    chord("ShiftLeft", "F11");
    expect(hook.state.saveKeybind).not.toHaveBeenCalled();
    expect(screen.getByTestId("shortcut-fault-dictate_toggle").textContent).toBe(
      "This combination is already in use for “Paste again”.",
    );
    expect(keycaps("dictate_toggle")).toEqual(["F10"]);
    // The other rows say nothing.
    expect(screen.queryByTestId("shortcut-fault-paste_last")).toBeNull();
  });

  it("names a shortcut from elsewhere in the app by a plain name", async () => {
    await renderTab();
    fireEvent.click(keys("dictate"));
    chord("F3", "F4");
    expect(hook.state.saveKeybind).not.toHaveBeenCalled();
    expect(screen.getByTestId("shortcut-fault-dictate").textContent).toBe(
      "This combination is already in use for “Call”.",
    );
  });

  it("does not name an action it has no name for", async () => {
    hook.state.config = config({ dictate: "f9", future_action: "f7" } as KeybindsConfig["keybinds"]);
    await renderTab();
    fireEvent.click(keys("dictate"));
    chord("F7");
    expect(screen.getByTestId("shortcut-fault-dictate").textContent).toBe(
      "This combination is already in use.",
    );
  });

  it("says in one sentence that a combination was not saved", async () => {
    hook.state.saveKeybind = vi.fn().mockRejectedValue(new Error("unsafe combo: internal reason"));
    await renderTab();
    fireEvent.click(keys("paste_last"));
    chord("F7");
    const fault = await screen.findByTestId("shortcut-fault-paste_last");
    expect(fault.textContent).toBe("This shortcut could not be saved.");
    expect(screen.queryByText(/internal reason/)).toBeNull();
    expect(keycaps("paste_last")).toEqual(["Shift", "F11"]);
    expect(keys("paste_last").disabled).toBe(false);
  });

  it("takes the sentence away when the row records again", async () => {
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    chord("F9");
    expect(screen.getByTestId("shortcut-fault-dictate_toggle")).toBeTruthy();
    fireEvent.click(keys("dictate_toggle"));
    expect(screen.queryByTestId("shortcut-fault-dictate_toggle")).toBeNull();
  });

  it("removes a shortcut from the recording state", async () => {
    await renderTab();
    expect(screen.queryByTestId("shortcut-remove-paste_last")).toBeNull();
    fireEvent.click(keys("paste_last"));
    fireEvent.click(screen.getByTestId("shortcut-remove-paste_last"));
    expect(hook.state.saveKeybind).toHaveBeenCalledWith("paste_last", "");
    await waitFor(() => expect(keys("paste_last").textContent).toBe("None"));
    expect(keys("paste_last").getAttribute("data-keybind-recording")).toBeNull();
  });

  it("offers no removal for a shortcut that has no keys", async () => {
    hook.state.config = config({ dictate: "f9", dictate_toggle: "" });
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    expect(screen.queryByTestId("shortcut-remove-dictate_toggle")).toBeNull();
  });
});

describe("ShortcutsTab hold mode", () => {
  it("sets hold mode after a new push-to-talk combination is saved", async () => {
    await renderTab();
    fireEvent.click(keys("dictate"));
    chord("F7");
    await waitFor(() => expect(settingsCalls().length).toBe(1));
    const [, init] = settingsCalls()[0];
    expect(init?.method).toBe("PUT");
    expect(JSON.parse(String(init?.body))).toEqual({ mode: "hold", persist: true });
  });

  it("does not touch the mode for the other two shortcuts", async () => {
    await renderTab();
    fireEvent.click(keys("dictate_toggle"));
    chord("F7");
    await waitFor(() => expect(keycaps("dictate_toggle")).toEqual(["F7"]));
    fireEvent.click(keys("paste_last"));
    chord("F8");
    await waitFor(() => expect(keycaps("paste_last")).toEqual(["F8"]));
    expect(settingsCalls().length).toBe(0);
  });

  it("does not set hold mode when the combination was refused", async () => {
    hook.state.saveKeybind = vi.fn().mockRejectedValue(new Error("no"));
    await renderTab();
    fireEvent.click(keys("dictate"));
    chord("F7");
    await screen.findByTestId("shortcut-fault-dictate");
    expect(settingsCalls().length).toBe(0);
  });

  it("says when push to talk is not on hold, and one action switches it back", async () => {
    backend.status = { mode: "toggle", insertion: { can_insert: true } };
    await renderTab();
    const notice = await screen.findByTestId("shortcuts-hold-notice");
    expect(notice.textContent).toContain(
      "Push to talk now starts with one press and stops with the next.",
    );
    expect(screen.getByTestId("shortcuts-use-hold").textContent).toBe("Switch to hold");

    fireEvent.click(screen.getByTestId("shortcuts-use-hold"));
    await waitFor(() => expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull());
    expect(JSON.parse(String(settingsCalls()[0][1]?.body))).toEqual({ mode: "hold", persist: true });
  });

  it("says nothing about the mode when the backend reports none", async () => {
    backend.status = { insertion: { can_insert: true } };
    await renderTab();
    expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull();
  });

  it("says in one sentence that hold could not be turned on, with a retry", async () => {
    backend.status = { mode: "toggle" };
    backend.settingsOk = false;
    await renderTab();
    fireEvent.click(await screen.findByTestId("shortcuts-use-hold"));
    await waitFor(() =>
      expect(screen.getByTestId("shortcuts-hold-notice").textContent).toContain(
        "Hold could not be turned on.",
      ),
    );
    expect(screen.getByTestId("shortcuts-hold-notice").getAttribute("role")).toBe("alert");

    backend.settingsOk = true;
    fireEvent.click(screen.getByTestId("shortcuts-use-hold"));
    await waitFor(() => expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull());
    expect(settingsCalls().length).toBe(2);
  });
});

describe("ShortcutsTab paste again", () => {
  it("says that paste again copies when text cannot be typed into other apps", async () => {
    backend.status = { mode: "hold", insertion: { can_insert: false } };
    await renderTab();
    const notice = await screen.findByTestId("shortcuts-paste-notice");
    expect(notice.textContent).toContain(
      "Paste again copies the text to the clipboard because typing into other apps is blocked.",
    );
    // The shortcut itself still works and can still be changed.
    expect(keys("paste_last").disabled).toBe(false);
  });

  it("says nothing when the dictation state cannot be read", async () => {
    backend.status = { mode: "toggle", insertion: { can_insert: false } };
    backend.statusOk = false;
    await renderTab();
    expect(screen.queryByTestId("shortcuts-paste-notice")).toBeNull();
    expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull();
    expect(keycaps("dictate")).toEqual(["F9"]);
  });
});
