import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useLocaleChunk, useT } from "@/i18n";
import { Notice } from "@/views/voice/kit";

/** The part of `GET /api/dictation/status` the notices read. */
interface DictationState {
  /** "hold" or "toggle": what the push-to-talk keys do today. */
  mode?: string;
  insertion?: { can_insert?: boolean };
}

const MODE_EVENT = "dodaios:dictation-mode-changed";

/** Said by whoever changed the dictation mode, so the notices read it again. */
export function dictationModeChanged(): void {
  window.dispatchEvent(new Event(MODE_EVENT));
}

/**
 * Two states of the dictation keys, said above the list that edits them
 * (Settings → Keyboard shortcuts) because no other place can say them:
 *
 * 1. Push to talk has to mean hold. Saving its combination also sets the
 *    dictation mode to "hold". An install that is on "toggle" gets one notice
 *    with the action that switches it back.
 * 2. "Paste again" cannot always paste. Where the system keeps one app from
 *    typing into another, the text goes to the clipboard, and a notice says so
 *    before the person presses a key that seems to do nothing.
 *
 * Informational only: without an answer from the backend both stay away. The
 * words are the `voice` locale chunk's; nothing is drawn before it is resident.
 */
export function DictationKeyNotices() {
  const t = useT();
  const ready = useLocaleChunk("voice");
  const [state, setState] = useState<DictationState | null>(null);
  const [holdFailed, setHoldFailed] = useState(false);

  const loadState = useCallback(async () => {
    try {
      const res = await fetch("/api/dictation/status");
      if (!res.ok) return;
      setState((await res.json()) as DictationState);
    } catch {
      // Keep what was known.
    }
  }, []);

  useEffect(() => {
    void loadState();
    const onChanged = () => void loadState();
    window.addEventListener(MODE_EVENT, onChanged);
    return () => window.removeEventListener(MODE_EVENT, onChanged);
  }, [loadState]);

  const switchToHold = useCallback(async () => {
    try {
      const res = await fetch("/api/dictation/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "hold", persist: true }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setHoldFailed(false);
      setState((prev) => (prev ? { ...prev, mode: "hold" } : prev));
      await loadState();
    } catch {
      setHoldFailed(true);
    }
  }, [loadState]);

  // Only a known "toggle" raises the notice; a backend that reports no mode
  // has not said the person is on the wrong one.
  const holdIsOff = state?.mode === "toggle";
  const pasteBlocked = state?.insertion?.can_insert === false;
  if (!ready || (!holdFailed && !holdIsOff && !pasteBlocked)) return null;

  return (
    <div className="flex flex-col gap-3" data-testid="dictation-key-notices">
      {(holdFailed || holdIsOff) && (
        <Notice
          tone={holdFailed ? "fault" : "warning"}
          testId="shortcuts-hold-notice"
          action={
            <Button variant="outline" onClick={() => void switchToHold()} data-testid="shortcuts-use-hold">
              {holdFailed ? t("voiceui.common.retry") : t("voiceui.shortcuts.use_hold")}
            </Button>
          }
        >
          {holdFailed ? t("voiceui.shortcuts.hold_failed") : t("voiceui.shortcuts.hold_off")}
        </Notice>
      )}
      {pasteBlocked && <Notice testId="shortcuts-paste-notice">{t("voiceui.shortcuts.paste_blocked")}</Notice>}
    </div>
  );
}
