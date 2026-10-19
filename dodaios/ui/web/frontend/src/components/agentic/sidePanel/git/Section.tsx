import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/** One titled block of the Git tab; the heading folds it. */
export function Section({
  id,
  title,
  count,
  open,
  onToggle,
  aside,
  children,
}: {
  id: string;
  title: string;
  count?: number;
  open: boolean;
  onToggle: () => void;
  /** Sits at the heading's right edge (a small action). */
  aside?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section data-testid={`git-section-${id}`} data-open={open || undefined} className="border-b border-border/60">
      <div className="flex h-8 items-center pr-2">
        <button
          type="button"
          data-testid={`git-section-toggle-${id}`}
          aria-expanded={open}
          onClick={onToggle}
          className="flex h-full min-w-0 flex-1 items-center gap-1 pl-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        >
          <ChevronRight
            className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform motion-reduce:transition-none", open && "rotate-90")}
            aria-hidden
          />
          <span className="truncate text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">{title}</span>
          {count !== undefined && <span className="shrink-0 text-[10.5px] tabular-nums text-muted-foreground/70">{count}</span>}
        </button>
        {aside}
      </div>
      {open && children}
    </section>
  );
}

/** "Show 20 more" under a list that is longer than it is useful to draw at once. */
export function ShowMore({ label, onClick, testId }: { label: string; onClick: () => void; testId: string }) {
  return (
    <button
      type="button"
      data-testid={testId}
      onClick={onClick}
      className="w-full px-3 py-2 text-left text-[11.5px] text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
    >
      {label}
    </button>
  );
}
