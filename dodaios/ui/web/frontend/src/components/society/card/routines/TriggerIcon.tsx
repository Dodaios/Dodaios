import { CalendarClock, Clock, Hand, Radio, Repeat, Timer, Webhook, Zap, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { triggerFamily, type TriggerFamily } from "./humanSchedule";

const ICONS: Record<TriggerFamily, LucideIcon> = {
  clock: CalendarClock,
  interval: Repeat,
  once: Timer,
  webhook: Webhook,
  event: Zap,
  source: Radio,
  manual: Hand,
  unknown: Clock,
};

export type RoutineTone = "active" | "paused" | "running" | "failed" | "parked";

/** The routine's trigger as a small tile; the ring says how it is doing. */
export function TriggerIcon({ trigger, tone = "active", size = "md", className }: {
  trigger: unknown; tone?: RoutineTone; size?: "md" | "lg"; className?: string;
}) {
  const Icon = ICONS[triggerFamily(trigger)];
  return <span
    aria-hidden
    data-tone={tone}
    className={cn(
      "relative inline-flex shrink-0 items-center justify-center border transition-colors duration-200",
      size === "lg" ? "h-10 w-10 rounded-xl" : "h-8 w-8 rounded-[10px]",
      tone === "paused" || tone === "parked" ? "border-border bg-secondary/40 text-faint-foreground"
        : tone === "failed" ? "border-destructive/35 bg-destructive/[0.07] text-destructive"
        : tone === "running" ? "border-primary/45 bg-primary/[0.08] text-primary"
        : "border-border bg-secondary text-foreground-secondary",
      className,
    )}
  >
    <Icon size={size === "lg" ? 18 : 15} strokeWidth={1.75} />
    {tone === "running" && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-primary motion-safe:animate-pulse" />}
    {tone === "parked" && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-warning" />}
  </span>;
}
