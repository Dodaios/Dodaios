import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import { chatUrlTransform, threadRefFromChatHref, threadRefFromMarkdownUrl } from "@/components/agentchat/chatLinks";
import { useEventStore } from "@/store/events";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { resetThreadLinksForTests } from "./CodingAgentLink";
import { copyThreadCode, shownThreadCode } from "./threadCode";

const ID = "3f9a2c41d0aa4b7e9c1f2a3b4c5d6e7f";

function answerWith(info: Record<string, unknown>) {
  const fetchMock = vi.fn(async (_url: string) => ({ ok: true, json: async () => info }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  resetThreadLinksForTests();
  useEventStore.setState({ activeSection: "chats" });
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("a coding agent linked in a chat answer", () => {
  it("reads a thread link and nothing else as one", () => {
    expect(threadRefFromMarkdownUrl(`thread:${ID}`)).toBe(ID);
    expect(threadRefFromMarkdownUrl("thread:#3F9A2C")).toBe("3f9a2c");
    expect(threadRefFromMarkdownUrl("thread:abc")).toBeNull();
    expect(threadRefFromMarkdownUrl("thread:../../etc")).toBeNull();
    expect(threadRefFromMarkdownUrl("https://example.test/thread:3f9a2c")).toBeNull();
    expect(threadRefFromChatHref(chatUrlTransform(`thread:${ID}`))).toBe(ID);
    expect(threadRefFromChatHref("#jarvis-local=x")).toBeNull();
  });

  it("shows the thread's own title with the coding agent's logo behind it", async () => {
    const fetchMock = answerWith({ found: true, session_id: ID, code: "3f9a2c", title: "Login page", agent: "claude", agent_label: "Claude Code" });
    render(<ChatMarkdown text={`It is in [the login thread](thread:${ID}).`} />);
    const link = screen.getByTestId("coding-agent-link");
    // The words of the answer until the thread's title is known.
    expect(link.textContent).toContain("the login thread");
    await waitFor(() => expect(screen.getByTestId("coding-agent-link").textContent).toContain("Login page"));
    expect(fetchMock).toHaveBeenCalledWith(`/api/agent-chat/thread-links/${ID}`);
    const chip = screen.getByTestId("coding-agent-link");
    const logo = chip.querySelector("[data-agent='claude'], img, svg, [role='img']");
    expect(logo).toBeTruthy();
    // Title first, logo behind it.
    expect(chip.firstElementChild?.textContent).toBe("Login page");
    expect(chip.lastElementChild).not.toBe(chip.firstElementChild);
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("opens the thread in the Agentic IDE on a click", async () => {
    answerWith({ found: true, session_id: ID, code: "3f9a2c", title: "Login page", agent: "codex", agent_label: "Codex" });
    render(<ChatMarkdown text={`[Login page](thread:${ID})`} />);
    await waitFor(() => expect(screen.getByTestId("coding-agent-link").getAttribute("title")).toContain("Codex"));
    fireEvent.click(screen.getByTestId("coding-agent-link"));
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(useIdeThreadsStore.getState().selection.sessionId).toBe(ID);
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
  });

  it("opens a thread linked by its code once the code is resolved", async () => {
    answerWith({ found: true, session_id: ID, code: "3f9a2c", title: "Login page", agent: "claude", agent_label: "Claude Code" });
    render(<ChatMarkdown text="[Login page](thread:3f9a2c)" />);
    fireEvent.click(screen.getByTestId("coding-agent-link"));
    await waitFor(() => expect(useIdeThreadsStore.getState().selection.sessionId).toBe(ID));
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
  });

  it("leaves plain words when the thread no longer exists", async () => {
    answerWith({ found: false, ref: ID });
    render(<ChatMarkdown text={`[Old thread](thread:${ID})`} />);
    await waitFor(() => expect(screen.getByTestId("coding-agent-link-gone").textContent).toBe("Old thread"));
    expect(screen.queryByTestId("coding-agent-link")).toBeNull();
  });

  it("asks once for a thread several links name", async () => {
    const fetchMock = answerWith({ found: true, session_id: ID, title: "Login page", agent: "claude", agent_label: "Claude Code" });
    render(<ChatMarkdown text={`[a](thread:${ID}) and again [b](thread:${ID})`} />);
    await waitFor(() => expect(screen.getAllByTestId("coding-agent-link")[1].textContent).toContain("Login page"));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("a thread's code", () => {
  it("is shown with its hash, and not at all while the row has none", () => {
    expect(shownThreadCode({ code: "3f9a2c" })).toBe("#3f9a2c");
    expect(shownThreadCode({})).toBe("");
    expect(shownThreadCode(null)).toBe("");
  });

  it("is copied with a word on what it is for", async () => {
    const writeText = vi.fn(async () => undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    const pushToast = vi.fn();
    useEventStore.setState({ pushToast });
    await copyThreadCode("#3f9a2c");
    expect(writeText).toHaveBeenCalledWith("#3f9a2c");
    expect(pushToast).toHaveBeenCalledTimes(1);
    expect(String(pushToast.mock.calls[0][1])).toContain("#3f9a2c");
  });
});
