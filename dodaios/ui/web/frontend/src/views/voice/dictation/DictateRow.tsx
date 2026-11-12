import { Mic, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { DictationStatus } from "@/hooks/useDictation";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { formatCombo } from "@/views/settings/KeybindRow";
import { Group, Keycap, LoadingGroup, Row } from "@/views/voice/kit";

/**
 * How to dictate, as one row like every other row of the section.
 *
 * The label names the shortcut that is really configured, key by key. The
 * small round button at its end does the same thing as the shortcut: it starts
 * a dictation, and while one runs it stops it.
 *
 * A computer where dictation is not set up gets no row: the notice below it
 * says so and leads to the keys.
 */
export interface DictateRowProps {
  status: DictationStatus | null;
  loading: boolean;
  /** A start or stop request is on its way. */
  busy: boolean;
  onToggle: () => void;
}

export function DictateRow({ status, loading, busy, onToggle }: DictateRowProps) {
  const t = useT();

  if (loading) return <LoadingGroup rows={1} testId="dictation-row-loading" />;
  if (!status?.available) return null;

  const active = Boolean(status.active);

  return (
    <Group testId="dictation-row">
      <Row
        label={
          <span className="inline-flex items-center gap-row" data-testid="dictation-headline">
            {active ? t("voiceui.dictation.listening") : <Instruction status={status} />}
          </span>
        }
      >
        <span className="relative inline-flex">
          {active && (
            <span
              aria-hidden="true"
              className="pointer-events-none absolute -inset-1 rounded-full border-2 border-success motion-safe:animate-pulse"
            />
          )}
          <Button
            type="button"
            variant="secondary"
            size="icon"
            aria-label={active ? t("voiceui.dictation.stop") : t("voiceui.dictation.start")}
            disabled={busy}
            onClick={onToggle}
            className={cn("h-10 w-10 rounded-full", "[&>svg]:h-[18px] [&>svg]:w-[18px]")}
            data-testid="dictation-toggle"
          >
            {active ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
          </Button>
        </span>
      </Row>
    </Group>
  );
}

/**
 * "Hold [⌃] [⌥] to dictate", with every key of the shortcut on its own cap.
 *
 * The hold key comes first; a computer that only has the press-once key gets
 * that one named, and one with neither is told to use the button.
 */
function Instruction({ status }: { status: DictationStatus }) {
  const t = useT();
  const hold = status.hotkey ?? "";
  const press = status.hotkey_toggle ?? "";
  const combo = hold || press;
  if (!combo) return <>{t("voiceui.dictation.click")}</>;

  // The language owns the word order, so the sentence is cut at its key slot.
  const template = t(hold ? "voiceui.dictation.hold" : "voiceui.dictation.press");
  const [before, after = ""] = template.split("{keys}");
  const keys = formatCombo(combo).split(" + ").filter(Boolean);

  return (
    <>
      {before.trim() && <span>{before}</span>}
      {keys.map((key, index) => (
        <Keycap key={`${key}-${index}`}>{key}</Keycap>
      ))}
      {after.trim() && <span>{after}</span>}
    </>
  );
}
