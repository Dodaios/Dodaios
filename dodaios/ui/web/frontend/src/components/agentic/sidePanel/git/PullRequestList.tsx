import { useState } from "react";
import { fill, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { QuickTooltip } from "@/components/ui/tooltip";
import { agoLabel, CiBadge, PR_ICON, PR_TONE, prStateLabel } from "./gitBadges";
import type { PullRequest } from "./gitOverviewApi";
import { ShowMore } from "./Section";

/** Drawn before "show all": enough to see everything that is broken. */
const FIRST_PAGE = 6;

function updatedSeconds(pr: PullRequest): number {
  const stamp = Date.parse(pr.updated_at);
  return Number.isFinite(stamp) ? Math.floor(stamp / 1000) : 0;
}

function PullRequestRow({ pr, defaultBranch }: { pr: PullRequest; defaultBranch: string }) {
  const t = useT();
  const lang = useRunLocale();
  const Icon = PR_ICON[pr.state];
  // Into the default branch is the rule; only another target is worth the space.
  const facts: { text: string; tone?: string }[] = [{ text: pr.base === defaultBranch ? pr.head : `${pr.head} → ${pr.base}` }];
  if (pr.conflicting) facts.push({ text: t("ide_side_panel.git.prs.conflicts"), tone: "text-destructive" });
  if (pr.review === "changes_requested") facts.push({ text: t("ide_side_panel.git.prs.changes_requested"), tone: "text-destructive" });
  if (pr.review === "approved") facts.push({ text: t("ide_side_panel.git.prs.approved"), tone: "text-success" });
  if (pr.review === "review_required") facts.push({ text: t("ide_side_panel.git.prs.review_required") });
  if (pr.fork && pr.author) facts.push({ text: fill(t("ide_side_panel.git.prs.from_fork"), { author: pr.author }) });
  const updated = updatedSeconds(pr);
  if (updated) facts.push({ text: agoLabel(updated, lang, t) });
  return (
    <li data-testid="git-pr-row" data-number={pr.number} data-state={pr.state} className="flex min-h-[38px] items-center gap-1 pl-3 pr-1 hover:bg-secondary/40">
      <button
        type="button"
        data-testid="git-pr-open"
        onClick={() => void openExternalUrl(pr.url)}
        className="flex min-w-0 flex-1 items-start gap-2 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
      >
        <QuickTooltip content={prStateLabel(t, pr)} side="bottom" className="mt-0.5 inline-flex shrink-0">
          <Icon className={cn("h-3.5 w-3.5", PR_TONE[pr.state])} aria-hidden />
        </QuickTooltip>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="flex min-w-0 items-baseline gap-1.5">
            <span className={cn("shrink-0 font-mono text-[11px] tabular-nums", PR_TONE[pr.state])}>#{pr.number}</span>
            <span className="truncate text-[12.5px] text-foreground">{pr.title}</span>
          </span>
          {/* Too narrow for everything: the age at the end is what gets cut. */}
          <span className="mt-0.5 flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap text-[10.5px] text-muted-foreground">
            {facts.map((fact, index) => (
              <span key={fact.text} className={cn(index === 0 ? "min-w-[4rem] truncate font-mono" : "shrink-0", fact.tone)}>
                {index > 0 && <span className="mr-1.5 text-muted-foreground/60" aria-hidden>·</span>}
                {fact.text}
              </span>
            ))}
          </span>
        </span>
      </button>
      <CiBadge ci={pr.ci} />
    </li>
  );
}

/** Every open pull request, what is broken first; a click opens it on GitHub. */
export function PullRequestList({ prs, defaultBranch }: { prs: PullRequest[]; defaultBranch: string }) {
  const t = useT();
  const [all, setAll] = useState(false);
  if (prs.length === 0) {
    return <p data-testid="git-prs-empty" className="px-3 pb-2.5 text-[11.5px] text-muted-foreground">{t("ide_side_panel.git.prs.none")}</p>;
  }
  const shown = all ? prs : prs.slice(0, FIRST_PAGE);
  return (
    <>
      <ul aria-label={t("ide_side_panel.git.prs.title")} className="pb-1">
        {shown.map((pr) => (
          <PullRequestRow key={pr.number} pr={pr} defaultBranch={defaultBranch} />
        ))}
      </ul>
      {prs.length > shown.length && (
        <ShowMore testId="git-prs-more" label={fill(t("ide_side_panel.git.show_all"), { n: prs.length })} onClick={() => setAll(true)} />
      )}
    </>
  );
}
