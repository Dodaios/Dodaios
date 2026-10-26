/**
 * A titled group of roster rows ("Needs you", "Teams", "Agents"). The heading
 * carries a count and folds the group; the fold is remembered per section.
 */
import { useCallback, useId, useState, type ReactNode } from "react";
import { ChevronDown } from "lucide-react";

import { cn } from "@/lib/utils";

const COLLAPSED_KEY = "society.roster.sections.collapsed.v1";

function readCollapsed(): string[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? "[]");
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

export function useSectionFold(sectionId: string): [boolean, () => void] {
  const [folded, setFolded] = useState(() => readCollapsed().includes(sectionId));
  const toggle = useCallback(() => {
    setFolded((value) => {
      const next = !value;
      const stored = readCollapsed().filter((id) => id !== sectionId);
      try {
        localStorage.setItem(COLLAPSED_KEY, JSON.stringify(next ? [...stored, sectionId] : stored));
      } catch {
        // Private mode: the fold holds for this window.
      }
      return next;
    });
  }, [sectionId]);
  return [folded, toggle];
}

export function RosterSection({
  id,
  title,
  count,
  tone,
  action,
  children,
  className,
}: {
  id: string;
  title: string;
  count?: number;
  /** "attention" colours the heading for the Needs-you group. */
  tone?: "attention";
  /** A small trailing control in the heading. */
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const [folded, toggle] = useSectionFold(id);
  const bodyId = useId();
  return (
    <section className={cn("flex flex-col", className)} data-testid={`roster-section-${id}`} aria-label={title}>
      <div className="as-section-head as-reveal-host">
        <button
          type="button"
          onClick={toggle}
          aria-expanded={!folded}
          aria-controls={bodyId}
          className={cn(
            "-ml-1 flex min-w-0 items-center gap-1 rounded px-1 py-0.5 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            tone === "attention" && "text-warning hover:text-warning",
          )}
        >
          <span className="truncate">{title}</span>
          {count !== undefined ? <span className="as-section-count">{count}</span> : null}
          <ChevronDown
            aria-hidden
            className={cn("as-reveal h-3 w-3 shrink-0 transition-transform duration-150 motion-reduce:transition-none", folded && "-rotate-90")}
          />
        </button>
        {action ? <span className="ml-auto flex items-center">{action}</span> : null}
      </div>
      <div id={bodyId} hidden={folded}>
        {children}
      </div>
    </section>
  );
}
