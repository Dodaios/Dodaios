import { useEffect, useId, useRef, useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  CircleAlert,
  Copy,
  RotateCcw,
  Trash2,
} from "lucide-react";

import {
  DICTATION_OUTCOMES,
  polishStatusLabel,
  STT_FAILURE_REASONS,
  type DictationEntry,
} from "@/hooks/useDictation";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { IconAction } from "@/views/voice/kit";

import { timeOfDay } from "./days";

/**
 * One dictation in the history: the text that was delivered, the time, and
 * the actions on it.
 *
 * Beside the time stands at most one remark, and only when the dictation did
 * not simply arrive as asked: why it failed, what became of it instead, or
 * that the chosen rewrite fell back.
 *
 * Deleting takes two steps. The first only discards: the entry stays, struck
 * out, and can be restored. The second, offered on a discarded entry, removes
 * it for good.
 */
export interface HistoryEntryProps {
  entry: DictationEntry;
  /** BCP-47 locale of the interface language, for the clock. */
  locale: string;
  /**
   * A translation or a prompt rewrite is switched on, so a wording pass that
   * fell back delivered the text in another form than the one chosen.
   */
  rewriteChosen: boolean;
  /** Resolves to whether the text reached the clipboard. */
  onCopy: (entry: DictationEntry) => Promise<boolean>;
  onDiscard: (entry: DictationEntry) => Promise<void>;
  onRestore: (entry: DictationEntry) => Promise<void>;
  onDelete: (entry: DictationEntry) => Promise<void>;
}

type Tone = "fault" | "degraded" | "plain";

const KNOWN_OUTCOMES: ReadonlySet<string> = new Set(DICTATION_OUTCOMES);

const KNOWN_FAILURES: ReadonlySet<string> = new Set(STT_FAILURE_REASONS);

/** How long the copy action shows that it worked. */
const COPIED_MS = 1500;

/** The words for an outcome; nothing for a value this build does not know. */
function outcomeLabel(t: (key: string) => string, outcome: string): string {
  return KNOWN_OUTCOMES.has(outcome) ? t(`dictation.outcome.${outcome}`) : "";
}

/**
 * The sentence for a failed transcription. A reason this build does not know
 * gets the general sentence, never the stored value itself.
 */
function failureLabel(t: (key: string) => string, reason: string): string {
  return KNOWN_FAILURES.has(reason)
    ? t(`dictation.failure.${reason}`)
    : t("dictation.failure.unknown");
}

/**
 * Whether an outcome is worth a remark, and how loud.
 *
 * A dictation that arrived where it was meant to go gets none; neither does a
 * value from a newer backend.
 */
function outcomeTone(outcome: string): Tone | null {
  switch (outcome) {
    case "failed":
      return "fault";
    case "unavailable":
    case "partial":
    case "empty":
      return "degraded";
    case "clipboard_only":
    case "cancelled":
      return "plain";
    default:
      return null;
  }
}

/** The wording pass gave up and the words were delivered as recognised. */
function wordingFellBack(status: string): boolean {
  switch (status) {
    case "unavailable":
    case "local_only":
    case "timeout":
    case "provider_error":
    case "rejected_drift":
      return true;
    default:
      return false;
  }
}

/** The one remark an entry carries, or none. */
function remarkFor(
  t: (key: string) => string,
  entry: DictationEntry,
  rewriteChosen: boolean,
): { text: string; tone: Tone } | null {
  if (entry.error) {
    return {
      text: failureLabel(t, entry.error),
      tone: entry.outcome === "failed" ? "fault" : "degraded",
    };
  }
  const tone = outcomeTone(entry.outcome);
  const outcome = tone ? outcomeLabel(t, entry.outcome) : "";
  if (tone && outcome) return { text: outcome, tone };
  if (rewriteChosen && entry.polish_status && wordingFellBack(entry.polish_status)) {
    return { text: polishStatusLabel(t, entry.polish_status), tone: "degraded" };
  }
  return null;
}

