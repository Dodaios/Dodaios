import { useState } from "react";
import { ArrowDown, ArrowUp, Check, CircleAlert, FileDiff, GitBranch, Loader2 } from "lucide-react";
import { fill, useT } from "@/i18n";
import { openExternalUrl } from "@/lib/openExternal";
import { cn } from "@/lib/utils";
import { CiBadge, plural, PullRequestBadge } from "./gitBadges";
import { checkoutOf, nextStep, type NextStep } from "./gitInsights";
import type { RepoOverview } from "./gitOverviewApi";
import type { GitActions } from "./useGitActions";

type Translate = (key: string) => string;

function SyncCell({ direction, count, known }: { direction: "push" | "pull"; count: number; known: boolean }) {
  const t = useT();
  const Icon = direction === "push" ? ArrowUp : ArrowDown;
  const active = known && count > 0;
  return (
    <div data-testid={`git-sync-${direction}`} data-count={known ? count : undefined} className="flex items-center gap-2 bg-background px-2.5 py-2">
      <Icon className={cn("h-4 w-4 shrink-0", active ? (direction === "push" ? "text-warning" : "text-info") : "text-muted-foreground/50")} aria-hidden />
      <span className={cn("text-lg font-semibold leading-none tabular-nums", active ? "text-foreground" : "text-muted-foreground/60")}>
        {known ? count : "–"}
      </span>
      <span className="min-w-0 truncate text-[11px] text-muted-foreground">{t(`ide_side_panel.git.status.to_${direction}`)}</span>
    </div>
  );
}

/** Who is ahead, in one sentence. */
function syncSentence(t: Translate, overview: RepoOverview): string {
  const checkout = checkoutOf(overview);
  const row = overview.branches.find((branch) => branch.current);
  if (checkout.detached || !checkout.branch) return t("ide_side_panel.git.status.detached");
  if (row?.upstream_gone) return t("ide_side_panel.git.status.gone");
  if (!checkout.upstream) return t(checkout.has_remote ? "ide_side_panel.git.status.unpublished" : "ide_side_panel.git.status.no_remote");
  const upstream = checkout.upstream;
  if (checkout.ahead && checkout.behind) {
    return fill(t("ide_side_panel.git.status.diverged"), { ahead: checkout.ahead, behind: checkout.behind, upstream });
  }
  if (checkout.ahead) return fill(plural(t, "ide_side_panel.git.status.ahead", checkout.ahead), { upstream });
  if (checkout.behind) return fill(plural(t, "ide_side_panel.git.status.behind", checkout.behind), { upstream });
  return fill(t("ide_side_panel.git.status.synced"), { upstream });
}

function workingTree(t: Translate, overview: RepoOverview): { clean: boolean; text: string; detail: string } {
  const checkout = checkoutOf(overview);
  if (checkout.files === 0) return { clean: true, text: t("ide_side_panel.git.status.clean"), detail: "" };
  const parts = [
    checkout.conflicted ? fill(t("ide_side_panel.git.status.n_conflicted"), { n: checkout.conflicted }) : "",
    checkout.staged ? fill(t("ide_side_panel.git.status.n_staged"), { n: checkout.staged }) : "",
    checkout.unstaged ? fill(t("ide_side_panel.git.status.n_modified"), { n: checkout.unstaged }) : "",
    checkout.untracked ? fill(t("ide_side_panel.git.status.n_untracked"), { n: checkout.untracked }) : "",
  ].filter(Boolean);
  return { clean: false, text: plural(t, "ide_side_panel.git.status.changed", checkout.files), detail: parts.join(" · ") };
}

interface StepView {
  title: string;
  reason: string;
  /** The button's label; none when there is nothing to click. */
  action: string;
  tone: "action" | "danger" | "wait" | "done";
}

