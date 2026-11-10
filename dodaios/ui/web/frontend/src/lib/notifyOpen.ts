import { useEventStore } from "@/store/events";

/**
 * A desktop notification was clicked (`NotificationOpened` on the app bus,
 * `dodaios/notify/notifier.py`). The window is already raised by the backend;
 * here the conversation opens and scrolls to the message the notification was
 * about. The timeline may still be mounting, so the scroll retries briefly.
 */
export interface NotificationOpenedPayload {
  kind?: string;
  session_id?: string;
  message_id?: string;
}

const RETRY_MS = 120;
const RETRIES = 25;

export function onNotificationOpened(payload: unknown): void {
  const note = (payload ?? {}) as NotificationOpenedPayload;
  const events = useEventStore.getState();
  if (events.solo) return;
  if (events.activeSection !== "chats") events.setActiveSection("chats");
  // The backend already raised the window before publishing the event.
  const messageId = (note.message_id ?? "").trim();
  if (messageId) scrollToMessage(messageId, RETRIES);
}

export function scrollToMessage(messageId: string, retries: number): void {
  if (typeof document === "undefined") return;
  const el = Array.from(document.querySelectorAll<HTMLElement>("[data-message-id]")).find(
    (node) => node.dataset.messageId === messageId,
  );
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  if (retries > 0) window.setTimeout(() => scrollToMessage(messageId, retries - 1), RETRY_MS);
}
