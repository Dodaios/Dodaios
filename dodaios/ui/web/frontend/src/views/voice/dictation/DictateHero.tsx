import { Mic, Square } from "lucide-react";

import { SkeletonBar } from "@/components/layout/PanelSkeleton";
import { Button } from "@/components/ui/button";
import type { DictationStatus } from "@/hooks/useDictation";
import { useT } from "@/i18n";
import { formatCombo } from "@/views/settings/KeybindRow";
import { Keycap } from "@/views/voice/kit";

/**
 * How to dictate: one round microphone button and one headline.
 *
 * The headline names the shortcut that is really configured, key by key. The
 * button does the same thing as the shortcut: it starts a dictation, and
 * while one runs it stops it.
 */
export interface DictateHeroProps {
  status: DictationStatus | null;
  loading: boolean;
  /** A start or stop request is on its way. */
  busy: boolean;
  onToggle: () => void;
}

const BUTTON_SIZE = "h-24 w-24 rounded-full";

export function DictateHero({ status, loading, busy, onToggle }: DictateHeroProps) {
  const t = useT();

  if (loading) {
    return (
      <section
        aria-busy="true"
        className="flex flex-col items-center gap-block py-6"
        data-testid="dictation-hero-loading"
      >
        <SkeletonBar className={BUTTON_SIZE} />
        <SkeletonBar className="h-10 w-80 max-w-full" />
      </section>
    );
  }

  const available = Boolean(status?.available);
  const active = available && Boolean(status?.active);

  return (
    <section className="flex flex-col items-center gap-block py-6 text-center">
      <span className="relative inline-flex">
        {active && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute -inset-2 rounded-full border-2 border-success motion-safe:animate-pulse"
          />
        )}
        <Button
          type="button"
          aria-label={active ? t("voiceui.dictation.stop") : t("voiceui.dictation.start")}
          disabled={!available || busy}
          onClick={onToggle}
          className={`${BUTTON_SIZE} p-0 [&>svg]:h-9 [&>svg]:w-9`}
          data-testid="dictation-toggle"
        >
          {active ? <Square aria-hidden="true" /> : <Mic aria-hidden="true" />}
        </Button>
      </span>

      {available && (
        <h2
          className="flex min-h-10 flex-wrap items-center justify-center gap-row text-display text-foreground-strong"
          data-testid="dictation-headline"
        >
          {active ? t("voiceui.dictation.listening") : <Instruction status={status} />}
        </h2>
      )}
    </section>
  );
}

/**
 * "Hold [⌃] [⌥] to dictate", with every key of the shortcut on its own cap.
 *
 * The hold key comes first; a computer that only has the press-once key gets
 * that one named, and one with neither is told to use the button.
 */
function Instruction({ status }: { status: DictationStatus | null }) {
  const t = useT();
  const hold = status?.hotkey ?? "";
  const press = status?.hotkey_toggle ?? "";
  const combo = hold || press;
  if (!combo) return <>{t("voiceui.dictation.click")}</>;

  // The language owns the word order, so the sentence is cut at its key slot.
  const template = t(hold ? "voiceui.dictation.hold" : "voiceui.dictation.press");
  const [before, after = ""] = template.split("{keys}");
  const keys = formatCombo(combo).split(" + ").filter(Boolean);

  return (
    <>
      {before.trim() && <span>{before.trim()}</span>}
      {keys.map((key, index) => (
        <Keycap key={`${key}-${index}`} large>
          {key}
        </Keycap>
      ))}
      {after.trim() && <span>{after.trim()}</span>}
    </>
  );
}
