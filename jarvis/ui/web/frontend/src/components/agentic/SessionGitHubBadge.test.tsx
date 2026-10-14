import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { openExternalUrl } from "@/lib/openExternal";
import { GitHubStatusBadge } from "./SessionGitHubBadge";
import type { SessionGitHubStatus } from "./useSessionGitHub";
import { PANE_BRAND, PANE_CHROME } from "./terminalThemes";

vi.mock("@/lib/openExternal", () => ({ openExternalUrl: vi.fn().mockResolvedValue(true) }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function status(extra: Partial<SessionGitHubStatus> = {}): SessionGitHubStatus {
  return {
    repo: "owner/repo", branch: "feature/test", url: "https://github.com/owner/repo/pull/7",
    owned: true, published: true, available: true, reason: "", fetched_at: Date.now() / 1000,
    state: "open", number: 7, ci_stale: false,
    ci: { state: "running", url: "https://github.com/owner/repo/actions/runs/1", commit: "1234567",
      total: 2, passed: 1, failed: 0, running: 1, pending: 0, names: ["tests"] },
    ...extra,
  };
}

describe("session GitHub link", () => {
  it.each([null, status({ owned: false }),
    status({ owned: undefined as unknown as boolean })])("hides a pane without a branch", (value) => {
    const { container } = render(<GitHubStatusBadge status={value} appearance="dark" />);
    expect(container.innerHTML).toBe("");
  });

  it("shows a quiet branch symbol while the branch is only local", () => {
    render(<GitHubStatusBadge status={status({ published: false, state: "branch", number: null })} appearance="dark" />);
    const symbol = screen.getByTestId("session-github-status");
    expect(symbol.getAttribute("role")).toBe("img");
    expect(symbol.getAttribute("aria-label")).toBe("owner/repo · feature/test: Not on GitHub yet");
    expect(symbol.title).toContain("Not on GitHub yet");
    expect(symbol.querySelectorAll("svg")).toHaveLength(1);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("does not claim a local branch is unpublished while GitHub cannot be read", () => {
    render(<GitHubStatusBadge status={status({ published: false, available: false })} appearance="dark" />);
    expect(screen.getByTestId("session-github-status").title).toContain("GitHub status unavailable");
  });

  it("renders just one quiet icon even with running CI and merge warnings", () => {
    render(<GitHubStatusBadge status={status({ merge_status: "dirty", review: "changes_requested" })} appearance="dark" />);
    const link = screen.getByRole("link");
    expect(link.textContent).toBe("");
    expect(link.querySelectorAll("svg")).toHaveLength(1);
    expect(link.querySelector("svg")?.getAttribute("width")).toBe("16");
    expect(link.style.background).toBe("");
    expect(link.style.border).toBe("");
    expect(link.className).not.toMatch(/(?:^|\s)(?:bg-|border(?:\s|-))/);
    expect(screen.queryByText(/Running|#7/)).toBeNull();
  });

  it.each(["draft", "open", "queued", "merged", "closed"] as const)("opens the %s pull request through the desktop browser bridge", (state) => {
    const drag = vi.fn();
    render(<div onPointerDown={drag} onClick={drag}><GitHubStatusBadge status={status({ state })} appearance="dark" /></div>);
    const link = screen.getByRole("link", { name: /Open GitHub pull request #7/ });
    expect(link.getAttribute("href")).toBe("https://github.com/owner/repo/pull/7");
    expect(link.title).toContain("Open pull request #7");
    fireEvent.pointerDown(link);
    fireEvent.click(link);
    expect(drag).not.toHaveBeenCalled();
    expect(openExternalUrl).toHaveBeenCalledExactlyOnceWith("https://github.com/owner/repo/pull/7");
  });

  it("opens the published branch when it has no pull request", () => {
    render(<GitHubStatusBadge status={status({ state: "branch", number: null,
      url: "https://github.com/owner/repo/tree/feature%2Ftest" })} appearance="dark" />);
    const link = screen.getByRole("link", { name: /Open GitHub branch/ });
    expect(link.getAttribute("href")).toBe("https://github.com/owner/repo/tree/feature%2Ftest");
    fireEvent.click(link);
    expect(openExternalUrl).toHaveBeenCalledExactlyOnceWith("https://github.com/owner/repo/tree/feature%2Ftest");
  });

  it("opens the upstream pull request for a fork's branch", () => {
    render(<GitHubStatusBadge status={status({ repo: "contributor/fork",
      url: "https://github.com/upstream/project/pull/7" })} appearance="dark" />);
    fireEvent.click(screen.getByRole("link", { name: /Open GitHub pull request #7/ }));
    expect(openExternalUrl).toHaveBeenCalledExactlyOnceWith("https://github.com/upstream/project/pull/7");
  });

  it.each(["https://github.com/", "https://github.com/owner/repo",
    "https://github.com.evil.invalid/owner/repo/pull/7", "https://github.com@evil.invalid/owner/repo/pull/7",
    "javascript:alert(1)", "https://github.com/owner/repo/pull/0"])("falls back to the branch for invalid PR URL %s", (url) => {
    render(<GitHubStatusBadge status={status({ url })} appearance="dark" />);
    const link = screen.getByRole("link", { name: /Open GitHub branch/ });
    expect(link.getAttribute("href")).toBe("https://github.com/owner/repo/tree/feature%2Ftest");
    fireEvent.click(link);
    expect(openExternalUrl).toHaveBeenCalledExactlyOnceWith("https://github.com/owner/repo/tree/feature%2Ftest");
  });

  it.each(["light", "dark"] as const)("uses normal %s terminal chrome", (appearance) => {
    render(<GitHubStatusBadge status={status({ state: "merged" })} appearance={appearance} />);
    const reference = document.createElement("a");
    reference.style.color = PANE_BRAND[appearance].inkMuted;
    expect(screen.getByRole("link").style.color).toBe(reference.style.color);
  });

  it.each(["branch", "draft", "open", "queued", "merged", "closed"] as const)("keeps %s status in the single icon's tooltip", (state) => {
    render(<GitHubStatusBadge status={status({ state })} appearance="dark" />);
    const link = screen.getByRole("link");
    expect(link.title).toContain("owner/repo · feature/test\n");
    expect(link.querySelectorAll("svg")).toHaveLength(1);
    expect(link.textContent).toBe("");
  });

  it.each([{ available: false }, { fetched_at: 1 }])("keeps the known PR link when status is unavailable: %j", (extra) => {
    render(<GitHubStatusBadge status={status({ state: "merged", ...extra })} appearance="dark" />);
    const link = screen.getByRole("link");
    expect(link.title).toContain("GitHub status unavailable");
    expect(link.title).not.toContain("merged");
    expect(link.getAttribute("href")).toBe("https://github.com/owner/repo/pull/7");
  });

  it("rejects invalid repository link metadata", () => {
    const { container } = render(<GitHubStatusBadge status={status({ repo: "evil.invalid/a/b" })} appearance="dark" />);
    expect(container.innerHTML).toBe("");
  });
});

describe("a session with several branches", () => {
  const several = () => status({
    branch: "claude/still-open", url: "https://github.com/owner/repo/pull/9", number: 9, state: "open",
    others: [
      status({ branch: "claude/merged", url: "https://github.com/owner/repo/pull/8", number: 8, state: "merged" }),
      status({ branch: "claude/closed", url: "https://github.com/owner/repo/pull/7", number: 7, state: "closed" }),
      status({ branch: "claude/local", published: false, state: "branch", number: null }),
    ],
  });

  it("shows one symbol with the number of branches and keeps the list closed", () => {
    render(<GitHubStatusBadge status={several()} appearance="dark" />);
    const button = screen.getByRole("button", { name: /4 branches of this session, now owner\/repo · claude\/still-open/ });
    expect(button.textContent).toBe("4");
    expect(button.querySelectorAll("svg")).toHaveLength(1);
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.getByTestId("session-github-branches").hidden).toBe(true);
  });

  it("lists every branch with its state, the shown one first", () => {
    render(<GitHubStatusBadge status={several()} appearance="dark" />);
    fireEvent.click(screen.getByTestId("session-github-status"));
    const menu = screen.getByTestId("session-github-branches");
    expect(menu.hidden).toBe(false);
    const rows = Array.from(menu.querySelectorAll("[role=menuitem]"));
    expect(rows.map((row) => row.textContent)).toEqual([
      "claude/still-open#9 · Open pull request",
      "claude/merged#8 · Pull request merged",
      "claude/closed#7 · Closed without merging",
      "claude/localNot on GitHub yet",
    ]);
    expect(rows[1].className).toContain("opacity-60");
    expect(rows[0].className).not.toContain("opacity-60");
  });

  it("opens the chosen pull request and closes the list", () => {
    const drag = vi.fn();
    render(<div onPointerDown={drag} onClick={drag}><GitHubStatusBadge status={several()} appearance="dark" /></div>);
    fireEvent.pointerDown(screen.getByTestId("session-github-status"));
    fireEvent.click(screen.getByTestId("session-github-status"));
    fireEvent.click(screen.getByRole("menuitem", { name: /Open GitHub pull request #8/ }));
    expect(openExternalUrl).toHaveBeenCalledExactlyOnceWith("https://github.com/owner/repo/pull/8");
    expect(screen.getByTestId("session-github-branches").hidden).toBe(true);
    expect(drag).not.toHaveBeenCalled();
  });

  it("does not link a branch that is not on GitHub", () => {
    render(<GitHubStatusBadge status={several()} appearance="dark" />);
    fireEvent.click(screen.getByTestId("session-github-status"));
    const local = screen.getByText("claude/local").closest("[role=menuitem]") as HTMLElement;
    expect(local.tagName).toBe("DIV");
    expect(local.getAttribute("aria-disabled")).toBe("true");
  });

  it("closes on Escape and on a press outside", () => {
    render(<GitHubStatusBadge status={several()} appearance="dark" />);
    const button = screen.getByTestId("session-github-status");
    const menu = screen.getByTestId("session-github-branches");
    fireEvent.click(button);
    fireEvent.keyDown(menu, { key: "Escape" });
    expect(menu.hidden).toBe(true);
    fireEvent.click(button);
    fireEvent.pointerDown(document.body);
    expect(menu.hidden).toBe(true);
  });

  it("drops a listed branch with invalid repository metadata", () => {
    render(<GitHubStatusBadge status={status({ others: [status({ repo: "evil.invalid/a/b", branch: "x" })] })} appearance="dark" />);
    expect(screen.getByRole("link")).toBeTruthy();
    expect(screen.queryByTestId("session-github-branches")).toBeNull();
  });

  it.each(["light", "dark"] as const)("draws the list on the %s float step", (appearance) => {
    render(<GitHubStatusBadge status={several()} appearance={appearance} />);
    const reference = document.createElement("div");
    reference.style.background = PANE_CHROME[appearance].float;
    reference.style.color = PANE_BRAND[appearance].ink;
    const menu = screen.getByTestId("session-github-branches");
    expect(menu.style.background).toBe(reference.style.background);
    expect(menu.style.color).toBe(reference.style.color);
  });
});

describe("a status that is still being confirmed", () => {
  it("holds the branch's place with a spinner before anything is known", () => {
    render(<GitHubStatusBadge status={null} pending appearance="dark" />);
    const place = screen.getByRole("status");
    expect(place.getAttribute("aria-label")).toBe("Reading the GitHub status…");
    expect(place.getAttribute("data-state")).toBe("loading");
    expect(screen.getByTestId("session-github-pending").querySelector("svg")?.getAttribute("class")).toContain("animate-spin");
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("keeps an old answer's symbol inside the spinner instead of calling it unavailable", () => {
    const old = status({ state: "queued", fetched_at: Date.now() / 1000 - 600 });
    render(<GitHubStatusBadge status={old} pending appearance="dark" />);
    const link = screen.getByRole("link");
    expect(link.title).toContain("In the merge queue");
    expect(link.title).toContain("Refreshing GitHub status…");
    expect(link.title).not.toContain("GitHub status unavailable");
    expect(screen.getByTestId("session-github-pending")).toBeTruthy();
    expect(link.querySelector("svg")?.getAttribute("width")).toBe("10");
  });

  it("calls the same old answer unavailable once nothing newer is coming", () => {
    render(<GitHubStatusBadge status={status({ fetched_at: Date.now() / 1000 - 600 })} appearance="dark" />);
    expect(screen.getByRole("link").title).toContain("GitHub status unavailable");
    expect(screen.queryByTestId("session-github-pending")).toBeNull();
  });

  it("spins round the symbol of a session with several branches", () => {
    const shown = status({ others: [status({ branch: "feature/other", state: "merged" })] });
    render(<GitHubStatusBadge status={shown} pending appearance="light" />);
    const button = screen.getByTestId("session-github-status");
    expect(button.tagName).toBe("BUTTON");
    expect(button.textContent).toBe("2");
    expect(button.title).toContain("Refreshing GitHub status…");
    expect(screen.getByTestId("session-github-pending").style.color).toBe("rgb(139, 87, 0)");
  });

  it.each(["light", "dark"] as const)("takes the pending hue from the %s pane appearance", (appearance) => {
    render(<GitHubStatusBadge status={null} pending appearance={appearance} />);
    const ring = screen.getByTestId("session-github-pending");
    expect(ring.style.color).toBe(appearance === "light" ? "rgb(139, 87, 0)" : "rgb(210, 148, 62)");
  });
});
