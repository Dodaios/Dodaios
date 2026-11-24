import { useVoiceMode } from "@/hooks/useVoiceMode";
import { realtimeTransportIssueKey } from "@/lib/realtimeTransportIssue";
import { useT } from "@/i18n";

/**
 * What the running call is doing, at the top of the Live calls tab: the
 * provider a live session really uses, and the reason a call did not start.
 *
 * "Connecting" comes first. A subscription transport spends 15-45 s spawning
 * its app-server, verifying the account and negotiating WebRTC; reporting that
 * window as idle is what made a working call look frozen. The backend's own
 * one-liner for a blocked transport is rendered verbatim: it names the actual
 * blocker, and paraphrasing it would drop the diagnosis. Nothing is drawn
 * while no call runs and nothing went wrong.
 */
export function VoiceCallStatus() {
  const t = useT();
  const voice = useVoiceMode();
  const detail = [voice.activeSessionProvider, voice.activeSessionModel].filter(Boolean).join(" · ");
  const runtime = voice.connecting
    ? t("apikeys_view.runtime_connecting")
    : voice.transitioning
      ? t("apikeys_view.runtime_switching")
      : voice.sessionActive
        ? `${t("apikeys_view.runtime_realtime")}${detail ? ` · ${detail}` : ""}`
        : "";
  const offerBlocked = voice.requiresWebRtcOffer && voice.transportOfferReady === false;
  const offer = !offerBlocked
    ? ""
    : voice.transportIssue
      ? t(realtimeTransportIssueKey(voice.transportIssue))
      : voice.transportOfferDetail;
  const startError = voice.lastStartError;
  if (!runtime && !offer && !startError) return null;
  return (
    <div data-testid="voice-call-status" className="space-y-1 px-1 text-xs" aria-live="polite">
      {runtime && (
        <p data-testid="voice-call-runtime" className="text-muted-foreground">
          {runtime}
        </p>
      )}
      {startError && (
        <p data-testid="realtime-last-start-error" className="text-foreground">
          {t("voice_state.connect_failed")
            .replace("{0}", startError.provider || "?")
            .replace("{1}", startError.message)}
        </p>
      )}
      {offer && (
        <p data-testid="realtime-transport-offer-detail" className="text-foreground">
          {offer}
        </p>
      )}
    </div>
  );
}
