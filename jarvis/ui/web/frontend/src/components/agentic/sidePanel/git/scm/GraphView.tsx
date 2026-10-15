import { memo, useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { ArrowDown, ArrowUp, ChevronDown, Cloud, GitBranch, Loader2, Tag } from "lucide-react";
import { useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { QuickTooltip } from "@/components/ui/tooltip";
import { useEventStore } from "@/store/events";
import { FileTypeIcon } from "../../explorer/FileTypeIcon";
import { agoLabel } from "../gitBadges";
import { scmApi, type CommitDetails, type GraphCommit, type GraphPage, type GraphScope } from "./scmApi";
import { baseName, dirName, laneColor, layoutGraph, letterTone, parseRefs, type GraphRow, type RefBadge } from "./scmModel";
import { ScmMenu, type MenuItem } from "./ScmMenu";
import type { ScmCommands } from "./useScm";
import type { DiffSource } from "./DiffDialog";

const ROW = 22;
const LANE = 11;
const PAGE = 50;

function laneX(lane: number) {
  return LANE / 2 + 2 + lane * LANE;
}

/** The lanes of one graph row: lines from above into the dot, lines from the dot down. */
const GraphLanes = memo(function GraphLanes({ row, head }: { row: GraphRow; head: boolean }) {
  const width = laneX(row.width - 1) + LANE / 2 + 2;
  const mid = ROW / 2;
  const x = laneX(row.lane);
  const paths: { d: string; color: string }[] = [];
  row.top.forEach((value, lane) => {
    if (value === null) return;
    if (value === row.commit.id) {
      const from = laneX(lane);
      paths.push({ d: from === x ? `M${x} 0 V${mid}` : `M${from} 0 C${from} ${mid * 0.8} ${x} ${mid * 0.4} ${x} ${mid}`, color: laneColor(lane === row.lane ? row.lane : lane) });
    } else {
      const lx = laneX(lane);
      // A lane passing by goes straight through, unless it was freed here and moves down.
      if (row.bottom[lane] === value) paths.push({ d: `M${lx} 0 V${ROW}`, color: laneColor(lane) });
      else {
        const target = row.bottom.indexOf(value);
        if (target >= 0) paths.push({ d: `M${lx} 0 C${lx} ${mid} ${laneX(target)} ${mid} ${laneX(target)} ${ROW}`, color: laneColor(target) });
      }
    }
  });
  if (row.bottom[row.lane] !== undefined && row.bottom[row.lane] !== null && row.commit.parents.length > 0) {
    paths.push({ d: `M${x} ${mid} V${ROW}`, color: laneColor(row.lane) });
  }
  for (const lane of row.branches) {
    const bx = laneX(lane);
    paths.push({ d: `M${x} ${mid} C${x} ${mid + mid * 0.6} ${bx} ${mid + mid * 0.2} ${bx} ${ROW}`, color: laneColor(lane) });
  }
  const merge = row.commit.parents.length > 1;
  return (
    <svg width={width} height={ROW} className="shrink-0" aria-hidden>
      {paths.map((path, index) => (
        <path key={index} d={path.d} stroke={path.color} strokeWidth={1.5} fill="none" />
      ))}
      {head ? (
        <circle cx={x} cy={mid} r={4} fill="hsl(var(--background))" stroke={laneColor(row.lane)} strokeWidth={2} />
      ) : merge ? (
        <>
          <circle cx={x} cy={mid} r={4} fill="hsl(var(--background))" stroke={laneColor(row.lane)} strokeWidth={1.5} />
          <circle cx={x} cy={mid} r={1.8} fill={laneColor(row.lane)} />
        </>
      ) : (
        <circle cx={x} cy={mid} r={3.5} fill={laneColor(row.lane)} />
      )}
    </svg>
  );
});

function RefChip({ badge, color }: { badge: RefBadge; color: string }) {
  const Icon = badge.kind === "tag" ? Tag : badge.kind === "remote" ? Cloud : GitBranch;
  return (
    <span
      data-testid="scm-graph-ref"
      data-kind={badge.kind}
      style={{ borderColor: color, color: badge.current ? "hsl(var(--background))" : color, background: badge.current ? color : "transparent" }}
      className="inline-flex h-[16px] max-w-[140px] shrink-0 items-center gap-0.5 rounded-full border px-1.5 text-[10.5px] font-medium leading-none"
    >
      <Icon className="h-2.5 w-2.5 shrink-0" aria-hidden />
      <span className="truncate">{badge.name}</span>
    </span>
  );
}

/**
 * The commit graph under the changes: the current branch with its upstream
 * (or every branch), lanes and merges drawn beside each commit, branch and
 * tag badges, commits not yet pulled or pushed marked. A click opens the
 * commit's files; a file opens its diff.
 */
export function GraphView({
  workspaceId,
  revision,
  scope,
  commands,
  onDiff,
  targetHead,
}: {
  workspaceId: string;
  /** Bumped whenever history or refs may have moved. */
  revision: string;
  scope: GraphScope;
  commands: ScmCommands;
  onDiff: (source: DiffSource) => void;
  /** Bumped to scroll the current commit into view. */
  targetHead: number;
}) {
  const t = useT();
  const lang = useRunLocale();
  const pushToast = useEventStore((state) => state.pushToast);
  const [page, setPage] = useState<GraphPage | null>(null);
  const [commits, setCommits] = useState<GraphCommit[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<Record<string, CommitDetails | "loading">>({});
  const [menu, setMenu] = useState<{ items: MenuItem[]; x: number; y: number } | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    setLoading(true);
    // Re-read as many commits as are on screen, so a refresh keeps the scroll.
    const size = Math.max(PAGE, Math.min(200, commits.length || PAGE));
    scmApi
      .graph(workspaceId, scope, 0, size, controller.signal)
      .then((answer) => {
        if (!alive) return;
        setPage(answer);
        setCommits(answer.commits);
        setError("");
      })
      .catch((err: Error) => alive && err.name !== "AbortError" && setError(err.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
      controller.abort();
    };
    // `commits.length` is read once per load on purpose.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId, scope, revision]);

  useEffect(() => setOpen({}), [workspaceId, scope]);

  const loadMore = useCallback(() => {
    if (loading || !page?.more) return;
    setLoading(true);
    scmApi
      .graph(workspaceId, scope, commits.length, PAGE)
      .then((answer) => {
        setCommits((current) => [...current, ...answer.commits]);
        setPage((current) => (current ? { ...current, more: answer.more } : answer));
      })
      .catch((err: Error) => pushToast("error", err.message))
      .finally(() => setLoading(false));
  }, [loading, page, workspaceId, scope, commits.length, pushToast]);

  const rows = useMemo(() => layoutGraph(commits), [commits]);
  const incoming = useMemo(() => new Set(page?.incoming ?? []), [page]);
  const outgoing = useMemo(() => new Set(page?.outgoing ?? []), [page]);
  const head = page?.head ?? "";

  useEffect(() => {
    if (!targetHead || !head) return;
    scroller.current?.querySelector<HTMLElement>(`[data-commit="${head}"]`)?.scrollIntoView?.({ block: "center" });
  }, [targetHead, head]);

  const toggle = (commit: GraphCommit) => {
    if (open[commit.id]) {
      setOpen((current) => {
        const next = { ...current };
        delete next[commit.id];
        return next;
      });
      return;
    }
    setOpen((current) => ({ ...current, [commit.id]: "loading" }));
    scmApi
      .commit(workspaceId, commit.id)
      .then((details) => setOpen((current) => (current[commit.id] ? { ...current, [commit.id]: details } : current)))
      .catch((err: Error) => {
        pushToast("error", err.message);
        setOpen((current) => {
          const next = { ...current };
          delete next[commit.id];
          return next;
        });
      });
  };

  const copy = (text: string) => void navigator.clipboard?.writeText(text).catch(() => pushToast("error", t("ide_side_panel.git.scm.copy_failed")));

  const commitMenu = (commit: GraphCommit): MenuItem[] => [
    { id: "checkout-detached", label: t("ide_side_panel.git.scm.checkout_detached_here"), run: () => void commands.checkoutRef(commit.id, true) },
    { id: "create-branch", label: t("ide_side_panel.git.scm.create_branch_here"), run: () => void commands.createBranch(commit.id) },
    { id: "create-tag", label: t("ide_side_panel.git.scm.create_tag_here"), run: () => void commands.createTag(commit.id) },
    { kind: "separator", id: "g1" },
    { id: "cherry-pick", label: t("ide_side_panel.git.scm.cherry_pick"), disabled: commit.id === head, run: () => void commands.cherryPick(commit.id) },
    { id: "revert", label: t("ide_side_panel.git.scm.revert_commit"), run: () => void commands.revert(commit.id) },
    { kind: "separator", id: "g2" },
    { id: "copy-id", label: t("ide_side_panel.git.scm.copy_commit_id"), run: () => copy(commit.id) },
    { id: "copy-message", label: t("ide_side_panel.git.scm.copy_commit_message"), run: () => copy(commit.subject) },
  ];

  const onContext = (commit: GraphCommit, event: MouseEvent) => {
    event.preventDefault();
    setMenu({ items: commitMenu(commit), x: event.clientX, y: event.clientY });
  };

  if (error && commits.length === 0) {
    return <p data-testid="scm-graph-error" className="px-3 py-3 text-xs text-destructive">{error}</p>;
  }
  if (!page) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" aria-hidden />
      </div>
    );
  }
  if (commits.length === 0) {
    return <p className="px-3 py-3 text-[12px] text-muted-foreground">{t("ide_side_panel.git.scm.no_commits")}</p>;
  }

  return (
    <div
      ref={scroller}
      data-testid="scm-graph"
      className="h-full overflow-y-auto"
      onScroll={(event) => {
        const element = event.currentTarget;
        if (element.scrollTop + element.clientHeight > element.scrollHeight - ROW * 6) loadMore();
      }}
    >
      {rows.map((row) => {
        const commit = row.commit;
        const badges = parseRefs(commit.refs);
        const details = open[commit.id];
        const direction = incoming.has(commit.id) ? "incoming" : outgoing.has(commit.id) ? "outgoing" : "";
        const date = new Date(commit.date * 1000);
        const tip = [
          `${commit.author} <${commit.email}>`,
          `${agoLabel(commit.date, lang, t)} (${date.toLocaleString(lang)})`,
          "",
          commit.subject,
          "",
          commit.id.slice(0, 8),
          ...(direction ? [t(`ide_side_panel.git.scm.${direction}`)] : []),
        ].join("\n");
        return (
          <div key={commit.id}>
            <div
              role="button"
              tabIndex={0}
              data-testid="scm-graph-commit"
              data-commit={commit.id}
              data-direction={direction || undefined}
              aria-expanded={Boolean(details)}
              onClick={() => toggle(commit)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggle(commit);
                }
              }}
              onContextMenu={(event) => onContext(commit, event)}
              style={{ height: ROW }}
              className="group/commit flex cursor-pointer select-none items-center gap-1 pr-2 text-[12.5px] hover:bg-secondary/70 focus-visible:outline focus-visible:outline-1 focus-visible:-outline-offset-1 focus-visible:outline-accent"
            >
              <GraphLanes row={row} head={commit.id === head} />
              <QuickTooltip content={tip} side="bottom" className="flex min-w-0 flex-1 items-center gap-1.5">
                <span className={cn("min-w-0 truncate", commit.id === head ? "font-semibold text-foreground" : "text-foreground/90", direction === "incoming" && "italic")}>
                  {commit.subject}
                </span>
                <span className="min-w-0 shrink truncate text-[11.5px] text-muted-foreground/80">{commit.author}</span>
              </QuickTooltip>
              {direction === "incoming" && <ArrowDown className="h-3 w-3 shrink-0 text-accent" aria-label={t("ide_side_panel.git.scm.incoming")} />}
              {direction === "outgoing" && <ArrowUp className="h-3 w-3 shrink-0 text-accent" aria-label={t("ide_side_panel.git.scm.outgoing")} />}
              {badges.slice(0, 3).map((badge) => (
                <RefChip key={`${badge.kind}:${badge.name}`} badge={badge} color={laneColor(row.lane)} />
              ))}
              {badges.length > 3 && <span className="shrink-0 text-[10.5px] text-muted-foreground">+{badges.length - 3}</span>}
            </div>
            {details === "loading" && (
              <div className="flex h-[22px] items-center pl-8">
                <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground motion-reduce:animate-none" aria-hidden />
              </div>
            )}
            {details && details !== "loading" && (
              <div data-testid="scm-graph-files">
                {details.message.includes("\n") && (
                  <p className="whitespace-pre-wrap break-words py-1 pl-8 pr-3 text-[11.5px] text-muted-foreground">{details.message.split("\n").slice(1).join("\n").trim()}</p>
                )}
                {details.files.map((file) => (
                  <div
                    key={file.path}
                    role="button"
                    tabIndex={0}
                    data-testid="scm-graph-file"
                    onClick={() =>
                      onDiff({
                        title: `${baseName(file.path)} (${commit.id.slice(0, 7)})`,
                        path: file.path,
                        load: () => scmApi.commitFile(workspaceId, commit.id, file.path, file.original),
                      })
                    }
                    onKeyDown={(event) => {
                      if (event.key === "Enter") event.currentTarget.click();
                    }}
                    style={{ height: ROW }}
                    className="flex cursor-pointer select-none items-center gap-1.5 pl-8 pr-2 text-[12.5px] hover:bg-secondary/70"
                  >
                    <FileTypeIcon path={file.path} className="h-4 w-4" />
                    <span className={cn("truncate", letterTone(file.letter), file.letter === "D" && "line-through")}>{baseName(file.path)}</span>
                    <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted-foreground/80">{dirName(file.path)}</span>
                    <span className={cn("w-3.5 shrink-0 text-center font-mono text-[12px] font-semibold", letterTone(file.letter))}>{file.letter}</span>
                  </div>
                ))}
                {details.stat && <p className="py-0.5 pl-8 text-[11px] text-muted-foreground">{details.stat}</p>}
              </div>
            )}
          </div>
        );
      })}
      {page.more && (
        <button type="button" data-testid="scm-graph-more" onClick={loadMore} className="flex h-[22px] w-full items-center gap-1 pl-3 text-[12px] text-accent hover:underline">
          {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" aria-hidden /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden />}
          {t("ide_side_panel.git.scm.load_more")}
        </button>
      )}
      {menu && <ScmMenu items={menu.items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