function describe(t: Translate, step: NextStep, overview: RepoOverview): StepView {
  const upstream = checkoutOf(overview).upstream;
  const key = (name: string) => t(`ide_side_panel.git.next.${name}`);
  switch (step.kind) {
    case "resolve":
      return {
        title: step.operation ? fill(key("resolve_operation"), { operation: step.operation }) : key("resolve"),
        reason: step.conflicts ? plural(t, "ide_side_panel.git.next.resolve_reason", step.conflicts) : key("resolve_reason_none"),
        action: key("open_changes"),
        tone: "danger",
      };
    case "detached":
      return { title: key("detached"), reason: key("detached_reason"), action: "", tone: "wait" };
    case "fetch":
      return { title: key("fetch"), reason: key("fetch_reason"), action: key("fetch_action"), tone: "action" };
    case "pull":
      return {
        title: fill(plural(t, "ide_side_panel.git.next.pull", step.count), { upstream }),
        reason: key("pull_reason"),
        action: key("pull_action"),
        tone: "action",
      };
    case "commit":
      return { title: plural(t, "ide_side_panel.git.next.commit", step.count), reason: key("commit_reason"), action: key("commit_action"), tone: "action" };
    case "rebase":
      return {
        title: fill(key("rebase"), { upstream }),
        reason: fill(key("rebase_reason"), { ahead: step.ahead, behind: step.behind }),
        action: key("rebase_action"),
        tone: "action",
      };
    case "publish":
      return { title: key("publish"), reason: key("publish_reason"), action: key("publish_action"), tone: "action" };
    case "push":
      return { title: fill(plural(t, "ide_side_panel.git.next.push", step.count), { upstream }), reason: key("push_reason"), action: key("push_action"), tone: "action" };
    case "open_pr":
      return {
        title: key("open_pr"),
        reason: fill(key("open_pr_reason"), { base: overview.default_branch }),
        action: key("open_pr_action"),
        tone: "action",
      };
    case "fix_ci":
      return {
        title: step.number ? fill(key("fix_ci_pr"), { number: step.number }) : key("fix_ci"),
        reason: step.names.length ? fill(key("fix_ci_reason"), { names: step.names.join(", ") }) : key("fix_ci_reason_none"),
        action: step.url ? key("view_checks") : "",
        tone: "danger",
      };
    case "fix_conflict":
      return { title: fill(key("fix_conflict"), { number: step.pr.number }), reason: fill(key("fix_conflict_reason"), { base: step.pr.base }), action: key("view_pr"), tone: "danger" };
    case "changes_requested":
      return { title: fill(key("changes_requested"), { number: step.pr.number }), reason: key("changes_requested_reason"), action: key("view_pr"), tone: "danger" };
    case "wait_queue":
      return { title: fill(key("wait_queue"), { number: step.pr.number }), reason: key("wait_queue_reason"), action: key("view_pr"), tone: "wait" };
    case "wait_ci":
      return { title: key("wait_ci"), reason: key("wait_ci_reason"), action: step.url ? key("view_checks") : "", tone: "wait" };
    case "ready":
      return { title: fill(key("ready"), { number: step.pr.number }), reason: key("ready_reason"), action: key("view_pr"), tone: "done" };
    default:
      return { title: key("done"), reason: key("done_reason"), action: "", tone: "done" };
  }
}

function busyKey(step: NextStep): string {
  if (step.kind === "pull" || step.kind === "rebase") return "pull";
  if (step.kind === "push" || step.kind === "publish") return "push:";
  if (step.kind === "open_pr") return "pr:";
  return step.kind;
}

/**
 * The top of the Git tab: the checkout the person is in — who is ahead, what
 * is uncommitted, how its pull request and CI stand — and the one next step,
 * as a button.
 */
