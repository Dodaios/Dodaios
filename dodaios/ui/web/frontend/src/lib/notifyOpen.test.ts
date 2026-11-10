import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useEventStore } from "@/store/events";

import { onNotificationOpened, scrollToMessage } from "./notifyOpen";

describe("a clicked desktop notification opens the conversation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = "";
    useEventStore.setState({ activeSection: "memory", solo: false });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("switches to the chats section and scrolls to the message once it exists", () => {
    onNotificationOpened({ kind: "reminder", session_id: "s1", message_id: "n-7" });
    expect(useEventStore.getState().activeSection).toBe("chats");
    // The timeline mounts a moment later.
    const el = document.createElement("div");
    el.dataset.messageId = "n-7";
    el.scrollIntoView = vi.fn();
    document.body.appendChild(el);
    vi.advanceTimersByTime(500);
    expect(el.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
  });

  it("gives up quietly when the message never appears", () => {
    expect(() => {
      scrollToMessage("n-404", 2);
      vi.advanceTimersByTime(2_000);
    }).not.toThrow();
  });

  it("a detached solo window leaves the opening to the main window", () => {
    useEventStore.setState({ activeSection: "memory", solo: true });
    onNotificationOpened({ message_id: "n-1" });
    expect(useEventStore.getState().activeSection).toBe("memory");
  });
});