export function HistoryEntry({
  entry,
  locale,
  rewriteChosen,
  onCopy,
  onDiscard,
  onRestore,
  onDelete,
}: HistoryEntryProps) {
  const t = useT();
  const heardId = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(copiedTimer.current), []);

  const delivered = entry.text || entry.raw_text;
  const hasText = Boolean(delivered);
  // Worth opening only when the delivered text is not simply what was heard.
  const heardDiffers =
    Boolean(entry.text) && Boolean(entry.raw_text) && entry.text !== entry.raw_text;
  // Without any text, the kept recording can be run again. So can the
  // recording of a partly transcribed entry: it was kept because words are
  // missing. The backend does both under the same call that restores a
  // discarded entry.
  const canTranscribeAgain = hasText
    ? entry.audio_available && entry.outcome === "partial"
    : entry.audio_available || entry.outcome === "failed" || entry.outcome === "partial";
  const remark = remarkFor(t, entry, rewriteChosen);
  const time = timeOfDay(entry.created_at, locale);

  async function run(action: (entry: DictationEntry) => Promise<void>) {
    setBusy(true);
    try {
      await action(entry);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!(await onCopy(entry))) return;
    setCopied(true);
    window.clearTimeout(copiedTimer.current);
    copiedTimer.current = window.setTimeout(() => setCopied(false), COPIED_MS);
  }

  return (
    <div className="px-block py-3" data-testid="dictation-entry">
      <div className={cn("flex gap-stack", hasText ? "items-start" : "items-center")}>
        <div className="min-w-0 flex-1">
          {hasText && (
            <p
              className={cn(
                "whitespace-pre-wrap break-words text-reading",
                entry.discarded ? "text-muted-foreground line-through" : "text-foreground",
              )}
              data-testid="dictation-entry-text"
            >
              {delivered}
            </p>
          )}
          <p className="flex flex-wrap items-center gap-x-stack text-body text-muted-foreground">
            {time && (
              <time dateTime={entry.created_at} className="tabular-nums">
                {time}
              </time>
            )}
            {remark && (
              <span className="inline-flex items-center gap-1" data-testid="dictation-entry-remark">
                {remark.tone === "fault" && (
                  <CircleAlert aria-hidden="true" className="h-4 w-4 shrink-0 text-destructive" />
                )}
                {remark.tone === "degraded" && (
                  <AlertTriangle aria-hidden="true" className="h-4 w-4 shrink-0 text-warning" />
                )}
                {remark.text}
              </span>
            )}
          </p>
        </div>

        <div className="flex shrink-0 items-center">
          {entry.discarded ? (
            <>
              <IconAction
                label={t("voiceui.dictation.restore")}
                disabled={busy}
                onClick={() => void run(onRestore)}
              >
                <RotateCcw aria-hidden="true" />
              </IconAction>
              <IconAction
                label={t("voiceui.dictation.delete_forever")}
                disabled={busy}
                onClick={() => void run(onDelete)}
                className="text-destructive hover:text-destructive"
              >
                <Trash2 aria-hidden="true" />
              </IconAction>
            </>
          ) : (
            <>
              {heardDiffers && (
                <IconAction
                  label={t("voiceui.dictation.heard")}
                  aria-expanded={open}
                  aria-controls={heardId}
                  onClick={() => setOpen((value) => !value)}
                >
                  <ChevronDown
                    aria-hidden="true"
                    className={cn(
                      "transition-transform duration-150 motion-reduce:transition-none",
                      open && "rotate-180",
                    )}
                  />
                </IconAction>
              )}
              {hasText && (
                <IconAction
                  label={copied ? t("voiceui.dictation.copied") : t("voiceui.common.copy")}
                  onClick={() => void copy()}
                >
                  {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
                </IconAction>
              )}
              {canTranscribeAgain && (
                <IconAction
                  label={t("voiceui.dictation.transcribe_again")}
                  disabled={busy}
                  onClick={() => void run(onRestore)}
                >
                  <RotateCcw aria-hidden="true" />
                </IconAction>
              )}
              <IconAction
                label={t("voiceui.common.delete")}
                disabled={busy}
                onClick={() => void run(onDiscard)}
              >
                <Trash2 aria-hidden="true" />
              </IconAction>
            </>
          )}
        </div>
      </div>

      {heardDiffers && open && !entry.discarded && (
        <p
          id={heardId}
          className="mt-stack whitespace-pre-wrap break-words border-l-2 border-border-strong pl-3 text-reading text-muted-foreground"
          data-testid="dictation-entry-heard"
        >
          {entry.raw_text}
        </p>
      )}
    </div>
  );
}
