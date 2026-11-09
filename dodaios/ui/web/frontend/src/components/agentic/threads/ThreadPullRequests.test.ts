import { describe, expect, it } from "vitest";
import type { SessionGitHubStatus } from "../useSessionGitHub";
import { pullRequestsOf } from "./ThreadPullRequests";

function branch(number: number | null, state: SessionGitHubStatus["state"], extra: Partial<SessionGitHubStatus> = {}): SessionGitHubStatus {
  return {
    repo: "acme/app", branch: `b${number}`, url: "", published: true, owned: true, available: true, reason: "",
    fetched_at: 0, state, number, ci: { state: "none" } as SessionGitHubStatus["ci"], ci_stale: false, ...extra,
  };
}

describe("pullRequestsOf", () => {
  it("lists every pull request once, open work before merged and closed", () => {
    const status = branch(10, "merged", { others: [branch(12, "open"), branch(11, "closed"), branch(12, "open")] });
    expect(pullRequestsOf(status)).toEqual([
      { number: 12, state: "open" }, { number: 10, state: "merged" }, { number: 11, state: "closed" },
    ]);
  });

  it("leaves out plain branches, unpublished work and someone else's branch", () => {
    const status = branch(null, "branch", {
      others: [branch(5, "open", { published: false }), branch(6, "open", { owned: false }), branch(7, "draft")],
    });
    expect(pullRequestsOf(status)).toEqual([{ number: 7, state: "draft" }]);
    expect(pullRequestsOf(null)).toEqual([]);
  });
});
