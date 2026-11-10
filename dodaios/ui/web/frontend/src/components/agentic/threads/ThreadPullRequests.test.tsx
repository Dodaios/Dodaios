import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionGitHubStatus } from "../useSessionGitHub";
import { ThreadPullRequests, pullRequestsOf } from "./ThreadPullRequests";

const github = vi.hoisted(() => ({ status: null as SessionGitHubStatus | null }));
vi.mock("../useSessionGitHub", () => ({ useThreadGitHub: () => ({ status: github.status, pending: false }) }));
const opened = vi.hoisted(() => vi.fn());
vi.mock("@/components/agentic/sidePanel/browser/ideBrowserLinks", () => ({ openLinkInIdeBrowser: opened }));

afterEach(() => { cleanup(); vi.clearAllMocks(); github.status = null; });

function branch(number: number | null, state: SessionGitHubStatus["state"], extra: Partial<SessionGitHubStatus> = {}): SessionGitHubStatus {
  return {
    repo: "acme/app", branch: `b${number}`, url: number ? `https://github.com/acme/app/pull/${number}` : "",
    published: true, owned: true, available: true, reason: "",
    fetched_at: 0, state, number, ci: { state: "none" } as SessionGitHubStatus["ci"], ci_stale: false, ...extra,
  };
}

describe("pullRequestsOf", () => {
  it("lists every pull request once, open work before merged and closed", () => {
    const status = branch(10, "merged", { others: [branch(12, "open"), branch(11, "closed"), branch(12, "open")] });
    expect(pullRequestsOf(status).map(({ number, state }) => [number, state])).toEqual([
      [12, "open"], [10, "merged"], [11, "closed"],
    ]);
  });

  it("leaves out plain branches, unpublished work and someone else's branch", () => {
    const status = branch(null, "branch", {
      others: [branch(5, "open", { published: false }), branch(6, "open", { owned: false }), branch(7, "draft")],
    });
    expect(pullRequestsOf(status).map((request) => request.number)).toEqual([7]);
    expect(pullRequestsOf(null)).toEqual([]);
  });

  it("keeps only a GitHub pull request link", () => {
    const [request] = pullRequestsOf(branch(3, "open", { url: "javascript:alert(1)" }));
    expect(request.url).toBe("");
  });
});

describe("the pull request card", () => {
  it("shows nothing for a thread without a pull request", () => {
    github.status = branch(null, "branch");
    const { container } = render(<ThreadPullRequests sessionId="s1" />);
    expect(container.innerHTML).toBe("");
  });

  it("lists every pull request on hover and opens the one clicked", () => {
    github.status = branch(1248, "merged", {
      title: "feat(permissions): choose approval modes", additions: 731, deletions: 30,
      others: [branch(1250, "open", { title: "fix: follow-up" })],
    });
    const rowClick = vi.fn();
    render(<div onClick={rowClick}><ThreadPullRequests sessionId="s1" /></div>);

    fireEvent.mouseEnter(screen.getByTestId("thread-prs-s1"));
    const card = screen.getByTestId("thread-pr-card-s1");
    expect(card.textContent).toContain("fix: follow-up");
    expect(card.textContent).toContain("feat(permissions): choose approval modes");
    expect(card.textContent).toContain("acme/app #1248");
    expect(card.textContent).toContain("+731");
    expect(card.textContent).toContain("−30");

    fireEvent.click(screen.getByTestId("thread-pr-card-row-1248"));
    expect(opened).toHaveBeenCalledExactlyOnceWith("https://github.com/acme/app/pull/1248");
    expect(rowClick).not.toHaveBeenCalled();
    expect(screen.queryByTestId("thread-pr-card-s1")).toBeNull();
  });
});
