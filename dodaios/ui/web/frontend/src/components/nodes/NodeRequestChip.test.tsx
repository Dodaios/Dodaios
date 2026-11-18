import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentComposer } from "@/components/agentchat/AgentComposer";
import { AgentChatStoreProvider } from "@/components/agentchat/AgentChatStoreContext";
import { readComposerDraft, writeComposerDraft } from "@/components/agentchat/composerDrafts";
import { EMPTY_TIMELINE } from "@/components/agentchat/reduce";
import { MessageWithChips } from "@/components/agentchat/ToolChoiceChips";
import type { AgentChatCatalog } from "@/lib/agentChatApi";
import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import { NODE_TYPES } from "./nodeModel";
import { nodeRequestMessage, splitNodeRequest } from "./NodeRequestChip";

/**
 * "New" in the Nodes library opens the chat with the type's chip in front of
 * the composer. Under test: the chip and its question in the box, taking it
 * out again, the message it sends, and the bubble that shows the type.
 */

const CATALOG: AgentChatCatalog = {
  default_cwd: "C:\\work",
  shell: "pwsh",
  providers: [
    {
      id: "claude-api",
      label: "Anthropic Claude",
      family: "claude",
      runner: "claude-cli",
      models_source: "curated",
      curated_models: [{ id: "claude-opus-5", label: "Claude Opus 5" }],
      default_model: "",
      keyless: false,
      native_resume: true,
      effort_levels: ["low", "high"],
      default_effort: "high",
      permission_modes: [{ id: "default", label: "Ask before acting", description: "" }],
      default_permission_mode: "default",
      cli_installed: true,
    },
  ],
};

type Send = (...args: unknown[]) => Promise<void | "sent" | "failed" | "stale">;

function seed(send = vi.fn<Send>(async () => {})) {
  useAgentChatStore.setState({
    catalog: CATALOG,
    connections: [{ jarvis: "claude-api", key_set: true, is_active_brain: true }],
    catalogError: null,
    backendOutdated: false,
    liveModels: {},
    sessions: [],
    activeSessionId: "lead",
    activeSession: null,
    timeline: EMPTY_TIMELINE,
    surface: "jarvis",
    draft: {
      provider: "claude-api",
      model: "",
      effort: "high",
      permissionMode: "default",
      buildMode: "default",
      cwd: "C:\\work",
    },
    busy: false,
    lastError: null,
    loadCatalog: async () => {},
    loadSessions: async () => {},
    loadModels: async () => {},
    send,
  });
  return send;
}

function composer() {
  return render(
    <AgentChatStoreProvider store={useAgentChatStore}>
      <AgentComposer />
    </AgentChatStoreProvider>,
  );
}

function type(text: string) {
  const box = screen.getByTestId("composer-chip-field");
  box.textContent = text;
  fireEvent.input(box);
  return box;
}

describe("the node request message", () => {
  it("carries the type on its first line and reads back for every type", () => {
    for (const kind of NODE_TYPES) {
      const message = nodeRequestMessage(kind, "  Ten slides on last quarter \n");
      expect(message).toBe(`[node: ${kind}]\nTen slides on last quarter`);
      expect(splitNodeRequest(message)).toEqual({ type: kind, text: "Ten slides on last quarter" });
    }
  });

  it("leaves any other message alone", () => {
    expect(splitNodeRequest("[node: poster]\nA poster")).toBeNull();
    expect(splitNodeRequest("Make me [node: slides] please")).toBeNull();
    expect(splitNodeRequest("Ten slides on last quarter")).toBeNull();
  });
});

describe("the type chip in the composer", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useEventStore.setState({ connected: true, wsWarming: false, assistantName: "George" });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) }) as Response));
  });

  afterEach(() => {
    cleanup();
    writeComposerDraft(useAgentChatStore, "lead", { text: "", choices: [] });
    vi.unstubAllGlobals();
  });

  it("stands in front of the box with the type's question, and sends the type with the words", async () => {
    const send = seed();
    writeComposerDraft(useAgentChatStore, "lead", { text: "", choices: [], nodeType: "slides" });
    composer();

    expect(screen.getByTestId("node-request-chip").textContent).toBe("Dodaios Slides");
    const box = screen.getByTestId("composer-chip-field");
    expect(box.getAttribute("data-placeholder")).toBe("What should this presentation be about?");
    // The chip alone is not a request.
    expect(screen.queryByTestId("composer-send")).toBeNull();

    type("Ten slides on last quarter for Monday");
    await act(async () => {
      fireEvent.click(screen.getByTestId("composer-send"));
    });

    expect(send).toHaveBeenCalledWith("[node: slides]\nTen slides on last quarter for Monday", []);
    // Sent: the chip goes with the message, the box is an ordinary box again.
    expect(screen.queryByTestId("node-request-chip")).toBeNull();
    expect(readComposerDraft(useAgentChatStore, "lead").nodeType).toBeUndefined();
  });

  it("comes out with its cross, and with Backspace in an empty box", () => {
    seed();
    writeComposerDraft(useAgentChatStore, "lead", { text: "", choices: [], nodeType: "sheets" });
    composer();
    fireEvent.click(screen.getByTestId("node-request-chip-remove"));
    expect(screen.queryByTestId("node-request-chip")).toBeNull();
    expect(screen.getByTestId("composer-chip-field").getAttribute("data-placeholder")).not.toBe(
      "What should go in this sheet?",
    );

    act(() => writeComposerDraft(useAgentChatStore, "lead", { text: "", choices: [], nodeType: "data" }));
    expect(screen.getByTestId("node-request-chip").textContent).toBe("Dodaios Analytics");
    fireEvent.keyDown(screen.getByTestId("composer-chip-field"), { key: "Backspace" });
    expect(screen.queryByTestId("node-request-chip")).toBeNull();
  });

  it("keeps the chip and the words when the message could not be sent", async () => {
    const send = seed(vi.fn<Send>(async () => "failed"));
    writeComposerDraft(useAgentChatStore, "lead", { text: "", choices: [], nodeType: "docs" });
    composer();
    type("A one-page brief");
    await act(async () => {
      fireEvent.click(screen.getByTestId("composer-send"));
    });
    expect(send).toHaveBeenCalledTimes(1);
    const draft = readComposerDraft(useAgentChatStore, "lead");
    expect(draft.nodeType).toBe("docs");
    expect(draft.text).toBe("A one-page brief");
  });
});

describe("the sent bubble", () => {
  it("shows the type's chip above the person's words", () => {
    render(<MessageWithChips text={"[node: whiteboard]\nIdeas for the launch"} choices={[]} />);
    expect(screen.getByTestId("node-request-chip").getAttribute("data-node-type")).toBe("whiteboard");
    expect(screen.getByTestId("node-request-chip").textContent).toBe("Dodaios Whiteboard");
    expect(screen.getByTestId("tool-choice-chips").textContent).toBe("Dodaios WhiteboardIdeas for the launch");
  });
});
