import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key }));
vi.mock("@/store/home", () => ({
  useHomeStore: (selector: (s: { agentChatId: string | null }) => unknown) => selector({ agentChatId: null }),
}));
vi.mock("@/components/home/AssistantChat", () => ({ AssistantChat: () => <div data-testid="assistant-chat" /> }));
vi.mock("@/components/home/AssistantPanel", () => ({
  default: () => <aside data-testid="assistant-panel" />,
}));
vi.mock("@/lib/newChat", () => ({ startNewTextChat: vi.fn() }));

import { HomeView } from "@/views/HomeView";

afterEach(cleanup);

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
