import { prettyProviderName } from "@/lib/prettyProviderName";

/**
 * Which realtime provider + model the voice surfaces should name right now.
 *
 * Calls always run on a realtime speech-to-speech provider. One display, one
 * rule, shared by the sidebar footer and the deck:
 *
 *   - Name the configured realtime pick and its model.
 *   - A live session outranks the configured pick, so a mid-call
 *     cross-family fallback (AP-22) is visible.
 */

export interface VoiceEngineDisplay {
  providerId: string;
  providerLabel: string;
  model: string;
}

export interface VoiceEngineDisplayInput {
  activeProvider: string | null;
  activeProviderLabel: string | null;
  activeModel: string | null;
  sessionActive: boolean;
  activeSessionProvider: string;
  activeSessionModel: string;
}

export function resolveVoiceEngineDisplay(
  input: VoiceEngineDisplayInput,
): VoiceEngineDisplay {
  const liveSession = input.sessionActive && Boolean(input.activeSessionProvider);
  const providerId = liveSession
    ? input.activeSessionProvider
    : input.activeProvider ?? "";
  const providerLabel = realtimeProviderLabel(input, liveSession, providerId);
  const model = liveSession ? input.activeSessionModel : input.activeModel ?? "";
  return {
    providerId,
    providerLabel: providerLabel || "—",
    model,
  };
}

/** Registry label when we have it; pretty-id fallback when the session crossed families. */
function realtimeProviderLabel(
  input: VoiceEngineDisplayInput,
  liveSession: boolean,
  providerId: string,
): string {
  if (liveSession) {
    if (
      input.activeSessionProvider === input.activeProvider &&
      input.activeProviderLabel?.trim()
    ) {
      return input.activeProviderLabel.trim();
    }
    return prettyProviderName(input.activeSessionProvider);
  }
  return input.activeProviderLabel?.trim() || prettyProviderName(providerId);
}
