import { CheckCircle2, CircleDashed, Clock, Loader2, PauseCircle, SkipForward, XCircle, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

const STATUS: Record<string, { icon: LucideIcon; tone: string; spin?: boolean }> = {
  completed: { icon: CheckCircle2, tone: "text-success" },
  failed: { icon: XCircle, tone: "text-destructive" },
  cancelled: { icon: XCircle, tone: "text-muted-foreground" },
  interrupted: { icon: XCircle, tone: "text-warning" },
  skipped: { icon: SkipForward, tone: "text-muted-foreground" },
  running: { icon: Loader2, tone: "text-primary", spin: true },
  pending: { icon: Clock, tone: "text-muted-foreground" },
  waiting: { icon: PauseCircle, tone: "text-warning" },
  legacy: { icon: CircleDashed, tone: "text-muted-foreground" },
};

/** One run's outcome as a glyph; `label` is its accessible name. */
export function RunStatusIcon({ status, label, size = 15, className }: {
  status: string; label: string; size?: number; className?: string;
}) {
  const entry = STATUS[status] ?? STATUS.pending;
  const Icon = entry.icon;
  return <Icon size={size} strokeWidth={2} role="img" aria-label={label}
    className={cn("shrink-0", entry.tone, entry.spin && "motion-safe:animate-spin", className)} />;
}
