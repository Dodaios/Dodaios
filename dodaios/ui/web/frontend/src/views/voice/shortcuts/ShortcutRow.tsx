import { useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";

import {
  validateCombo,
  type KeybindAction,
  type KeybindSaveResult,
  type KeybindsConfig,
} from "@/hooks/useHotkey";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { formatCombo } from "@/views/settings/KeybindRow";
import { useChordCapture } from "@/views/settings/useChordCapture";
import { IconAction, Keycap, Row } from "@/views/voice/kit";
import { RowFault } from "@/views/voice/shortcuts/RowFault";

/** Why the last combination was not taken. */
type Fault =
  /** Another action already has it; `action` is that action's id. */
  | { kind: "taken"; action?: string }
  /** The save was refused or did not go through. */
  | { kind: "save_failed" };

function normalise(combo: string | undefined): string {
  return (combo ?? "").trim().toLowerCase();
}

/**
 * One shortcut: its name, and its key combination as the control.
 *
 * Clicking the combination records a new one: hold the keys, let go, and it
 * is saved. Escape or a second click leaves it as it was. While recording, a
 * shortcut that has a combination can also be removed.
 *
 * The recording itself (`useChordCapture`), the check against the other
 * actions (`validateCombo`) and the save are the ones Settings uses; this is
 * only another face on them.
 */
export function ShortcutRow({
  action,
  label,
  config,
  recording,
  onRecordingChange,
  onSave,
  onSaved,
  actionName,
}: {
  action: KeybindAction;
  label: string;
  config: KeybindsConfig;
  /** Whether this row is the one recording. The owner keeps it to one row. */
  recording: boolean;
  onRecordingChange: (recording: boolean) => void;
  onSave: (action: KeybindAction, combo: string) => Promise<KeybindSaveResult>;
  /** Runs after a new combination was accepted. */
  onSaved?: (combo: string) => void | Promise<void>;
  /** The name a person knows another action by, for "already used by". */
  actionName: (action: string) => string | undefined;
}) {
  const t = useT();
  // Every read defaults: a backend that does not know this action yet sends
  // no entry for it.
  const current = normalise(config.keybinds?.[action]);

  // The chord as it grows, while keys are down.
  const [preview, setPreview] = useState<string | null>(null);
  // What the backend just accepted, shown until the reloaded config says the same.
  const [accepted, setAccepted] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [fault, setFault] = useState<Fault | null>(null);

  useEffect(() => {
    setAccepted(null);
  }, [current]);

  // Another row took over the recording: this row's half-built chord is gone.
  useEffect(() => {
    if (!recording) setPreview(null);
  }, [recording]);

  const shown = accepted ?? current;

  const others = useMemo(() => {
    const out: Record<string, string> = {};
    for (const [other, combo] of Object.entries(config.keybinds ?? {})) {
      if (other !== action) out[other] = combo ?? "";
    }
    return out;
  }, [config, action]);

  async function save(next: string) {
    const combo = normalise(next);
    // Nothing pressed, or the combination it already has.
    if (!combo || combo === shown) return;
    // The same combination on two actions is the one thing the backend
    // refuses, so it is said here instead of being sent.
    const verdict = validateCombo(combo, others);
    if (verdict.status === "error") {
      setFault({ kind: "taken", action: verdict.conflict?.action });
      return;
    }
    setSaving(true);
    try {
      await onSave(action, combo);
    } catch {
      setFault({ kind: "save_failed" });
      return;
    } finally {
      setSaving(false);
    }
    setAccepted(combo);
    await onSaved?.(combo);
  }

  async function remove() {
    onRecordingChange(false);
    setSaving(true);
    try {
      await onSave(action, "");
      setAccepted("");
    } catch {
      setFault({ kind: "save_failed" });
    } finally {
      setSaving(false);
    }
  }

  useChordCapture(recording, {
    onPreview: setPreview,
    // Letting go of every key ends the gesture and saves.
    onCommit: (next) => {
      onRecordingChange(false);
      void save(next);
    },
    onCancel: () => onRecordingChange(false),
  });

  function toggleRecording() {
    if (!recording) setFault(null);
    onRecordingChange(!recording);
  }

  const keys = recording ? preview : shown;
  const spoken = shown ? formatCombo(shown) : t("voiceui.shortcuts.none");

  let faultText: string | null = null;
  if (fault?.kind === "save_failed") {
    faultText = t("voiceui.shortcuts.save_failed");
  } else if (fault?.kind === "taken") {
    const name = fault.action ? actionName(fault.action) : undefined;
    faultText = name
      ? fill(t("voiceui.shortcuts.taken"), { action: name })
      : t("voiceui.shortcuts.taken_other");
  }

  return (
    <Row
      label={label}
      testId={`shortcut-row-${action}`}
      below={faultText && <RowFault testId={`shortcut-fault-${action}`}>{faultText}</RowFault>}
    >
      {recording && shown && (
        <IconAction
          label={t("voiceui.shortcuts.remove")}
          testId={`shortcut-remove-${action}`}
          onClick={() => void remove()}
        >
          <X aria-hidden="true" />
        </IconAction>
      )}
      <button
        type="button"
        aria-label={`${label}: ${spoken}`}
        aria-pressed={recording}
        // App-level key chords stand down while this is set, so the keys being
        // recorded reach the recorder instead of opening something.
        data-keybind-recording={recording ? "true" : undefined}
        data-testid={`shortcut-keys-${action}`}
        disabled={saving}
        onClick={toggleRecording}
        className={cn(
          "inline-flex min-h-10 items-center gap-1 rounded-md px-2 transition-colors duration-150 hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-strong disabled:pointer-events-none disabled:opacity-50",
          recording && "bg-secondary ring-2 ring-border-strong",
        )}
      >
        {keys ? (
          formatCombo(keys)
            .split(" + ")
            .map((key, index) => <Keycap key={`${key}-${index}`}>{key}</Keycap>)
        ) : (
          <span className="px-1 text-title text-muted-foreground">
            {recording ? t("voiceui.shortcuts.press_keys") : t("voiceui.shortcuts.none")}
          </span>
        )}
      </button>
    </Row>
  );
}
