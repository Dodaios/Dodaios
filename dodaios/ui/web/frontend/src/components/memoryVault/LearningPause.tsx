/**
 * The "don't remember" switch. One endless conversation has no temporary
 * chat, so this is where the user stops background learning for a while:
 * an hour, until tomorrow, or until they turn it back on. Explicit
 * "remember that" requests still work while it is paused.
 */
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { PauseCircle, PlayCircle } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { setLearningPause, useLearningPause } from "@/lib/personalMemoryApi";

function minutesUntilTomorrowMorning(): number {
  const now = new Date();
  const next = new Date(now);
  next.setDate(now.getDate() + 1);
  next.setHours(7, 0, 0, 0);
  return Math.max(1, Math.round((next.getTime() - now.getTime()) / 60_000));
}

export function LearningPause({ onError }: { onError: (message: string) => void }) {
  const t = useT();
  const queryClient = useQueryClient();
  const pause = useLearningPause();
  const [open, setOpen] = useState(false);
  const paused = pause.data?.paused ?? false;
  const until = pause.data?.until ?? null;

  const apply = async (span: number | "forever" | null) => {
    setOpen(false);
    try {
      await setLearningPause(span);
      await queryClient.invalidateQueries({ queryKey: ["memory-vault"] });
    } catch (error) {
      onError(error instanceof Error ? error.message : String(error));
    }
  };

  const untilLabel =
    until === "forever"
      ? t("vault.pause_until_resumed")
      : until
        ? fill(t("vault.pause_until"), {
            time: new Date(until).toLocaleString(undefined, { weekday: "short", hour: "2-digit", minute: "2-digit" }),
          })
        : "";

  const item =
    "flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

  return (
    <div className="px-2 pb-1" data-testid="vault-pause">
      {paused ? (
        <button type="button" onClick={() => void apply(null)} className={cn(item, "bg-[hsl(35_95%_55%/0.12)] text-foreground hover:bg-[hsl(35_95%_55%/0.18)]")}>
          <PlayCircle className="h-3.5 w-3.5 text-[hsl(35_95%_55%)]" />
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{t("vault.pause_resume")}</span>
            <span className="block truncate text-[11px] text-muted-foreground">{untilLabel}</span>
          </span>
        </button>
      ) : (
        <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)} className={cn(item, "text-muted-foreground hover:bg-sheen/[0.05] hover:text-foreground")}>
          <PauseCircle className="h-3.5 w-3.5" /> {t("vault.pause")}
        </button>
      )}
      {open && !paused && (
        <div className="mt-1 space-y-0.5 rounded-lg border border-border bg-popover p-1" role="menu">
          <button type="button" role="menuitem" className={cn(item, "hover:bg-sheen/[0.05]")} onClick={() => void apply(60)}>
            {t("vault.pause_hour")}
          </button>
          <button type="button" role="menuitem" className={cn(item, "hover:bg-sheen/[0.05]")} onClick={() => void apply(minutesUntilTomorrowMorning())}>
            {t("vault.pause_tomorrow")}
          </button>
          <button type="button" role="menuitem" className={cn(item, "hover:bg-sheen/[0.05]")} onClick={() => void apply("forever")}>
            {t("vault.pause_forever")}
          </button>
        </div>
      )}
    </div>
  );
}