export function StatusPanel({
  overview,
  actions,
  onOpenChanges,
}: {
  overview: RepoOverview;
  actions: GitActions;
  onOpenChanges: () => void;
}) {
  const t = useT();
  const checkout = checkoutOf(overview);
  const row = overview.branches.find((branch) => branch.current);
  const step = nextStep(overview);
  const view = describe(t, step, overview);
  const tree = workingTree(t, overview);
  const [composing, setComposing] = useState(false);
  const [message, setMessage] = useState("");
  const tracking = Boolean(checkout.upstream) && !row?.upstream_gone && !checkout.detached;
  const working = actions.busy !== "" && actions.busy === busyKey(step);

  const act = () => {
    switch (step.kind) {
      case "resolve":
        return onOpenChanges();
      case "fetch":
        return void actions.fetch();
      case "pull":
        return actions.pull();
      case "rebase":
        return actions.rebase();
      case "commit":
        return setComposing(true);
      case "publish":
      case "push":
        return actions.push();
      case "open_pr":
        return actions.createPullRequest();
      case "fix_ci":
      case "wait_ci":
        return void openExternalUrl(step.url);
      case "fix_conflict":
      case "changes_requested":
      case "wait_queue":
      case "ready":
        return void openExternalUrl(step.pr.url);
      default:
        return undefined;
    }
  };
  // What else is possible right now, beside the one next step.
  const extras: { id: string; label: string; run: () => void }[] = [];
  if (checkout.files > 0 && step.kind !== "commit" && step.kind !== "resolve" && !checkout.detached) {
    extras.push({ id: "commit", label: t("ide_side_panel.git.next.commit_action"), run: () => setComposing(true) });
  }
  if (tracking && checkout.behind > 0 && step.kind !== "pull" && step.kind !== "rebase" && step.kind !== "resolve") {
    extras.push({ id: "pull", label: t("ide_side_panel.git.next.pull_action"), run: actions.pull });
  }
  if (tracking && checkout.ahead > 0 && checkout.behind === 0 && step.kind !== "push" && step.kind !== "resolve") {
    extras.push({ id: "push", label: t("ide_side_panel.git.next.push_action"), run: () => actions.push() });
  }
  const commit = async () => {
    if (!message.trim()) return;
    if (await actions.commit(message.trim())) {
      setMessage("");
      setComposing(false);
    }
  };

  return (
    <section data-testid="git-status" aria-label={t("ide_side_panel.git.status.aria")} className="shrink-0 border-b border-border/60 px-3 pb-3 pt-2.5">
      <div className="flex min-h-6 items-center gap-1.5">
        <GitBranch className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        <span data-testid="git-current-branch" className="min-w-0 truncate font-mono text-[13px] font-semibold text-foreground">
          {checkout.detached || !checkout.branch ? overview.head.slice(0, 7) : checkout.branch}
        </span>
        {checkout.branch === overview.default_branch && checkout.branch !== "" && (
          <span className="shrink-0 rounded border border-border px-1 text-[9.5px] uppercase tracking-wide text-muted-foreground">
            {t("ide_side_panel.git.default_badge")}
          </span>
        )}
        <span className="ml-auto flex shrink-0 items-center">
          {row && <PullRequestBadge prs={row.pull_requests} />}
          {row && <CiBadge ci={row.ci} stale={row.ci_stale} />}
        </span>
      </div>

      <div
        data-testid="git-sync"
        className="mt-2 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border/70 bg-border/70"
      >
        <SyncCell direction="push" count={checkout.ahead} known={tracking} />
        <SyncCell direction="pull" count={checkout.behind} known={tracking} />
      </div>
      <p data-testid="git-sync-sentence" className="mt-1.5 text-[11.5px] leading-snug text-muted-foreground">
        {syncSentence(t, overview)}
        {row?.unfetched && <span className="text-info"> {t("ide_side_panel.git.status.unfetched")}</span>}
      </p>

      {overview.checkout && (
        <p data-testid="git-working-tree" data-clean={tree.clean || undefined} className="mt-1.5 flex min-w-0 items-center gap-1.5 text-[11.5px]">
          {tree.clean ? (
            <Check className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden />
          ) : (
            <FileDiff className={cn("h-3.5 w-3.5 shrink-0", checkout.conflicted ? "text-destructive" : "text-warning")} aria-hidden />
          )}
          <span className={cn("shrink-0", tree.clean ? "text-muted-foreground" : "text-foreground")}>{tree.text}</span>
          {tree.detail && <span className="min-w-0 truncate text-muted-foreground">{tree.detail}</span>}
          {!tree.clean && (
            <button
              type="button"
              data-testid="git-review-changes"
              onClick={onOpenChanges}
              className="ml-auto shrink-0 rounded px-1 text-[11px] text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("ide_side_panel.git.status.review")}
            </button>
          )}
        </p>
      )}

      {composing ? (
        <div data-testid="git-commit-form" className="mt-2.5 space-y-1.5 rounded-lg border border-border/70 bg-secondary/40 p-2">
          <textarea
            data-testid="git-commit-message"
            autoFocus
            rows={2}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void commit();
              if (event.key === "Escape") {
                event.stopPropagation();
                setComposing(false);
              }
            }}
            placeholder={t("ide_side_panel.git.commit.placeholder")}
            aria-label={t("ide_side_panel.git.commit.placeholder")}
            className="w-full resize-none rounded-md border border-border/70 bg-background px-2 py-1.5 text-[12px] text-foreground outline-none placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring"
          />
          <p className="text-[10.5px] leading-snug text-muted-foreground">{plural(t, "ide_side_panel.git.commit.scope", checkout.files)}</p>
          <div className="flex justify-end gap-1.5">
            <button
              type="button"
              onClick={() => setComposing(false)}
              className="h-7 rounded-md px-2.5 text-[11.5px] text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              {t("ide_side_panel.git.confirm.cancel")}
            </button>
            <button
              type="button"
              data-testid="git-commit-submit"
              disabled={!message.trim() || actions.busy !== ""}
              onClick={() => void commit()}
              className="inline-flex h-7 items-center gap-1.5 rounded-md bg-primary px-2.5 text-[11.5px] font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              {actions.busy === "commit" && <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />}
              {t("ide_side_panel.git.commit.submit")}
            </button>
          </div>
        </div>
      ) : (
        <div
          data-testid="git-next"
          data-step={step.kind}
          className={cn(
            "mt-2.5 flex items-center gap-2 rounded-lg border px-2.5 py-2",
            view.tone === "danger" ? "border-destructive/30 bg-destructive/5" : "border-border/70 bg-secondary/40",
          )}
        >
          {view.tone === "done" ? (
            <Check className="h-4 w-4 shrink-0 text-success" aria-hidden />
          ) : view.tone === "danger" ? (
            <CircleAlert className="h-4 w-4 shrink-0 text-destructive" aria-hidden />
          ) : null}
          <div className="min-w-0 flex-1">
            {view.tone !== "done" && (
              <p className="text-[9.5px] font-semibold uppercase tracking-wider text-muted-foreground">{t("ide_side_panel.git.next.label")}</p>
            )}
            <p className="break-words text-[12.5px] font-medium leading-snug text-foreground">{view.title}</p>
            <p className="break-words text-[11px] leading-snug text-muted-foreground">{view.reason}</p>
          </div>
          {view.action && (
            <button
              type="button"
              data-testid="git-next-action"
              disabled={actions.busy !== ""}
              onClick={act}
              className={cn(
                "inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-[11.5px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                view.tone === "action"
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "border border-border-strong text-foreground hover:bg-secondary",
              )}
            >
              {working && <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden />}
              {view.action}
            </button>
          )}
        </div>
      )}
      {!composing && extras.length > 0 && (
        <div data-testid="git-quick-actions" className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 px-0.5 text-[11px]">
          <span className="text-muted-foreground">{t("ide_side_panel.git.next.also")}</span>
          {extras.map((extra) => (
            <button
              key={extra.id}
              type="button"
              data-testid={`git-quick-${extra.id}`}
              disabled={actions.busy !== ""}
              onClick={extra.run}
              className="rounded text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              {extra.label}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
