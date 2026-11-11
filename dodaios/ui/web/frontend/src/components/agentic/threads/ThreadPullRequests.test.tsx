import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionGitHubStatus } from "../useSessionGitHub";
import { ThreadPullRequests, cardPosition, pullRequestsOf } from "./ThreadPullRequests";

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

describe("cardPosition", () => {
  const mark = { left: 450, right: 478, top: 692, bottom: 710 };

  it("hangs the card under the symbol, right edges together, clear of the row's own end", () => {
    expect(cardPosition(mark, 3, 2560, 1392)).toEqual({ left: 118, top: 716 });
  });

  it("stays inside the window beside a narrow list", () => {
    expect(cardPosition({ ...mark, left: 180, right: 208 }, 3, 2560, 1392)).toEqual({ left: 8, top: 716 });
  });

  it("stands on the symbol where it would run out of the window below", () => {
    expect(cardPosition({ ...mark, top: 1340, bottom: 1358 }, 3, 2560, 1392)).toEqual({ left: 118, bottom: 58 });
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
    // No native tooltip comes up over the card.
    expect(card.querySelector("[title]")).toBeNull();

    fireEvent.click(screen.getByTestId("thread-pr-card-row-1248"));
    expect(opened).toHaveBeenCalledExactlyOnceWith("https://github.com/acme/app/pull/1248");
    expect(rowClick).not.toHaveBeenCalled();
    expect(screen.queryByTestId("thread-pr-card-s1")).toBeNull();
  });
});
