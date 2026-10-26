import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEventStore } from "@/store/events";
import { useAgentNavigation } from "@/views/society/agentNavigation";

import { currentFocus, onAgentAttention, presentAttention } from "./attentionBus";
import { applyTitleBadge, resetAttentionStore, useAttentionStore } from "./attentionStore";
import { resetNotificationPrefs, useNotificationPrefs } from "./notificationPrefs";

const queryClient = { invalidateQueries: vi.fn(async () => undefined) };

function focusApp(focused: boolean) {
  vi.spyOn(document, "hasFocus").mockReturnValue(focused);
}

beforeEach(() => {
  resetAttentionStore();
  resetNotificationPrefs();
  useEventStore.setState({ toasts: [], activeSection: "skills" });
  useAgentNavigation.setState({ request: null, onScreen: null });
  document.title = "Dodaios";
  queryClient.invalidateQueries.mockClear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const NEEDS = {
  count: 1,
  transition: "needs_input",
  agent_id: "scout",
  agent_name: "Scout",
  session_id: "society:scout",
  kind: "question",
  ref_id: "q1",
  summary: "Which database?",
};

describe("badge", () => {
  it("carries the count in the window title and clears it at zero", () => {
    applyTitleBadge(3);
    expect(document.title).toBe("(3) Dodaios");
    applyTitleBadge(1);
    expect(document.title).toBe("(1) Dodaios");
    applyTitleBadge(0);
    expect(document.title).toBe("Dodaios");
  });

  it("takes the count from every bus change and refreshes the roster dots", () => {
    focusApp(true);
    onAgentAttention({ count: 2 }, queryClient as never);
    expect(useAttentionStore.getState().count).toBe(2);
    expect(document.title).toBe("(2) Dodaios");
    expect(queryClient.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["society", "roster"] });
    expect(useEventStore.getState().toasts).toHaveLength(0); // no transition, no notice
  });

  it("re-reads the list only once a view has asked for it", () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ items: [], count: 0 })));
    vi.stubGlobal("fetch", fetchMock);
    onAgentAttention({ count: 0 }, queryClient as never);
    expect(fetchMock).not.toHaveBeenCalled();
    useAttentionStore.setState({ list: { items: [], count: 0 } });
    onAgentAttention({ count: 0 }, queryClient as never);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("presentAttention", () => {
  it("is quiet for a muted agent and for finished work when that is off", () => {
    focusApp(true);
    useNotificationPrefs.setState({ muted: ["scout"] });
    expect(presentAttention(NEEDS)).toBe("muted");
    useNotificationPrefs.setState({ muted: [], finished: false });
    expect(presentAttention({ ...NEEDS, transition: "done" })).toBe("off");
    expect(presentAttention({ ...NEEDS, transition: "" })).toBe("none");
  });

  it("stays silent while the person looks at that agent", () => {
    focusApp(true);
    useEventStore.setState({ activeSection: "agents" });
    useAgentNavigation.setState({ onScreen: { agentId: "scout" } });
    expect(presentAttention(NEEDS)).toBe("looking");
    expect(useEventStore.getState().toasts).toHaveLength(0);
  });

  it("shows an in-app toast whose button opens the agent at the card", () => {
    focusApp(true);
    expect(presentAttention(NEEDS)).toBe("toast");
    const [toast] = useEventStore.getState().toasts;
    expect(toast.kind).toBe("warning");
    expect(toast.message).toContain("Scout");
    expect(toast.message).toContain("Which database?");
    void toast.action?.onAction();
    expect(useAgentNavigation.getState().request).toMatchObject({ agentId: "scout", cardRef: "q1", kind: "question" });
    expect(useEventStore.getState().activeSection).toBe("agents");
  });

  it("uses a desktop notification in the background, silent for finished work", () => {
    focusApp(false);
    const shown: Array<{ title: string; options: NotificationOptions }> = [];
    class FakeNotification {
      static permission = "granted";
      onclick: (() => void) | null = null;
      constructor(title: string, options: NotificationOptions) {
        shown.push({ title, options });
      }
      close() {}
    }
    vi.stubGlobal("Notification", FakeNotification);
    useNotificationPrefs.setState({ desktop: true });
    expect(presentAttention({ ...NEEDS, transition: "done" })).toBe("desktop");
    expect(shown[0].options.silent).toBe(true);
    expect(presentAttention(NEEDS)).toBe("desktop");
    expect(shown[1].options.silent).toBe(false);
    expect(shown[1].options.body).toBe("Which database?");
  });

  it("leaves the telling to the main window in a detached one", () => {
    focusApp(true);
    useEventStore.setState({ solo: true });
    try {
      expect(presentAttention(NEEDS)).toBe("none");
    } finally {
      useEventStore.setState({ solo: false });
    }
  });

  it("falls back to a toast in the background when desktop notices are off", () => {
    focusApp(false);
    expect(presentAttention(NEEDS)).toBe("toast");
  });
});

describe("focus report", () => {
  it("names the agent on screen, and the lead on the front-page chat", () => {
    focusApp(true);
    useNotificationPrefs.setState({ muted: ["quiet"] });
    useEventStore.setState({ activeSection: "agents" });
    useAgentNavigation.setState({ onScreen: { agentId: "scout" } });
    expect(currentFocus()).toEqual({ agentId: "scout", sessionId: "", appFocused: true, muted: ["quiet"] });
    useEventStore.setState({ activeSection: "chats" });
    expect(currentFocus().agentId).toBe("jarvis");
    useEventStore.setState({ activeSection: "skills" });
    expect(currentFocus().agentId).toBe("");
  });
});

describe("list reads", () => {
  it("reads once more when a change arrives during a read, so it is never lost", async () => {
    const { refreshAttention } = await import("./attentionStore");
    const bodies = [
      { items: [], count: 0 },
      { items: [], count: 1 },
    ];
    let release: (() => void) | null = null;
    const fetchMock = vi.fn(async () => {
      const body = bodies.shift() ?? { items: [], count: 1 };
      if (fetchMock.mock.calls.length === 1) await new Promise<void>((resolve) => { release = resolve; });
      return new Response(JSON.stringify(body), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const first = refreshAttention();
    void refreshAttention(); // a change lands while the first read is out
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(release).not.toBeNull());
    release!();
    await first;
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    await vi.waitFor(() => expect(useAttentionStore.getState().count).toBe(1));
  });
});
