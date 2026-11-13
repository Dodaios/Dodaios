import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { loadLocaleChunk, useI18nStore } from "@/i18n";
import { DictationKeyNotices, dictationModeChanged } from "@/views/voice/shortcuts/DictationKeyNotices";

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
  return { ok: true, status: 200, json: async () => ({}) };
});

function statusReads() {
  return fetchMock.mock.calls.filter(([url]) => String(url) === "/api/dictation/status").length;
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
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

/** Render and wait until the dictation state has been read. */
async function renderNotices() {
  const view = render(<DictationKeyNotices />);
  await waitFor(() => expect(statusReads()).toBeGreaterThan(0));
  await waitFor(() => undefined);
  return view;
}

describe("DictationKeyNotices", () => {
  it("draws nothing while push to talk means hold and pasting works", async () => {
    await renderNotices();
    expect(screen.queryByTestId("dictation-key-notices")).toBeNull();
  });

  it("stays away when the backend does not answer", async () => {
    backend.statusOk = false;
    await renderNotices();
    expect(screen.queryByTestId("dictation-key-notices")).toBeNull();
  });

  it("says that push to talk is on toggle and switches it back to hold", async () => {
    backend.status = { mode: "toggle", insertion: { can_insert: true } };
    await renderNotices();

    const notice = await screen.findByTestId("shortcuts-hold-notice");
    expect(notice.textContent).toContain("Push to talk now starts with one press");
    fireEvent.click(screen.getByTestId("shortcuts-use-hold"));

    await waitFor(() => expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull());
    const put = fetchMock.mock.calls.find(([url, init]) => String(url) === "/api/dictation/settings" && init?.method === "PUT");
    expect(JSON.parse(String(put?.[1]?.body))).toEqual({ mode: "hold", persist: true });
  });

  it("keeps the notice as a fault with a retry when hold cannot be turned on", async () => {
    backend.status = { mode: "toggle", insertion: { can_insert: true } };
    backend.settingsOk = false;
    await renderNotices();

    fireEvent.click(await screen.findByTestId("shortcuts-use-hold"));

    await waitFor(() => expect(screen.getByTestId("shortcuts-hold-notice").getAttribute("role")).toBe("alert"));
    expect(screen.getByTestId("shortcuts-hold-notice").textContent).toContain("Hold could not be turned on.");
  });

  it("says when Paste again can only copy to the clipboard", async () => {
    backend.status = { mode: "hold", insertion: { can_insert: false } };
    await renderNotices();

    expect((await screen.findByTestId("shortcuts-paste-notice")).textContent).toContain("clipboard");
    expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull();
  });

  it("reads the mode again when a saved key changed it", async () => {
    backend.status = { mode: "toggle", insertion: { can_insert: true } };
    await renderNotices();
    await screen.findByTestId("shortcuts-hold-notice");

    // Saving the push-to-talk key on the page pins hold mode, then says so.
    backend.status = { mode: "hold", insertion: { can_insert: true } };
    dictationModeChanged();

    await waitFor(() => expect(screen.queryByTestId("shortcuts-hold-notice")).toBeNull());
  });
});
