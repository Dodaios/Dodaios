import type { ReactNode, SVGProps } from "react";
import { CircleCheck, CircleDashed, CircleX, GitMerge, GitPullRequest, GitPullRequestClosed, GitPullRequestDraft, Loader2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { QuickTooltip } from "@/components/ui/tooltip";
import type { CiState, CiStatus, PullRequest, PullRequestState } from "./gitOverviewApi";

type Translate = (key: string) => string;

/** "1 commit" / "3 commits": the locale's own one-and-many forms. */
export function plural(t: Translate, key: string, n: number): string {
  return fill(t(`${key}_${n === 1 ? "one" : "other"}`), { n });
}

// GitHub's pull request colours: open green, merged purple, closed red, the
// merge queue amber, a draft grey. Each maps to a theme token that has a light
// and a dark value.
export const PR_TONE: Record<PullRequestState, string> = {
  draft: "text-muted-foreground",
  open: "text-success",
  queued: "text-warning",
  merged: "text-[hsl(var(--gh-merged))]",
  closed: "text-destructive",
};

/** GitHub's merge-queue mark: the merge glyph with the arm still dashed — waiting to land. */
function MergeQueueIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <circle cx="18" cy="18" r="3" />
      <circle cx="6" cy="6" r="3" />
      <path d="M6 21V9" />
      <path d="M6 9a9 9 0 0 0 9 9" strokeDasharray="2.5 3" />
    </svg>
  );
}

export const PR_ICON: Record<PullRequestState, (props: SVGProps<SVGSVGElement>) => ReactNode> = {
  draft: (props) => <GitPullRequestDraft {...props} />,
  open: (props) => <GitPullRequest {...props} />,
  queued: (props) => <MergeQueueIcon {...props} />,
  merged: (props) => <GitMerge {...props} />,
  closed: (props) => <GitPullRequestClosed {...props} />,
};

// CI gets the shapes GitHub uses for checks — a circle that is dashed,
// spinning, ticked or crossed — so a green tick can never be read as a merge.
export const CI_TONE: Record<CiState, string> = {
  none: "text-muted-foreground/60",
  pending: "text-warning",
  running: "text-warning",
  success: "text-success",
  failure: "text-destructive",
};

export function CiIcon({ state, className }: { state: CiState; className?: string }) {
  const cls = cn("h-4 w-4", CI_TONE[state], className);
  if (state === "running") return <Loader2 className={cn(cls, "animate-spin motion-reduce:animate-none")} aria-hidden />;
  if (state === "success") return <CircleCheck className={cls} aria-hidden />;
  if (state === "failure") return <CircleX className={cls} aria-hidden />;
  return <CircleDashed className={cls} aria-hidden />;
}

/** An icon that opens a GitHub page; a plain span when there is nowhere to go. */
export function LinkIcon({
  url,
  tip,
  label,
  testId,
  children,
}: {
  url: string;
  tip: string;
  label: string;
  testId: string;
  children: ReactNode;
}) {
  const body = url ? (
    <button
      type="button"
      data-testid={testId}
      aria-label={label}
      onClick={(event) => {
        event.stopPropagation();
        void openExternalUrl(url);
      }}
      className="inline-flex h-6 min-w-6 items-center justify-center gap-0.5 rounded-md px-1 hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      {children}
    </button>
  ) : (
    <span data-testid={testId} aria-label={label} className="inline-flex h-6 min-w-6 items-center justify-center gap-0.5 px-1">
      {children}
    </span>
  );
  return (
    <QuickTooltip content={tip} side="bottom" className="inline-flex shrink-0">
      {body}
    </QuickTooltip>
  );
}

export function prStateLabel(t: Translate, pr: PullRequest): string {
  if (pr.state === "queued" && pr.queue_position) return fill(t("ide_side_panel.git.pr.queued_position"), { n: pr.queue_position });
  return t(`ide_side_panel.git.pr.${pr.state}`);
}

