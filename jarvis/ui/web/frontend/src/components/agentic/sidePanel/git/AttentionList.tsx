import { Check, CircleX, GitMerge, TriangleAlert, type LucideIcon } from "lucide-react";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import type { AttentionItem, AttentionKind } from "./gitInsights";
import { plural } from "./gitBadges";

const TONE: Record<AttentionItem["tone"], { icon: LucideIcon; className: string }> = {
  danger: { icon: CircleX, className: "text-destructive" },
  warning: { icon: TriangleAlert, className: "text-warning" },
  neutral: { icon: GitMerge, className: "text-[hsl(var(--gh-merged))]" },
};

/** What the row's click does, named on its right edge. */
const ACTION: Record<AttentionKind, string> = {
  ci_failing: "show",
  default_ci: "view",
  pr_conflicts: "show",
  changes_requested: "show",
  default_behind: "update",
  unpushed: "show",
  behind: "show",
  cleanup: "clean_up",
};

/**
 * What needs a look across the whole repository, worst first: failing checks,
 * conflicts, work that is only on this computer, branches that fell behind,
 * merged branches that can go. One line each; a click goes to the fix.
 */
export function AttentionList({ items, onAct }: { items: AttentionItem[]; onAct: (item: AttentionItem) => void }) {
  const t = useT();
  if (items.length === 0) {
    return (
      <p data-testid="git-all-clear" className="flex items-center gap-1.5 border-b border-border/60 px-3 py-2.5 text-[11.5px] text-muted-foreground">
        <Check className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
        {t("ide_side_panel.git.attention.none")}
      </p>
    );
  }
  return (
    <section data-testid="git-attention" aria-label={t("ide_side_panel.git.attention.title")} className="border-b border-border/60 py-1">
      <h3 className="flex h-7 items-center gap-1.5 px-3 text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground">
        {t("ide_side_panel.git.attention.title")}
        <span className="tabular-nums text-muted-foreground/70">{items.length}</span>
      </h3>
      <ul>
        {items.map((item) => {
          const tone = TONE[item.tone];
          const Icon = tone.icon;
          return (
            <li key={item.kind}>
              <button
                type="button"
                data-testid="git-attention-item"
                data-kind={item.kind}
                onClick={() => onAct(item)}
                className="group/item flex w-full items-start gap-2 px-3 py-1.5 text-left hover:bg-secondary/60 focus-visible:bg-secondary/60 focus-visible:outline-none"
              >
                <Icon className={cn("mt-px h-3.5 w-3.5 shrink-0", tone.className)} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-[12px] leading-snug text-foreground">{plural(t, `ide_side_panel.git.attention.${item.kind}`, item.count)}</span>
                  <span className="block truncate font-mono text-[10.5px] text-muted-foreground">
                    {item.names.join(", ")}
                    {item.count > item.names.length ? ` +${item.count - item.names.length}` : ""}
                  </span>
                </span>
                <span className="shrink-0 pt-px text-[11px] text-accent group-hover/item:underline">
                  {t(`ide_side_panel.git.attention.action.${ACTION[item.kind]}`)}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
