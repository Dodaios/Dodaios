import { memo, useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
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
import { Codicon, Twistie } from "./Codicon";
import type { ScmCommands } from "./useScm";
import type { DiffSource } from "./DiffDialog";

const ROW = 22;
/** A commit's files sit one level in, under its subject. */
const GRAPH_INDENT = 16;
const LANE = 11;
const PAGE = 50;

function laneX(lane: number) {
  return LANE / 2 + 2 + lane * LANE;
}

/** The lanes of one graph row: lines from above into the dot, lines from the dot down. */
const GraphLanes = memo(function GraphLanes({ row, head, lanes }: { row: GraphRow; head: boolean; lanes: number }) {
  // Every row is as wide as the widest one, so the subjects line up.
  const width = laneX(Math.max(lanes, row.width) - 1) + LANE / 2 + 2;
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
        <path key={index} d={path.d} stroke={path.color} strokeWidth={1} fill="none" />
      ))}
      {head ? (
        <>
          <circle cx={x} cy={mid} r={5} fill={laneColor(row.lane)} />
          <circle cx={x} cy={mid} r={3} fill="var(--scm-bg)" />
        </>
      ) : merge ? (
        <>
          <circle cx={x} cy={mid} r={4} fill="var(--scm-bg)" stroke={laneColor(row.lane)} strokeWidth={2} />
          <circle cx={x} cy={mid} r={1.5} fill={laneColor(row.lane)} />
        </>
      ) : (
        <circle cx={x} cy={mid} r={4} fill={laneColor(row.lane)} />
      )}
    </svg>
  );
});

const REF_COLOR: Record<RefBadge["kind"], string> = {
  head: "var(--scm-ref-local)",
  remote: "var(--scm-ref-remote)",
  tag: "var(--scm-ref-base)",
};
const REF_ICON: Record<RefBadge["kind"], string> = { head: "git-branch", remote: "cloud", tag: "tag" };

/** A ref on a commit: the first one with its name, every further one as its icon only. */
function RefChip({ badge, compact }: { badge: RefBadge; compact: boolean }) {
  return (
    <QuickTooltip content={badge.name} side="bottom" className="inline-flex shrink-0">
      <span
        data-testid="scm-graph-ref"
        data-kind={badge.kind}
        aria-label={badge.name}
        style={{ background: REF_COLOR[badge.kind], color: "var(--scm-ref-fg)" }}
        className={cn(
          "ml-[4px] inline-flex h-[18px] max-w-[120px] items-center gap-[2px] rounded-[9px] text-[11px] leading-[18px]",
          compact ? "w-[18px] justify-center" : "px-[5px]",
        )}
      >
        <Codicon name={badge.current ? "target" : REF_ICON[badge.kind]} className="!text-[12px] !leading-[12px]" />
        {!compact && <span className="truncate">{badge.name}</span>}
      </span>
    </QuickTooltip>
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
  const lanes = useMemo(() => Math.min(12, rows.reduce((most, row) => Math.max(most, row.width), 1)), [rows]);
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
    return (
      <p data-testid="scm-graph-error" className="px-[20px] py-[4px] text-[13px]" style={{ color: "var(--scm-deleted)" }}>
        {error}
      </p>
    );
  }
  if (!page) {
    return (
      <div className="flex items-center justify-center py-[8px]">
        <Codicon name="loading" spin />
      </div>
    );
  }
  if (commits.length === 0) {
    return <p className="px-[20px] py-[4px] text-[13px] opacity-70">{t("ide_side_panel.git.scm.no_commits")}</p>;
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
              className="scm-row flex cursor-pointer select-none items-center pr-[8px] focus-visible:outline focus-visible:outline-1 focus-visible:-outline-offset-1 focus-visible:outline-[var(--scm-focus)]"
            >
              <GraphLanes row={row} head={commit.id === head} lanes={lanes} />
              <QuickTooltip content={tip} side="bottom" className="ml-[4px] flex min-w-0 flex-1 items-baseline overflow-hidden whitespace-nowrap">
                <span className={cn("min-w-0 truncate", commit.id === head && "font-semibold")}>{commit.subject}</span>
                <span className="ml-[0.5em] min-w-0 shrink truncate text-[0.9em] opacity-70">{commit.author}</span>
              </QuickTooltip>
              {direction && (
                <QuickTooltip content={t(`ide_side_panel.git.scm.${direction}`)} side="bottom" className="inline-flex shrink-0">
                  <span aria-label={t(`ide_side_panel.git.scm.${direction}`)} className="ml-[4px] inline-flex opacity-80">
                    <Codicon name={direction === "incoming" ? "arrow-circle-down" : "arrow-circle-up"} />
                  </span>
                </QuickTooltip>
              )}
              {badges.map((badge, index) => (
                <RefChip key={`${badge.kind}:${badge.name}`} badge={badge} compact={index > 0} />
              ))}
            </div>
            {details === "loading" && (
              <div className="flex h-[22px] items-center" style={{ paddingLeft: GRAPH_INDENT + 22 }}>
                <Codicon name="loading" spin />
              </div>
            )}
            {details && details !== "loading" && (
              <div data-testid="scm-graph-files">
                {details.message.includes("\n") && (
                  <p className="whitespace-pre-wrap break-words py-[2px] pr-[12px] text-[12px] leading-[18px] opacity-70" style={{ paddingLeft: GRAPH_INDENT + 22 }}>{details.message.split("\n").slice(1).join("\n").trim()}</p>
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
                    style={{ height: ROW, paddingLeft: GRAPH_INDENT }}
                    className="scm-row flex cursor-pointer select-none items-center"
                  >
                    <Twistie visible={false} />
                    <FileTypeIcon path={file.path} className="mr-[6px] h-4 w-4" />
                    <span className={cn("truncate", letterTone(file.letter), file.letter === "D" && "line-through")}>{baseName(file.path)}</span>
                    <span className="ml-[0.5em] min-w-0 flex-1 truncate text-[0.9em] opacity-70">{dirName(file.path)}</span>
                    <span className={cn("ml-[5px] mr-[12px] w-4 shrink-0 text-center text-[12px] font-semibold opacity-90", letterTone(file.letter))}>{file.letter}</span>
                  </div>
                ))}
                {details.stat && (
                  <p className="text-[12px] leading-[22px] opacity-70" style={{ paddingLeft: GRAPH_INDENT + 22 }}>
                    {details.stat}
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
      {page.more && (
        <button type="button" data-testid="scm-graph-more" onClick={loadMore} className="scm-row flex h-[22px] w-full items-center gap-[6px] pl-[8px]" style={{ color: "var(--scm-focus)" }}>
          <Codicon name={loading ? "loading" : "fold-down"} spin={loading} />
          {t("ide_side_panel.git.scm.load_more")}
        </button>
      )}
      {menu && <ScmMenu items={menu.items} x={menu.x} y={menu.y} onClose={() => setMenu(null)} />}
    </div>
  );
}
