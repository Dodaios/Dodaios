import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { useDictation } from "@/hooks/useDictation";
import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { DictateHero } from "@/views/voice/dictation/DictateHero";
import { History } from "@/views/voice/dictation/History";
import { Notice, VoicePage } from "@/views/voice/kit";

/** How often a running dictation is asked whether it still runs. */
const ACTIVE_POLL_MS = 2000;

/**
 * The Dictation tab: how to dictate, then what was dictated.
 *
 * Top to bottom: the microphone button with the one instruction, a notice for
 * each thing that stands in the way (at most one sentence each), and the
 * history.
 */
export function DictationTab() {
  const t = useT();
  const {
    status,
    settings,
    entries,
    loading,
    error,
    start,
    stop,
    copyEntry,
    discardEntry,
    restoreEntry,
    deleteEntry,
    clearHistory,
    refetch,
    refetchStatus,
    refetchHistory,
  } = useDictation();
  const pushToast = useEventStore((s) => s.pushToast);
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const [toggling, setToggling] = useState(false);

  const active = Boolean(status?.active);

  // A dictation can end without this button: the shortcut stops it, or it
  // runs into its time limit. Keep asking while one runs, so the headline
  // does not go on saying it listens.
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void refetchStatus(), ACTIVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, refetchStatus]);

  // When one has ended, its text is in the history.
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !active) void refetchHistory();
    wasActive.current = active;
  }, [active, refetchHistory]);

  async function toggle() {
    setToggling(true);
    try {
      // "auto": the backend decides on delivery whether the text goes into
      // the app in front or into this app's own input.
      if (active) await stop();
      else await start("auto");
    } catch {
      pushToast(
        "error",
        t(active ? "voiceui.dictation.stop_failed" : "voiceui.dictation.start_failed"),
      );
    } finally {
      setToggling(false);
    }
  }

  // Three separate facts. Each is shown only when it is known: an absent
  // status says nothing about this computer, it only failed to load.
  const unavailable = !loading && status !== null && !status.available;
  const cannotType =
    !loading && status !== null && status.available && status.insertion?.can_insert === false;

  return (
    <VoicePage wide testId="dictation-tab">
      {(loading || status !== null) && (
        <DictateHero
          status={status}
          loading={loading}
          busy={toggling}
          onToggle={() => void toggle()}
        />
      )}

      {(error || unavailable || cannotType) && (
        <div className="flex flex-col gap-stack">
          {error && (
            <Notice
              tone="fault"
              testId="dictation-load-error"
              action={
                <Button type="button" variant="secondary" onClick={() => void refetch()}>
                  {t("voiceui.common.retry")}
                </Button>
              }
            >
              {t("voiceui.dictation.load_failed")}
            </Notice>
          )}
          {unavailable && (
            <Notice
              testId="dictation-unavailable"
              action={
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setActiveSection("voice-api-keys")}
                >
                  {t("nav.voice_api_keys")}
                </Button>
              }
            >
              {t("voiceui.dictation.unavailable")}
            </Notice>
          )}
          {cannotType && (
            <Notice testId="dictation-cannot-type">{t("voiceui.dictation.cannot_type")}</Notice>
          )}
        </div>
      )}

      <History
        entries={entries}
        loading={loading}
        rewriteChosen={Boolean(settings?.translate || settings?.prompt_mode)}
        copyEntry={copyEntry}
        discardEntry={discardEntry}
        restoreEntry={restoreEntry}
        deleteEntry={deleteEntry}
        clearHistory={clearHistory}
      />
    </VoicePage>
  );
}
