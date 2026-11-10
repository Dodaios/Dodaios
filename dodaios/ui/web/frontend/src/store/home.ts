import { create } from "zustand";

import { readHomeSurface, writeHomeSurface, type HomeSurface } from "@/lib/homeSurface";
import { reduceTranscript, type TranscriptLine } from "@/lib/homeTranscript";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";

/**
 * The front page's own store: which surface (voice / chat) is on screen, and
 * the live transcript the voice stage shows.
 *
 * Lives apart from the big event store because it is read by exactly two
 * places — the sidebar switch that sets it and the home view that renders
 * it. The transcript is fed from the WebSocket hook with one `ingest` call
 * per event, the same way the deck and command-activity stores are; the
 * reducer returns the same array for the (vast) majority of events, which
 * `set` turns into a no-op without waking a single subscriber.
 */
interface HomeStore {
  jarvisCardMode: "voice" | "chat";
  setJarvisCardMode: (mode: "voice" | "chat") => void;
  /**
   * The society agent whose chat holds the front page instead of Jarvis'
   * (picked from the sidebar's agent list), or null for Jarvis' own chat.
   * Starting a new chat or opening one from the history clears it.
   */
  agentChatId: string | null;
  openAgentChat: (agentId: string | null) => void;
  freshVoicePending: boolean;
  voiceSelectionPending: boolean;
  voiceSwitchStopping: boolean;
  /**
   * The archived voice chat the front page reopened from the history. Its
   * calls are recorded into it (dodaios/sessions/continuation.py). A hangup
   * clears the selection; continuing it again requires a new history click.
   */
  continuedVoiceId: string | null;
  setContinuedVoiceId: (id: string | null) => void;
  surface: HomeSurface;
  setSurface: (surface: HomeSurface) => void;
  /** What was said and answered, oldest first (lib/homeTranscript.ts). */
  transcript: TranscriptLine[];
  /**
   * The assistant's answer while it is still being spoken / produced —
   * AssistantTextDelta snapshots from the voice paths, shown as a muted
   * live line under the lane until the spoken line (SpeechSpoken) lands.
   */
  liveReply: string;
  liveSessionId: string | null;
  /**
   * A call asked for from this window that the host has not answered yet:
   * the call window opens at the click, not when the first state arrives.
   */
  callPending: boolean;
  setCallPending: (pending: boolean) => void;
  /**
   * Why the last call ended on its own (a start the provider refused, a
   * connection that broke), until the person closes the note or calls
   * again. An empty message means the reason is not known.
   */
  callProblem: { message: string } | null;
  setCallProblem: (problem: { message: string } | null) => void;
  /**
   * A change of voice path during this call, in the backend's own words
   * (`VoiceProviderRefused` with `continued_on`): the chosen provider refused
   * and the call went on through another one or the classic pipeline. Shown
   * under the call's status until the call ends.
   */
  callNotice: { message: string } | null;
  setCallNotice: (notice: { message: string } | null) => void;
  /** History row captured when this call starts; navigation cannot reassign it. */
  liveConversationId: string | null;
  ingest: (name: string, payload: unknown, tsMs: number) => void;
  /**
   * Replace the lane with a stored conversation (a reopened voice session);
   * live events append after it.
   */
  seedTranscript: (lines: TranscriptLine[]) => void;
  /** Tests and a fresh session. */
  resetTranscript: () => void;
}

/**
 * The voice stage's live answer line: grows with every AssistantTextDelta
 * of a voice path, and goes away once the authoritative spoken line has
 * replaced it or the turn is over. Same string back for every other event.
 */
export function reduceLiveReply(current: string, name: string, payload: unknown): string {
  const p = (payload ?? {}) as Record<string, unknown>;
  switch (name) {
    case "AssistantTextDelta": {
      const channel = typeof p.channel === "string" ? p.channel : "";
      if (channel === "chat") return current;
      return typeof p.text === "string" ? p.text : current;
    }
    case "SpeechSpoken":
    case "MessageSent": {
      // The final words arrived as a transcript line — the preview has
      // served. (A preamble said mid-turn leaves the growing answer alone.)
      const kind = typeof p.spoken_kind === "string" ? p.spoken_kind : "";
      const role = typeof p.role === "string" ? p.role : "assistant";
      if (name === "MessageSent" && role !== "assistant") return current;
      if (name === "SpeechSpoken" && kind && kind !== "reply" && kind !== "other") {
        return current;
      }
      return "";
    }
    case "VoiceTurnCompleted":
      return "";
    case "SystemStateChanged": {
      const next = typeof p.new_state === "string" ? p.new_state.toLowerCase() : "";
      return next === "idle" ? "" : current;
    }
    default:
      return current;
  }
}

