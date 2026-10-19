import { afterEach, describe, expect, it } from "vitest";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { openPaneSession } from "./codingNavigate";

describe("open a coding session from the office", () => {
  const initialSection = useEventStore.getState().activeSection;
  const initialLayout = useIdeThreadsStore.getState().layout;
  afterEach(() => {
    useIdeThreadsStore.setState({ layout: initialLayout });
    useEventStore.setState({ activeSection: initialSection });
    useIdeChatStore.setState({ paneRequest: null });
  });

  it("switches to the Agentic IDE and asks it to focus the pane", () => {
    useEventStore.setState({ activeSection: "visualization" });
    openPaneSession({ workspace_id: "ws-1", name: "T2" });
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
    expect(useIdeChatStore.getState().paneRequest).toMatchObject({ workspaceId: "ws-1", pane: "T2", maximize: true });
  });

  it("stays in the IDE and issues a fresh request each time", () => {
    useEventStore.setState({ activeSection: "agentic-ide" });
    openPaneSession({ workspace_id: "ws-1", name: "T2" });
    const first = useIdeChatStore.getState().paneRequest!.nonce;
    openPaneSession({ workspace_id: "ws-1", name: "T2" });
    expect(useEventStore.getState().activeSection).toBe("agentic-ide");
    expect(useIdeChatStore.getState().paneRequest!.nonce).toBe(first + 1);
  });


  it("leaves the thread layout so the pane itself shows, not the last open thread", () => {
    useIdeThreadsStore.setState({ layout: "threads" });
    openPaneSession({ workspace_id: "ws-1", name: "T2" });
    expect(useIdeThreadsStore.getState().layout).toBe("grid");
    expect(useIdeChatStore.getState().paneRequest).toMatchObject({ workspaceId: "ws-1", pane: "T2", maximize: true });
  });
});
