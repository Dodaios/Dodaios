import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { GitHubIcon, type GitHubIconName } from "../GitHubIcon";
import { useThreadGitHub, type SessionGitHubStatus } from "../useSessionGitHub";
import { PULL_REQUEST_TONE } from "../pullRequestTone";

type PullRequestState = Exclude<SessionGitHubStatus["state"], "branch">;

/** GitHub's own symbol and colour for each pull request state. */
const LOOK: Record<PullRequestState, { icon: GitHubIconName; tone: string; label: string }> = {
  open: { icon: "git-pull-request", tone: PULL_REQUEST_TONE.open, label: "ide_panes.github.state_open" },
  draft: { icon: "git-pull-request-draft", tone: PULL_REQUEST_TONE.draft, label: "ide_panes.github.state_draft" },
  queued: { icon: "git-merge-queue", tone: PULL_REQUEST_TONE.queued, label: "ide_panes.github.state_queued" },
  merged: { icon: "git-merge", tone: PULL_REQUEST_TONE.merged, label: "ide_panes.github.state_merged" },
  closed: { icon: "git-pull-request-closed", tone: PULL_REQUEST_TONE.closed, label: "ide_panes.github.state_closed" },
};

/** Which pull request a row's symbol stands for: work still open before finished work. */
const RANK: Record<PullRequestState, number> = { queued: 0, open: 1, draft: 2, merged: 3, closed: 4 };

export interface ThreadPullRequest {
  number: number;
  state: PullRequestState;
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
    out.push({ number: row.number, state: row.state });
  }
  return out.sort((a, b) => RANK[a.state] - RANK[b.state] || b.number - a.number);
}

/**
 * The pull request mark at the end of a thread row: GitHub's symbol in
 * GitHub's colour for the thread's most pressing pull request, and how many
 * it has when there are several. Nothing while the thread has none.
 */
export function ThreadPullRequests({ sessionId }: { sessionId: string }) {
  const t = useT();
  const { status } = useThreadGitHub(sessionId);
  const requests = pullRequestsOf(status);
  if (requests.length === 0) return null;
  const lead = LOOK[requests[0].state];
  const summary = requests.map((request) => `#${request.number} · ${t(LOOK[request.state].label)}`).join("\n");
  return <span role="img" aria-label={summary} title={summary} data-testid={`thread-prs-${sessionId}`}
    className={cn("flex shrink-0 items-center gap-0.5 text-xs tabular-nums", lead.tone)}>
    <GitHubIcon name={lead.icon} width={14} height={14} className="shrink-0" />
    {requests.length > 1 && <span>{requests.length}</span>}
  </span>;
}
