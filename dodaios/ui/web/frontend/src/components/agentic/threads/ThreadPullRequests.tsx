import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { openLinkInIdeBrowser } from "@/components/agentic/sidePanel/browser/ideBrowserLinks";
import { GitHubIcon, type GitHubIconName } from "../GitHubIcon";
import { useThreadGitHub, type SessionGitHubStatus } from "../useSessionGitHub";
import { PULL_REQUEST_TONE } from "../pullRequestTone";

type PullRequestState = Exclude<SessionGitHubStatus["state"], "branch">;

/** GitHub's own symbol and colour for each pull request state. */
const LOOK: Record<PullRequestState, { icon: GitHubIconName; tone: string; label: string }> = {
  open: { icon: "git-pull-request", tone: PULL_REQUEST_TONE.open, label: "ide_threads.pr_state_open" },
  draft: { icon: "git-pull-request-draft", tone: PULL_REQUEST_TONE.draft, label: "ide_threads.pr_state_draft" },
  queued: { icon: "git-merge-queue", tone: PULL_REQUEST_TONE.queued, label: "ide_threads.pr_state_queued" },
  merged: { icon: "git-merge", tone: PULL_REQUEST_TONE.merged, label: "ide_threads.pr_state_merged" },
  closed: { icon: "git-pull-request-closed", tone: PULL_REQUEST_TONE.closed, label: "ide_threads.pr_state_closed" },
};

/** Which pull request a row's symbol stands for: work still open before finished work. */
const RANK: Record<PullRequestState, number> = { queued: 0, open: 1, draft: 2, merged: 3, closed: 4 };

/** Only a GitHub pull request link is opened from the card. */
const PULL_URL = /^https:\/\/github\.com\/[A-Za-z0-9][A-Za-z0-9-]*\/[A-Za-z0-9._-]+\/pull\/[1-9]\d*$/;

/** How long the card stays while the pointer travels from the symbol to it. */
const CLOSE_DELAY_MS = 150;
const CARD_WIDTH = 360;

export interface ThreadPullRequest {
  number: number;
  state: PullRequestState;
  repo: string;
  url: string;
  title: string;
  additions: number;
  deletions: number;
}

/** The pull requests a thread's coding agent opened, most pressing first. */
export function pullRequestsOf(status: SessionGitHubStatus | null): ThreadPullRequest[] {
  if (!status) return [];
  const seen = new Set<number>();
  const out: ThreadPullRequest[] = [];
  for (const row of [status, ...(status.others ?? [])]) {
    if (!row.owned || !row.published || row.number === null || row.state === "branch" || !(row.state in LOOK)) continue;
    if (seen.has(row.number)) continue;
    seen.add(row.number);
    out.push({
      number: row.number, state: row.state, repo: row.repo,
      url: PULL_URL.test(row.url) ? row.url : "",
      title: row.title ?? "", additions: row.additions ?? 0, deletions: row.deletions ?? 0,
    });
  }
  return out.sort((a, b) => RANK[a.state] - RANK[b.state] || b.number - a.number);
}

/** One pull request in the card: its title, then state, repository and size. */
function PullRequestRow({ request, onOpen }: { request: ThreadPullRequest; onOpen: (url: string) => void }) {
  const t = useT();
  const look = LOOK[request.state];
  const sized = request.additions > 0 || request.deletions > 0;
  return <button type="button" role="menuitem" disabled={!request.url}
    data-testid={`thread-pr-card-row-${request.number}`}
    title={request.url || undefined}
    onClick={(event) => { event.stopPropagation(); if (request.url) onOpen(request.url); }}
    className="flex w-full min-w-0 flex-col gap-0.5 rounded-md px-2.5 py-1.5 text-left transition-colors hover:bg-muted focus-visible:bg-muted focus-visible:outline-none disabled:cursor-default">
    <span className="w-full truncate text-sm text-foreground">{request.title || `#${request.number}`}</span>
    <span className="flex w-full min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
      <GitHubIcon name={look.icon} width={12} height={12} className={cn("shrink-0", look.tone)} />
      <span className={cn("shrink-0", look.tone)}>{t(look.label)}</span>
      <span aria-hidden>·</span>
      <span className="min-w-0 truncate">{request.repo} #{request.number}</span>
      {sized && <span className="ml-auto shrink-0 tabular-nums">
        <span className="text-[#1a7f37] dark:text-[#3fb950]">+{request.additions}</span>{" "}
        <span className="text-[#cf222e] dark:text-[#f85149]">−{request.deletions}</span>
      </span>}
    </span>
  </button>;
}

/**
 * The pull request mark at the end of a thread row: GitHub's symbol in
 * GitHub's colour for the thread's most pressing pull request, and how many
 * it has when there are several. Hovering it opens a card listing each pull
 * request; a click on one opens it. Nothing while the thread has none.
 */
export function ThreadPullRequests({ sessionId }: { sessionId: string }) {
  const t = useT();
  const { status } = useThreadGitHub(sessionId);
  const requests = pullRequestsOf(status);
  const anchor = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    if (!position) return;
    const close = () => setPosition(null);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    window.addEventListener("blur", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
      window.removeEventListener("blur", close);
    };
  }, [position]);

  if (requests.length === 0) return null;
  const lead = LOOK[requests[0].state];

  const show = () => {
    clearTimeout(timer.current);
    const rect = anchor.current?.getBoundingClientRect();
    if (!rect) return;
    const left = Math.max(8, Math.min(rect.right + 8, window.innerWidth - CARD_WIDTH - 8));
    setPosition({ left, top: Math.max(8, rect.top - 8) });
  };
  const hide = () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setPosition(null), CLOSE_DELAY_MS);
  };
  const open = (url: string) => {
    setPosition(null);
    // WebView2 drops target=_blank: the IDE's Browser tab opens it.
    void openLinkInIdeBrowser(url);
  };

  return <>
    <span ref={anchor} role="img" aria-label={requests.map((request) => `#${request.number} · ${t(LOOK[request.state].label)}`).join(", ")}
      data-testid={`thread-prs-${sessionId}`} onMouseEnter={show} onMouseLeave={hide}
      className={cn("flex shrink-0 items-center gap-1 text-sm font-medium tabular-nums", lead.tone)}>
      <GitHubIcon name={lead.icon} width={16} height={16} className="shrink-0" />
      {requests.length > 1 && <span>{requests.length}</span>}
    </span>
    {position && createPortal(<div role="menu" aria-label={t("ide_threads.pull_requests")}
      data-testid={`thread-pr-card-${sessionId}`}
      onMouseEnter={() => clearTimeout(timer.current)} onMouseLeave={hide}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      style={{ left: position.left, top: position.top, width: CARD_WIDTH }}
      className="fixed z-[90] max-w-[calc(100vw-16px)] rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg">
      {requests.map((request) => <PullRequestRow key={request.number} request={request} onOpen={open} />)}
    </div>, document.body)}
  </>;
}
