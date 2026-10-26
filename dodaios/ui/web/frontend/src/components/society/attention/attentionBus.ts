import type { QueryClient } from "@tanstack/react-query";

import { fill, translate } from "@/i18n";
import { useEventStore } from "@/store/events";
import {
  isAgentOnScreen,
  openAgent,
  useAgentNavigation,
  type CardKind,
} from "@/views/society/agentNavigation";

import { reportAttentionFocus, type FocusReport } from "./attentionApi";
import { refreshAttention, syncAttentionCount, useAttentionStore } from "./attentionStore";
import { desktopPermission, isAgentMuted, useNotificationPrefs } from "./notificationPrefs";

/**
 * The app-wide half of "needs you": the badge, the notifications, and the
 * focus report the backend's gate needs.
 *
 * It lives at the socket (`useWebSocket` hands it every `AgentAttentionChanged`
 * envelope and every reconnect), so it works on every screen, not only in the
 * Agents section. Nothing here speaks: a change becomes a count, an in-app
 * toast while the app is in front, or a desktop notification while it is in
 * the background, when the person turned those on.
 */

/** The roster's fixed lead id; the front-page chat is the lead's chat. */
const LEAD_AGENT_ID = "jarvis";

/** How often a focused window repeats its focus report (the backend forgets after 5 min). */
const FOCUS_HEARTBEAT_MS = 120_000;
const FOCUS_DEBOUNCE_MS = 250;

/** The bus payload (dodaios/agent_chat/attention.py `AgentAttentionChanged`). */
export interface AttentionEnvelope {
  count?: number;
  transition?: string;
  agent_id?: string;
  agent_name?: string;
  session_id?: string;
  kind?: string;
  ref_id?: string;
  summary?: string;
}

const CARD_KINDS: readonly string[] = ["question", "approval", "credential", "proposal"];

function cardKind(kind: string | undefined): CardKind | undefined {
  return kind && CARD_KINDS.includes(kind) ? (kind as CardKind) : undefined;
}

export type Presentation = "none" | "muted" | "off" | "looking" | "desktop" | "toast";

/** Turn a transition into the one notice it deserves; returns which one. */
export function presentAttention(note: AttentionEnvelope): Presentation {
  const agentId = note.agent_id ?? "";
  const transition = note.transition ?? "";
  if (!agentId || (transition !== "needs_input" && transition !== "done")) return "none";
  // A detached section window keeps its badge but leaves the telling to the
  // main window, so one change is never announced twice.
  if (useEventStore.getState().solo) return "none";
  if (isAgentMuted(agentId)) return "muted";
  const prefs = useNotificationPrefs.getState();
  const done = transition === "done";
  if (done && !prefs.finished) return "off";
  const focused = typeof document !== "undefined" && document.hasFocus();
  if (focused && isAgentOnScreen(agentId)) return "looking";

  const agent = note.agent_name || translate("agent_attention.fallback_agent");
  const summary = (note.summary ?? "").trim();
  const go = () => openAgent(agentId, {
    sessionId: note.session_id || undefined,
    cardRef: note.ref_id || undefined,
    kind: cardKind(note.kind),
  });
  const title = fill(translate(done ? "agent_attention.notify_done" : "agent_attention.notify_needs"), { agent });

  if (!focused && prefs.desktop && desktopPermission() === "granted") {
    try {
      const notice = new Notification(title, {
        body: done ? translate("agent_attention.notify_done_body") : summary || translate("agent_attention.notify_needs_body"),
        tag: `dodaios-agent-${agentId}-${transition}`,
        // Finished work is news, not an alarm.
        silent: done,
      });
      notice.onclick = () => {
        window.focus();
        go();
        notice.close();
      };
      return "desktop";
    } catch {
      // A window that refuses notifications after all: the toast below.
    }
  }
  const message = summary && !done ? `${title}: ${summary}` : title;
  useEventStore.getState().pushToast(done ? "info" : "warning", message, {
    action: { label: translate("agent_attention.open"), onAction: go },
    ttlMs: done ? 4_000 : 8_000,
  });
  return "toast";
}

/** One bus envelope: refresh the badge and lists, then notify if it is news. */
export function onAgentAttention(payload: unknown, queryClient: QueryClient): void {
  const note = (payload ?? {}) as AttentionEnvelope;
  if (typeof note.count === "number") syncAttentionCount(note.count);
  // The list is re-read only once a view has asked for it; the badge needs none.
  if (useAttentionStore.getState().list) void refreshAttention();
  // The roster carries each agent's waiting reason (the warning dot).
  void queryClient.invalidateQueries({ queryKey: ["society", "roster"] });
  presentAttention(note);
}

/** On every (re)connect: read the count, and start the focus report once. */
export function seedAgentAttention(): void {
  startFocusReporter();
  void refreshAttention();
  sendFocus(true);
}

// ------------------------------------------------------------- focus report

/** What the person is looking at, as the backend's gate wants it. */
export function currentFocus(): FocusReport {
  const section = useEventStore.getState().activeSection;
  const onScreen = useAgentNavigation.getState().onScreen;
  const visible = typeof document === "undefined" || document.visibilityState !== "hidden";
  const appFocused = visible && typeof document !== "undefined" && document.hasFocus();
  let agentId = "";
  let sessionId = "";
  if (section === "agents" && onScreen) {
    agentId = onScreen.agentId;
    sessionId = onScreen.sessionId ?? "";
  } else if (section === "chats") {
    agentId = LEAD_AGENT_ID;
  }
  return { agentId, sessionId, appFocused, muted: [...useNotificationPrefs.getState().muted] };
}

let lastSent = "";
let debounce: ReturnType<typeof setTimeout> | null = null;
let reporterStarted = false;

function sendFocus(force = false): void {
  const report = currentFocus();
  const key = JSON.stringify(report);
  if (!force && key === lastSent) return;
  lastSent = key;
  void reportAttentionFocus(report).catch(() => {
    lastSent = ""; // try again with the next change
  });
}

function scheduleFocus(): void {
  if (debounce) clearTimeout(debounce);
  debounce = setTimeout(() => {
    debounce = null;
    sendFocus();
  }, FOCUS_DEBOUNCE_MS);
}

function startFocusReporter(): void {
  if (reporterStarted || typeof window === "undefined") return;
  reporterStarted = true;
  window.addEventListener("focus", scheduleFocus);
  window.addEventListener("blur", scheduleFocus);
  document.addEventListener("visibilitychange", scheduleFocus);
  useAgentNavigation.subscribe((state, previous) => {
    if (state.onScreen !== previous.onScreen) scheduleFocus();
  });
  useEventStore.subscribe((state, previous) => {
    if (state.activeSection !== previous.activeSection) scheduleFocus();
  });
  useNotificationPrefs.subscribe((state, previous) => {
    if (state.muted !== previous.muted) scheduleFocus();
  });
  window.setInterval(() => {
    if (currentFocus().appFocused) sendFocus(true);
  }, FOCUS_HEARTBEAT_MS);
}