export const useHomeStore = create<HomeStore>((set, get) => ({
  // The lead's card opens on the conversation; the call button in its
  // composer (or a wake word) shows the call while it runs.
  jarvisCardMode: "chat",
  setJarvisCardMode: (jarvisCardMode) => set({ jarvisCardMode }),
  agentChatId: null,
  openAgentChat: (agentChatId) => set({ agentChatId }),
  freshVoicePending: false,
  voiceSelectionPending: false,
  voiceSwitchStopping: false,
  continuedVoiceId: null,
  setContinuedVoiceId: (continuedVoiceId) => set({ continuedVoiceId }),
  surface: readHomeSurface(),
  setSurface: (surface) => {
    writeHomeSurface(surface);
    set({ surface });
  },
  transcript: [],
  liveReply: "",
  liveSessionId: null,
  callPending: false,
  setCallPending: (callPending) => set({ callPending }),
  callProblem: null,
  // A named reason is never replaced by an unnamed one for the same call.
  setCallProblem: (callProblem) => {
    if (callProblem && !callProblem.message && get().callProblem?.message) return;
    set({ callProblem, ...(callProblem ? { callPending: false } : {}) });
  },
  callNotice: null,
  setCallNotice: (callNotice) => set({ callNotice }),
  liveConversationId: null,
  ingest: (name, payload, tsMs) => {
    if (name === "VoiceProviderRefused") {
      // The chosen provider said no (plan, key, credit, busy). With a
      // continuation the call goes on and the window says what changed;
      // without one the call is ending and this is the reason the "failed"
      // window shows — named here, before the generic error end arrives.
      const refusal = payload as { message?: unknown; continued_on?: unknown } | null;
      const message = typeof refusal?.message === "string" ? refusal.message.trim() : "";
      if (!message) return;
      if (typeof refusal?.continued_on === "string" && refusal.continued_on) {
        set({ callNotice: { message } });
      } else {
        get().setCallProblem({ message });
      }
      return;
    }
    // Late captions, spoken replies, and tool traces belong to the completed
    // call. Keep its blank successor empty until a call or selection starts.
    if (get().freshVoicePending && name !== "VoiceSessionStarted" && name !== "VoiceSessionEnded") return;
    if (name === "VoiceTranscriptUpdated") {
      const sessionId = (payload as { session_id?: string } | null)?.session_id;
      if (get().liveSessionId && sessionId !== get().liveSessionId) return;
      // The continuous caption has a stable row of its own. Clear the legacy
      // single-line preview so it cannot appear a second time at the bottom.
      useEventStore.getState().setTranscription("", true);
      set({ liveReply: "", liveSessionId: sessionId || null });
    }
    if (name === "VoiceContentShown") {
      // A card belongs to the call it was shown in, never to another one.
      const sessionId = (payload as { session_id?: string } | null)?.session_id;
      if (sessionId && get().liveSessionId && sessionId !== get().liveSessionId) return;
    }
    if (name === "VoiceSessionEnded") {
      const sessionId = (payload as { session_id?: string } | null)?.session_id;
      if (sessionId && get().liveSessionId && sessionId !== get().liveSessionId) return;
      const reason = (payload as { hangup_reason?: string } | null)?.hangup_reason;
      // A call that ended on an error says so in the call window, even when
      // nothing named the reason.
      if (reason === "error") get().setCallProblem({ message: "" });
      set({ callPending: false, callNotice: null });
      // A provider handover continues the same call. A real hangup opens an
      // empty lane; the completed conversation remains in the history rail.
      if (reason !== "realtime_fallback" && reason !== "desktop_fallback") {
        const events = useEventStore.getState();
        if (!get().voiceSwitchStopping) {
          events.setActiveConversation("voice", null);
          events.setMessages([]);
          events.seedThinkingTraces({});
          // Close the old timeline and unbind its backend voice context now,
          // even when the front page/card is closed. This does not start or
          // stop a call, so a later wake cannot be cancelled by a reset effect.
          // The one conversation stays on screen; only a voice archive left it.
          if (!useAgentChatStore.getState().activeSessionId) useAgentChatStore.getState().newChat();
        }
        events.setTranscription("", true);
        // Remember this even while the card is closed. Returning to Jarvis
        // must not restore the last archive selection. The call is over, so
        // the lead's card goes back to the conversation.
        set({
          transcript: [], liveReply: "", jarvisCardMode: "chat",
          continuedVoiceId: get().voiceSwitchStopping ? get().continuedVoiceId : null,
          freshVoicePending: !get().voiceSwitchStopping,
          voiceSelectionPending: get().voiceSwitchStopping && get().voiceSelectionPending,
        });
        return;
      }
    }
    if (name === "VoiceSessionStarted") {
      // A call already started elsewhere must not be ended on card re-entry.
      const sessionId = (payload as { session_id?: string })?.session_id || null;
      const events = useEventStore.getState();
      const continued = get().continuedVoiceId;
      set({
        freshVoicePending: false,
        callPending: false,
        callProblem: null,
        callNotice: null,
        // The lead's card shows a running call, however it was started.
        jarvisCardMode: "voice",
        liveSessionId: sessionId,
        liveConversationId: continued && events.activeKind === "voice" && events.activeThreadId === continued
          ? continued : sessionId,
      });
      // Wake words and external call controls start the same call as the
      // composer button: the conversation stays on screen and the call window
      // shows the call (components/home/CallWindow). A stored voice surface
      // from older builds goes back to the chat.
      if (get().surface !== "chat") get().setSurface("chat");
    }
    const before = get().transcript;
    const after = reduceTranscript(before, name, payload, tsMs);
    const live = reduceLiveReply(get().liveReply, name, payload);
    if (after !== before || live !== get().liveReply) {
      set({ transcript: after, liveReply: live });
    }
  },
  seedTranscript: (lines) => set({ transcript: lines, liveReply: "", freshVoicePending: false }),
  resetTranscript: () => set({ transcript: [], liveReply: "", liveSessionId: null, liveConversationId: null }),
}));
