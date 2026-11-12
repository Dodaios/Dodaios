import type { ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/** The pieces every part of the assistant's panel is built from. */

export const FOCUS = "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

/** One line of the panel: an icon, its words, and whatever trails them. */
export const PANEL_ROW = "flex min-h-8 w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1 text-left";
export const PANEL_ROW_BUTTON = cn(PANEL_ROW, "transition-colors hover:bg-secondary", FOCUS);
export const PANEL_ICON = "h-4 w-4 shrink-0 text-muted-foreground";

/** A titled part of the panel: a quiet label over its rows. */
export function PanelSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-label={title} data-testid={`assistant-panel-${id}`} className="mt-4 first:mt-0">
      <h2 className="px-2 pb-1 text-sm text-muted-foreground">{title}</h2>
      {children}
    </section>
  );
}

/** A line that says a part has nothing to show yet. */
export function PanelEmpty({ children, testId }: { children: ReactNode; testId?: string }) {
  return <p data-testid={testId} className={cn(PANEL_ROW, "text-sm text-muted-foreground")}>{children}</p>;
}

/** Unfolds the rows a part keeps back, and folds them away again. */
export function ShowMore({ open, onToggle, testId }: { open: boolean; onToggle: () => void; testId: string }) {
  const t = useT();
  const Icon = open ? ChevronUp : ChevronDown;
  return (
    <button type="button" data-testid={testId} aria-expanded={open} onClick={onToggle}
      className={cn(PANEL_ROW_BUTTON, "text-sm text-muted-foreground hover:text-foreground")}>
      <Icon aria-hidden strokeWidth={1.75} className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1 truncate">{t(open ? "sidebar.show_less" : "sidebar.show_more")}</span>
    </button>
  );
}
