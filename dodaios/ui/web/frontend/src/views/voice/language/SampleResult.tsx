import { ArrowDown } from "lucide-react";

import type { DictationPolishTest } from "@/hooks/useDictation";
import { useT } from "@/i18n";
import { RowNote } from "@/views/voice/keys/RowNote";

/** The outcomes in which the model really rewrote the sample. */
const CHANGED = new Set(["applied", "translated", "prompted"]);

/** The outcomes that have a sentence of their own. */
const EXPLAINED = new Set([
  "unchanged",
  "unavailable",
  "local_only",
  "timeout",
  "provider_error",
  "rejected_drift",
]);

/** What the last run of the sample test left behind. */
export type SampleOutcome =
  | { kind: "result"; result: DictationPolishTest }
  | { kind: "failed" }
  | null;

/**
 * The result of the sample test.
 *
 * When the model rewrote the sample, the two texts stand one above the other:
 * what was said, then what would be written. When it did not, one sentence
 * says why.
 */
export function SampleResult({ outcome }: { outcome: SampleOutcome }) {
  const t = useT();
  if (!outcome) return null;

  if (outcome.kind === "failed") {
    return <RowNote testId="voice-language-sample-fault">{t("voiceui.language.test_failed")}</RowNote>;
  }

  const { status, sample_in: before, sample_out: after } = outcome.result;
  if (!CHANGED.has(status)) {
    const reason = EXPLAINED.has(status) ? status : "other";
    return (
      <p className="text-body text-foreground" data-testid="voice-language-sample-unchanged">
        {t(`voiceui.language.test_result.${reason}`)}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-row" data-testid="voice-language-sample-result">
      <p
        className="break-words text-reading text-muted-foreground"
        data-testid="voice-language-sample-before"
      >
        {before}
      </p>
      <ArrowDown aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
      <p className="break-words text-reading text-foreground" data-testid="voice-language-sample-after">
        {after}
      </p>
    </div>
  );
}
