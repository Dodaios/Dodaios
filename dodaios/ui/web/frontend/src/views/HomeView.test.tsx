import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/store/home", () => ({
  useHomeStore: (selector: (s: { agentChatId: string | null }) => unknown) => selector({ agentChatId: null }),
}));
/** Whether the conversation was in the page when it first laid itself out. */
const placedAtMount: boolean[] = [];
vi.mock("@/components/home/AssistantChat", async () => {
  const { useLayoutEffect, useRef } = await import("react");
  return {
    AssistantChat: () => {
      const ref = useRef<HTMLDivElement>(null);
      useLayoutEffect(() => {
        placedAtMount.push(document.body.contains(ref.current));
      }, []);
      return <div ref={ref} data-testid="assistant-chat" />;
    },
  };
});
vi.mock("@/components/home/AssistantPanel", () => ({
  default: () => <aside data-testid="assistant-panel" />,
}));
vi.mock("@/lib/newChat", () => ({ startNewTextChat: vi.fn() }));

import { useAgentChatStore } from "@/store/agentChat";
import { useNodePeek } from "@/store/nodePeek";
import { HomeView } from "@/views/HomeView";

afterEach(cleanup);

describe("HomeView's conversation and the node window", () => {
  it("offers its conversation to the window: the element it is drawn in, and the way home", () => {
    render(<HomeView />);
    const chat = screen.getByTestId("assistant-chat");
    const column = screen.getByTestId("home-conversation-column");
    expect(column.contains(chat)).toBe(true);
    // The window can have this conversation: it is the one with the assistant.
    const lent = useNodePeek.getState().lender;
    expect(lent?.chat).toBe(useAgentChatStore);
    expect(lent?.home).toBe(column);
    expect(lent?.element.contains(chat)).toBe(true);

    // The window moves the element beside the node: the same drawing, elsewhere.
    const beside = document.body.appendChild(document.createElement("div"));
    act(() => void beside.appendChild(lent!.element));
    expect(screen.getAllByTestId("assistant-chat")).toEqual([chat]);
    expect(column.contains(chat)).toBe(false);
    beside.remove();
  });

  it("draws the conversation only once it is in the page, so it can open at its end", () => {
    placedAtMount.length = 0;
    render(<HomeView />);
    // Laid out in an element outside the page, the conversation has no height:
    // its move to the end goes nowhere and it opens at the first message.
    expect(placedAtMount).toEqual([true]);
  });

  it("has the conversation back and stops offering it once the page is gone", () => {
    const view = render(<HomeView />);
    const lent = useNodePeek.getState().lender!;
    const beside = document.body.appendChild(document.createElement("div"));
    beside.appendChild(lent.element);
    view.unmount();
    expect(useNodePeek.getState().lender).toBeNull();
    // Nothing of it is left standing in a window that no longer has a page behind it.
    expect(beside.childElementCount).toBe(0);
    expect(document.querySelector('[data-testid="home-conversation"]')).toBeNull();
    beside.remove();
  });
});

describe("HomeView assistant panel", () => {
  it("stands to the right of the conversation", async () => {
    render(<HomeView />);
    expect(await screen.findByTestId("assistant-panel")).toBeTruthy();
    expect(screen.getByTestId("assistant-chat")).toBeTruthy();
  });

  it("has no activity panel and no button to open one", async () => {
    render(<HomeView />);
    await screen.findByTestId("assistant-panel");
    expect(screen.queryByTestId("lead-activity-open")).toBeNull();
    expect(screen.queryByTestId("lead-activity")).toBeNull();
  });
});