/** CI in one plain line: "CI failed — 2 of 14 checks: lint, tests". */
export function ciSentence(t: Translate, ci: CiStatus): string {
  const head = t(`ide_side_panel.git.ci.${ci.state}`);
  if (ci.state === "none" || ci.total === 0) return head;
  const count =
    ci.state === "failure"
      ? fill(t("ide_side_panel.git.ci_failed_of"), { failed: ci.failed, total: ci.total })
      : fill(t("ide_side_panel.git.ci_passed_of"), { passed: ci.passed, total: ci.total });
  const names = ci.state === "failure" && ci.names.length > 0 ? `: ${ci.names.join(", ")}` : "";
  return `${head} — ${count}${names}`;
}

export function PullRequestBadge({ prs }: { prs: PullRequest[] }) {
  const t = useT();
  const [pr, ...others] = prs;
  if (!pr) return null;
  const Icon = PR_ICON[pr.state];
  const lines = [
    fill(t("ide_side_panel.git.pr_tooltip"), { state: prStateLabel(t, pr), number: pr.number, title: pr.title, base: pr.base }),
    ...others.map((other) => `#${other.number} · ${prStateLabel(t, other)}`),
    t("ide_side_panel.git.click_pr"),
  ];
  return (
    <LinkIcon url={pr.url} tip={lines.join("\n")} label={`${prStateLabel(t, pr)} #${pr.number}`} testId="git-pr">
      <Icon className={cn("h-3.5 w-3.5", PR_TONE[pr.state])} data-pr-state={pr.state} aria-hidden />
      <span className={cn("font-mono text-[11px] tabular-nums", PR_TONE[pr.state])}>#{pr.number}</span>
    </LinkIcon>
  );
}

export function CiBadge({ ci, stale = false }: { ci: CiStatus; stale?: boolean }) {
  const t = useT();
  if (ci.state === "none") return null;
  const lines = [ciSentence(t, ci)];
  if (ci.state !== "failure" && ci.names.length > 0) lines.push(fill(t("ide_side_panel.git.ci_running_names"), { names: ci.names.join(", ") }));
  if (stale && ci.commit) lines.push(fill(t("ide_side_panel.git.ci_stale"), { commit: ci.commit.slice(0, 7) }));
  if (ci.url) lines.push(t("ide_side_panel.git.click_ci"));
  return (
    <LinkIcon url={ci.url} tip={lines.join("\n")} label={t(`ide_side_panel.git.ci.${ci.state}`)} testId="git-ci">
      <span data-ci-state={ci.state} className={cn("inline-flex", stale && "opacity-60")}>
        <CiIcon state={ci.state} />
      </span>
    </LinkIcon>
  );
}

/** Today's commits read "3 hours ago"; older ones show the day ("3 Oct", plus the year when it differs). */
export function commitDateLabel(seconds: number, lang: string, now = Date.now()): string {
  const date = new Date(seconds * 1000);
  const elapsed = Math.max(0, now - date.getTime());
  if (elapsed < 24 * 3_600_000) {
    const relative = new Intl.RelativeTimeFormat(lang, { numeric: "auto", style: "short" });
    if (elapsed < 3_600_000) return relative.format(-Math.max(1, Math.round(elapsed / 60_000)), "minute");
    return relative.format(-Math.round(elapsed / 3_600_000), "hour");
  }
  const sameYear = date.getFullYear() === new Date(now).getFullYear();
  return new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) }).format(date);
}

/** "just now", "5 min. ago", "3 hr. ago", "2 days ago" — how long ago something was read. */
export function agoLabel(seconds: number, lang: string, t: Translate, now = Date.now()): string {
  const elapsed = Math.max(0, now / 1000 - seconds);
  if (elapsed < 45) return t("ide_side_panel.git.just_now");
  const relative = new Intl.RelativeTimeFormat(lang, { numeric: "always", style: "short" });
  if (elapsed < 3600) return relative.format(-Math.max(1, Math.round(elapsed / 60)), "minute");
  if (elapsed < 86_400) return relative.format(-Math.round(elapsed / 3600), "hour");
  return relative.format(-Math.round(elapsed / 86_400), "day");
}
