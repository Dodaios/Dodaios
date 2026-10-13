import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Ellipsis, FolderGit2, Search, X } from "lucide-react";
import { fill, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { QuickTooltip } from "@/components/ui/tooltip";
import { BranchDetails } from "./BranchDetails";
import { CiBadge, commitDateLabel, PullRequestBadge } from "./gitBadges";
import { BRANCH_FILTERS, matchesFilter, matchesQuery, syncOf, type BranchFilter } from "./gitInsights";
import type { BranchEditors, BranchRow, RepoOverview } from "./gitOverviewApi";
import { ShowMore } from "./Section";
import type { GitActions } from "./useGitActions";

/** Rows drawn before "show more": a repository can hold hundreds of branches. */
const PAGE = 20;

type Translate = (key: string) => string;

interface Fact {
  id: string;
  text: string;
  tone?: string;
  tip?: string;
}

/** The row's second line: when it last changed and what, if anything, is off. */
function factsOf(t: Translate, row: BranchRow, lang: string): Fact[] {
  const facts: Fact[] = [];
  if (row.committed_at) {
    const full = new Intl.DateTimeFormat(lang, { dateStyle: "medium", timeStyle: "short" }).format(new Date(row.committed_at * 1000));
    facts.push({ id: "date", text: commitDateLabel(row.committed_at, lang), tip: fill(t("ide_side_panel.git.last_commit"), { date: full }) });
  }
  const merged = row.merged_into[0];
  if (merged) {
    const tip =
      merged.via === "pull_request"
        ? fill(t("ide_side_panel.git.merged_pr"), { target: merged.target, number: merged.number ?? "" })
        : fill(t("ide_side_panel.git.merged_git"), { target: merged.target });
    facts.push({ id: "merged", text: fill(t("ide_side_panel.git.merged_short"), { target: merged.target }), tone: "text-[hsl(var(--gh-merged))]", tip });
  }
  const sync = syncOf(row);
  if (row.ahead > 0) {
    facts.push({ id: "push", text: fill(t("ide_side_panel.git.row.to_push"), { n: row.ahead }), tone: "text-warning", tip: t("ide_side_panel.git.row.to_push_tip") });
  }
  if (row.behind > 0) {
    facts.push({ id: "pull", text: fill(t("ide_side_panel.git.row.to_pull"), { n: row.behind }), tone: "text-info", tip: t("ide_side_panel.git.row.to_pull_tip") });
  } else if (row.unfetched) {
    facts.push({ id: "pull", text: t("ide_side_panel.git.row.unfetched"), tone: "text-info", tip: t("ide_side_panel.git.row.unfetched_tip") });
  }
  if (sync === "unpublished" && !merged) {
    facts.push({ id: "local", text: t("ide_side_panel.git.local_only"), tone: "text-warning", tip: t("ide_side_panel.git.local_only_tip") });
  }
  if (sync === "gone" && !merged) {
    facts.push({ id: "gone", text: t("ide_side_panel.git.row.gone"), tip: t("ide_side_panel.git.row.gone_tip") });
  }
  return facts;
}

function BranchLine({
  row,
  overview,
  workspaceId,
  editors,
  actions,
  menuOpen,
  onMenu,
  expanded,
  onToggle,
}: {
  row: BranchRow;
  overview: RepoOverview;
  workspaceId: string;
  editors: BranchEditors | null;
  actions: GitActions;
  menuOpen: boolean;
  onMenu: (row: BranchRow, x: number, y: number) => void;
  expanded: boolean;
  onToggle: () => void;
}) {
  const t = useT();
  const lang = useRunLocale();
  const isDefault = !row.remote_only && row.name === overview.default_branch;
  const facts = factsOf(t, row, lang);
  return (
    <li
      data-testid="git-branch-row"
      data-branch={row.name}
      data-current={row.current || undefined}
      data-expanded={expanded || undefined}
      data-sync={syncOf(row)}
      onContextMenu={(event) => {
        event.preventDefault();
        onMenu(row, event.clientX, event.clientY);
      }}
      className={cn("relative", expanded && "bg-secondary/30")}
    >
      {row.current && <span className="absolute inset-y-0 left-0 w-0.5 bg-accent" aria-hidden />}
      <div className={cn("group/row flex min-h-[38px] items-center gap-0.5 pl-3 pr-1 hover:bg-secondary/40", menuOpen && "bg-secondary/60")}>
        <button
          type="button"
          data-testid="git-branch-toggle"
          aria-expanded={expanded}
          onClick={onToggle}
          className="flex min-w-0 flex-1 flex-col py-1 text-left leading-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        >
          <span className="flex min-w-0 items-center gap-1.5">
            <span className={cn("truncate font-mono text-[12.5px] text-foreground", row.current && "font-semibold")}>{row.name}</span>
            {row.current && (
              <span data-testid="git-current-tag" className="shrink-0 rounded bg-accent/15 px-1 text-[9.5px] font-medium uppercase tracking-wide text-accent">
                {t("ide_side_panel.git.row.current")}
              </span>
            )}
            {isDefault && (
              <span className="shrink-0 rounded border border-border px-1 text-[9.5px] uppercase tracking-wide text-muted-foreground">
                {t("ide_side_panel.git.default_badge")}
              </span>
            )}
          </span>
          <span className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[10.5px] text-muted-foreground">
            {facts.map((fact, index) => (
              <QuickTooltip key={fact.id} content={fact.tip ?? fact.text} side="bottom" className="inline-flex min-w-0 shrink-0 items-center gap-1.5 last:shrink">
                {index > 0 && <span className="text-muted-foreground/50" aria-hidden>·</span>}
                <span data-testid={`git-fact-${fact.id}`} className={cn("truncate tabular-nums", fact.tone)}>
                  {fact.text}
                </span>
              </QuickTooltip>
            ))}
            {row.worktree && (
              <QuickTooltip content={fill(t("ide_side_panel.git.in_worktree"), { path: row.worktree })} side="bottom" className="inline-flex shrink-0">
                <FolderGit2 data-testid="git-worktree" className="h-3 w-3" aria-label={t("ide_side_panel.git.worktree_badge")} />
              </QuickTooltip>
            )}
          </span>
        </button>
        <PullRequestBadge prs={row.pull_requests} />
        <CiBadge ci={row.ci} stale={row.ci_stale} />
        <QuickTooltip content={t("ide_side_panel.git.more")} side="bottom" className="inline-flex shrink-0">
          <button
            type="button"
            data-testid="git-branch-more"
            data-branch-menu-anchor
            aria-label={fill(t("ide_side_panel.git.menu.aria"), { branch: row.name })}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={(event) => {
              const rect = event.currentTarget.getBoundingClientRect();
              onMenu(row, rect.right - 264, rect.bottom + 4);
            }}
            className={cn(
              "inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground opacity-0 hover:bg-secondary hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover/row:opacity-100",
              menuOpen && "bg-secondary text-foreground opacity-100",
            )}
          >
            <Ellipsis className="h-4 w-4" aria-hidden />
          </button>
        </QuickTooltip>
        <ChevronDown
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground/70 transition-transform motion-reduce:transition-none", expanded && "rotate-180")}
          aria-hidden
        />
      </div>
      {expanded && (
        <BranchDetails
          row={row}
          repoUrl={overview.github.repo_url}
          defaultBranch={overview.default_branch}
          baseRef={overview.base_ref ?? ""}
          githubReady={overview.github.available}
          workspaceId={workspaceId}
          editors={editors}
          actions={actions}
        />
      )}
    </li>
  );
}

/**
 * Every branch, the checked-out one first and the rest by last change: search
 * by name or pull request, narrow to what needs pushing, pulling or fixing.
 * Branches that exist only on GitHub sit in their own folded group.
 */
export function BranchList({
  overview,
  workspaceId,
  editors,
  actions,
  filter,
  onFilter,
  menuBranch,
  onMenu,
}: {
  overview: RepoOverview;
  workspaceId: string;
  editors: BranchEditors | null;
  actions: GitActions;
  filter: BranchFilter;
  onFilter: (value: BranchFilter) => void;
  /** The row whose menu is open ("" when none). */
  menuBranch: string;
  onMenu: (row: BranchRow, x: number, y: number) => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const [showRemote, setShowRemote] = useState(false);
  const [remoteLimit, setRemoteLimit] = useState(PAGE);
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(() => new Set());
  useEffect(() => {
    setQuery("");
    setExpanded(new Set());
    setShowRemote(false);
  }, [workspaceId]);
  // A new question starts at the top of its answer.
  useEffect(() => {
    setLimit(PAGE);
    setRemoteLimit(PAGE);
  }, [filter, query, workspaceId]);

  const trimmed = query.trim();
  const all = useMemo(() => [...overview.branches, ...overview.remote_branches], [overview]);
  const counts = useMemo(() => {
    const result = {} as Record<BranchFilter, number>;
    for (const value of BRANCH_FILTERS) {
      result[value] = all.filter((row) => matchesFilter(row, value) && matchesQuery(row, trimmed)).length;
    }
    return result;
  }, [all, trimmed]);
  const narrowed = filter !== "all" || trimmed !== "";
  const visible = (rows: BranchRow[]) => rows.filter((row) => matchesFilter(row, filter) && matchesQuery(row, trimmed));
  const local = visible(overview.branches);
  const remote = visible(overview.remote_branches);
  const remoteOpen = showRemote || narrowed;
  const toggle = (key: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  const line = (row: BranchRow, key: string) => (
    <BranchLine
      key={key}
      row={row}
      overview={overview}
      workspaceId={workspaceId}
      editors={editors}
      actions={actions}
      menuOpen={menuBranch === key}
      onMenu={onMenu}
      expanded={expanded.has(key)}
      onToggle={() => toggle(key)}
    />
  );

  return (
    <div data-testid="git-branches">
      <div data-testid="git-filter-bar" className="space-y-1.5 px-3 pb-2">
        <label className="flex h-7 items-center gap-1.5 rounded-md border border-border/70 bg-background px-2 focus-within:ring-2 focus-within:ring-ring">
          <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          <input
            data-testid="git-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && query) {
                event.stopPropagation();
                setQuery("");
              }
            }}
            placeholder={t("ide_side_panel.git.search")}
            aria-label={t("ide_side_panel.git.search")}
            className="min-w-0 flex-1 bg-transparent text-[12px] text-foreground outline-none placeholder:text-muted-foreground"
          />
          {query && (
            <button
              type="button"
              aria-label={t("ide_side_panel.git.search_clear")}
              onClick={() => setQuery("")}
              className="inline-flex h-4 w-4 items-center justify-center rounded text-muted-foreground hover:text-foreground"
            >
              <X className="h-3 w-3" aria-hidden />
            </button>
          )}
        </label>
        <div role="group" aria-label={t("ide_side_panel.git.filter_aria")} className="flex flex-wrap gap-x-3 gap-y-1">
          {BRANCH_FILTERS.filter((value) => value === "all" || value === filter || counts[value] > 0).map((value) => (
            <button
              key={value}
              type="button"
              data-testid={`git-filter-${value}`}
              aria-pressed={filter === value}
              onClick={() => onFilter(value)}
              className={cn(
                "inline-flex h-5 items-center gap-1 border-b-2 text-[11px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                filter === value ? "border-accent text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`ide_side_panel.git.filter.${value}`)}
              <span className="tabular-nums text-muted-foreground/70">{counts[value]}</span>
            </button>
          ))}
        </div>
      </div>

      <ul aria-label={t("ide_side_panel.git.branches")}>{local.slice(0, limit).map((row) => line(row, row.name))}</ul>
      {local.length > limit && (
        <ShowMore
          testId="git-branches-more"
          label={fill(t("ide_side_panel.git.show_more"), { n: Math.min(PAGE, local.length - limit), left: local.length - limit })}
          onClick={() => setLimit((value) => value + PAGE)}
        />
      )}
      {narrowed && counts[filter] === 0 && (
        <p data-testid="git-filter-empty" className="px-4 py-6 text-center text-xs text-muted-foreground">
          {t("ide_side_panel.git.filter_empty")}
        </p>
      )}
      {overview.truncated && (
        <p className="px-3 py-2 text-[11px] text-muted-foreground">{fill(t("ide_side_panel.git.truncated"), { n: overview.branches.length })}</p>
      )}
      {remote.length > 0 && (
        <div className="border-t border-border/60">
          <button
            type="button"
            data-testid="git-remote-toggle"
            aria-expanded={remoteOpen}
            onClick={() => setShowRemote((value) => !value)}
            className="flex h-8 w-full items-center gap-1 pl-2 text-left text-[10.5px] font-semibold uppercase tracking-wider text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          >
            <ChevronRight className={cn("h-3.5 w-3.5 transition-transform motion-reduce:transition-none", remoteOpen && "rotate-90")} aria-hidden />
            {fill(t("ide_side_panel.git.remote_only"), { n: remote.length })}
          </button>
          {remoteOpen && (
            <>
              <ul aria-label={fill(t("ide_side_panel.git.remote_only"), { n: remote.length })}>
                {remote.slice(0, remoteLimit).map((row) => line(row, `remote:${row.name}`))}
              </ul>
              {remote.length > remoteLimit && (
                <ShowMore
                  testId="git-remote-more"
                  label={fill(t("ide_side_panel.git.show_more"), { n: Math.min(PAGE, remote.length - remoteLimit), left: remote.length - remoteLimit })}
                  onClick={() => setRemoteLimit((value) => value + PAGE)}
                />
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
