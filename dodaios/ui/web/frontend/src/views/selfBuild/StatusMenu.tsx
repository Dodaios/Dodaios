/**
 * The page's one control: a status pill ("Learning", "Paused", ...) that opens
 * a small menu with pause/resume, settings and the emergency stop. Everything
 * the page used to spread over a toolbar, a hero button and a footer lives
 * here, the way desktop chat apps tuck page options behind one button.
 */
import { useEffect, useRef, useState } from "react";
import { ChevronDown, OctagonX, Pause, Play, Settings2 } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { HeroTone } from "./Hero";

export function StatusMenu({
  tone,
  enabled,
  paused,
  pauseBusy,
  onPause,
  onSettings,
  onStopAll,
}: {
  tone: HeroTone | null;
  enabled: boolean;
  paused: boolean;
  pauseBusy: boolean;
  onPause: (paused: boolean) => void;
  onSettings: () => void;
  /** Absent once everything is already stopped. */
  onStopAll?: () => void;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const run = (fn: () => void) => () => {
    setOpen(false);
    fn();
  };

  return (
    <div ref={root} className="relative shrink-0">
      <button
        type="button"
        data-testid="self-build-menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "inline-flex h-8 items-center gap-2 rounded-full border border-border px-3 text-sm text-foreground transition-colors hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          open && "bg-secondary",
        )}
      >
        {tone && (
          <span data-testid="self-build-status" data-tone={tone} className="inline-flex items-center gap-2">
            <span aria-hidden className={cn("h-2 w-2 rounded-full", DOT[tone])} />
            {t(`self_build.status.${tone}`)}
          </span>
        )}
        <ChevronDown aria-hidden className={cn("h-3.5 w-3.5 text-muted-foreground transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-10 z-50 w-64 rounded-xl border border-border bg-popover p-1 text-popover-foreground shadow-float"
        >
          {enabled && (
            <MenuItem
              testId="self-build-pause"
              icon={paused ? <Play className="h-4 w-4" aria-hidden /> : <Pause className="h-4 w-4" aria-hidden />}
              label={paused ? t("self_build.resume") : t("self_build.pause")}
              hint={paused ? undefined : t("self_build.page.pause_hint")}
              disabled={pauseBusy}
              onClick={run(() => onPause(!paused))}
            />
          )}
          <MenuItem
            testId="self-build-settings"
            icon={<Settings2 className="h-4 w-4" aria-hidden />}
            label={t("self_build.settings")}
            onClick={run(onSettings)}
          />
          {onStopAll && (
            <>
              <div role="separator" className="mx-2 my-1 h-px bg-border" />
              <MenuItem
                testId="society-stop-all"
                icon={<OctagonX className="h-4 w-4" aria-hidden />}
                label={t("self_build.stop_all")}
                hint={t("self_build.page.stop_hint")}
                danger
                onClick={run(onStopAll)}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}

const DOT: Record<HeroTone, string> = {
  running: "bg-success",
  silent: "bg-accent",
  paused: "bg-warning",
  stopped: "bg-destructive",
  off: "bg-border-strong",
};

function MenuItem({
  testId,
  icon,
  label,
  hint,
  danger = false,
  disabled = false,
  onClick,
}: {
  testId: string;
  icon: React.ReactNode;
  label: string;
  hint?: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "flex w-full items-start gap-3 rounded-lg px-3 py-2 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
        danger ? "text-destructive hover:bg-destructive/10" : "text-foreground hover:bg-secondary",
      )}
    >
      <span className="mt-0.5 shrink-0">{icon}</span>
      <span className="min-w-0">
        <span className="block">{label}</span>
        {hint && <span className="mt-0.5 block text-xs leading-snug text-muted-foreground">{hint}</span>}
      </span>
    </button>
  );
}
