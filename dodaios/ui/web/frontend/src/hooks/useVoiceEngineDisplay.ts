import { useMemo } from "react";

import { useVoiceMode } from "@/hooks/useVoiceMode";
import {
  resolveVoiceEngineDisplay,
  type VoiceEngineDisplay,
} from "@/lib/voiceEngineDisplay";

/**
 * The realtime provider + model the next call will use. Same rule as the
 * sidebar footer: the configured realtime pick, outranked by a live session.
 */
export function useVoiceEngineDisplay(): VoiceEngineDisplay {
  const voiceMode = useVoiceMode();
  return useMemo(
    () =>
      resolveVoiceEngineDisplay({
        activeProvider: voiceMode.activeProvider,
        activeProviderLabel: voiceMode.activeProviderLabel,
        activeModel: voiceMode.activeModel,
        sessionActive: voiceMode.sessionActive,
        activeSessionProvider: voiceMode.activeSessionProvider,
        activeSessionModel: voiceMode.activeSessionModel,
      }),
    [
      voiceMode.activeProvider,
      voiceMode.activeProviderLabel,
      voiceMode.activeModel,
      voiceMode.sessionActive,
      voiceMode.activeSessionProvider,
      voiceMode.activeSessionModel,
    ],
  );
}
