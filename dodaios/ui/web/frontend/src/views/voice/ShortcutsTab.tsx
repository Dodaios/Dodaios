import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useKeybinds, type KeybindAction } from "@/hooks/useHotkey";
import { useT } from "@/i18n";
import { Group, LoadingGroup, Notice, VoicePage } from "@/views/voice/kit";
import { ShortcutRow } from "@/views/voice/shortcuts/ShortcutRow";

/** The part of `GET /api/dictation/status` this tab reads. */
interface DictationState {
  /** "hold" or "toggle": what the push-to-talk keys do today. */
  mode?: string;
  insertion?: { can_insert?: boolean };
}

const ROWS: readonly { action: KeybindAction; labelKey: string }[] = [
  { action: "dictate", labelKey: "voiceui.shortcuts.push_to_talk" },
  { action: "dictate_toggle", labelKey: "voiceui.shortcuts.hands_free" },
  { action: "paste_last", labelKey: "voiceui.shortcuts.paste_again" },
];

/** Names for the actions that have their row elsewhere in the app. */
const OTHER_ACTION_KEYS: Record<string, string> = {
  call: "voiceui.shortcuts.actions.call",
  hangup: "voiceui.shortcuts.actions.hangup",
  pet_toggle: "voiceui.shortcuts.actions.pet_toggle",
};

/**
 * The Shortcuts tab: the three key combinations of dictation.
 *
 * Two states are said here because no other place can say them:
 *
 * 1. Push to talk has to mean hold. Saving its combination also sets the
 *    dictation mode to "hold". An install that is on "toggle" gets one notice
 *    with the action that switches it back.
 * 2. "Paste again" cannot always paste. Where the system keeps one app from
 *    typing into another, the text goes to the clipboard, and a notice says so
 *    before the person presses a key that seems to do nothing.
 */
export function ShortcutsTab() {
  const t = useT();
  const { config, loading, error, refetch, saveKeybind } = useKeybinds();
  const [state, setState] = useState<DictationState | null>(null);
  const [recording, setRecording] = useState<KeybindAction | null>(null);
  const [holdFailed, setHoldFailed] = useState(false);

  const loadState = useCallback(async () => {
    // Informational only: without an answer both notices stay away, and the
    // rows work as they are.
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
      // The combination itself is saved by now; what is missing is said in
      // the notice, with the action to try again.
      setHoldFailed(true);
    }
  }, [loadState]);

  const actionName = useCallback(
    (action: string) => {
      const key = ROWS.find((row) => row.action === action)?.labelKey ?? OTHER_ACTION_KEYS[action];
      return key ? t(key) : undefined;
    },
    [t],
  );

  // Only a known "toggle" raises the notice; a backend that reports no mode
  // has not said the person is on the wrong one.
  const holdIsOff = state?.mode === "toggle";
  const pasteBlocked = state?.insertion?.can_insert === false;

  // While the hook loads again it has neither a config nor an error.
  if (loading || (!config && !error)) {
    return (
      <VoicePage testId="voice-shortcuts">
        <LoadingGroup rows={ROWS.length} testId="shortcuts-loading" />
      </VoicePage>
    );
  }

  return (
    <VoicePage testId="voice-shortcuts">
      {error && (
        <Notice
          tone="fault"
          testId="shortcuts-load-failed"
          action={
            <Button variant="outline" onClick={() => void refetch()} data-testid="shortcuts-retry">
              {t("voiceui.common.retry")}
            </Button>
          }
        >
          {t("voiceui.shortcuts.load_failed")}
        </Notice>
      )}

      {config && (holdFailed || holdIsOff) && (
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

      {config && pasteBlocked && (
        <Notice testId="shortcuts-paste-notice">{t("voiceui.shortcuts.paste_blocked")}</Notice>
      )}

      {config && (
        <Group testId="shortcuts">
          {ROWS.map((row) => (
            <ShortcutRow
              key={row.action}
              action={row.action}
              label={t(row.labelKey)}
              config={config}
              recording={recording === row.action}
              onRecordingChange={(on) =>
                setRecording((prev) => (on ? row.action : prev === row.action ? null : prev))
              }
              onSave={saveKeybind}
              onSaved={row.action === "dictate" ? switchToHold : undefined}
              actionName={actionName}
            />
          ))}
        </Group>
      )}
    </VoicePage>
  );
}
