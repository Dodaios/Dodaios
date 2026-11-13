/**
 * The dialog a tile of the "Make something new" row opens, and the two
 * messages the library hands to the assistant.
 *
 * Contracts worth pinning:
 * - the dialog is headed by the type's name, says what the type is good
 *   for, and offers three examples that fill the field,
 * - "Create with the assistant" needs text; it sends the request, tells the
 *   library (which shows a placeholder) and closes,
 * - a request that could not be sent keeps the dialog open with what was
 *   typed, and says so,
 * - "Start with an empty one" creates a starter node and hands the card on,
 * - the request goes into the lead conversation as the reader's own message;
 *   a change request only drafts, in that conversation's composer.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { readComposerDraft } from "@/components/agentchat/composerDrafts";
import { useEventStore } from "@/store/events";
import { NewNodeDialog } from "./NewNodeDialog";
import type { NodeCard, NodeType } from "./nodeModel";

const chat = vi.hoisted(() => ({
  requestNewNode: vi.fn(async (_type: string, _text: string) => undefined),
  askDodaiosToChange: vi.fn(async () => undefined),
}));
vi.mock("./askDodaios", () => chat);

// The front page's chat store, reduced to what a draft needs.
const chatStore = vi.hoisted(() => {
  const state = { activeSessionId: null as string | null, openSession: vi.fn() };
  const hook = Object.assign(() => state, { getState: () => state });
  return { state, hook };
});
vi.mock("@/store/agentChat", () => ({ useAgentChatStore: chatStore.hook }));

const CREATED: NodeCard = {
  key: "2026-11-13__node__abc::index.html",
  id: "abc",
  type: "sheets",
  origin: "node",
  title: "Untitled",
  slug: "2026-11-13__node__abc",
  path: "index.html",
  visual_kind: "page",
  created_at: 1_000,
  updated_at: 1_000,
  size: 10,
  version: 1,
  status: "ready",
  kept_current: false,
  refreshing: false,
  every_minutes: 0,
  request: "",
  preview: null,
};

interface Call {
  url: string;
  method: string;
  body: unknown;
}

function installFetch(failing: (url: string, method: string) => boolean = () => false): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
      if (failing(url, method)) return { ok: false, status: 500, json: async () => ({ detail: "down" }) };
      if (url === "/api/agent-chat/lead") return { ok: true, status: 200, json: async () => ({ session_id: "lead-1" }) };
      if (url.endsWith("/messages")) return { ok: true, status: 200, json: async () => ({ turn_id: "turn-1" }) };
      if (url === "/api/nodes" && method === "POST") return { ok: true, status: 200, json: async () => CREATED };
      return { ok: true, status: 200, json: async () => ({}) };
    }),
  );
  return calls;
}

function renderDialog(type: NodeType | null = "sheets") {
  const spies = {
    onType: vi.fn<(type: NodeType) => void>(),
    onClose: vi.fn(),
    onRequested: vi.fn<(type: NodeType, request: string) => void>(),
    onCreated: vi.fn<(card: NodeCard) => void>(),
  };
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <NewNodeDialog type={type} {...spies} />
    </QueryClientProvider>,
  );
  return { ...spies, invalidate };
}

const field = () => screen.getByTestId("new-node-request") as HTMLTextAreaElement;
const create = () => screen.getByTestId("new-node-create") as HTMLButtonElement;
const empty = () => screen.getByTestId("new-node-empty") as HTMLButtonElement;

beforeEach(() => {
  window.localStorage.clear();
  chat.requestNewNode.mockReset();
  chat.requestNewNode.mockResolvedValue(undefined);
  chatStore.state.activeSessionId = null;
  chatStore.state.openSession.mockClear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NewNodeDialog", () => {
  it("stays closed without a type", () => {
    installFetch();
    renderDialog(null);
    expect(screen.queryByTestId("new-node-dialog")).toBeNull();
  });

  it("is headed by the type, says what it is good for, and asks one question", () => {
    installFetch();
    renderDialog("sheets");
    const dialog = screen.getByTestId("new-node-dialog");
    expect(within(dialog).getByRole("heading").textContent).toBe("Sheets");
    expect(dialog.querySelector('[data-node-type-icon="sheets"], svg')).toBeTruthy();
    expect(dialog.textContent).toContain("rows and columns");
    expect(field().value).toBe("");
    expect(field().placeholder.length).toBeGreaterThan(10);
    expect(document.activeElement).toBe(field());
    // Nothing to send yet; an empty one can always be started.
    expect(create().disabled).toBe(true);
    expect(empty().disabled).toBe(false);
  });

  it("lets the reader choose the type inside, and keeps what was typed", () => {
    const { onType } = renderDialog("sheets");
    const types = within(screen.getByTestId("new-node-types")).getAllByRole("radio");
    expect(types).toHaveLength(7);
    expect(screen.getByTestId("new-node-type-sheets").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("new-node-type-docs").getAttribute("aria-checked")).toBe("false");

    fireEvent.change(field(), { target: { value: "Our subscriptions" } });
    fireEvent.click(screen.getByTestId("new-node-type-data"));
    expect(onType).toHaveBeenCalledWith("data");
    // The owner switches the type; the form itself stays, with its text.
    expect(field().value).toBe("Our subscriptions");
  });

  it("offers three examples per type, and a click puts one into the field", () => {
    installFetch();
    renderDialog("slides");
    const examples = screen.getAllByTestId("new-node-example");
    expect(examples).toHaveLength(3);
    expect(new Set(examples.map((example) => example.textContent)).size).toBe(3);

    fireEvent.click(examples[1]);
    expect(field().value).toBe(examples[1].textContent);
    expect(create().disabled).toBe(false);
  });

  it("sends the request, tells the library and closes", async () => {
    installFetch();
    const { onClose, onRequested, onCreated } = renderDialog("sheets");
    fireEvent.change(field(), { target: { value: "  A budget for this year by month  " } });
    fireEvent.click(create());

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
    expect(chat.requestNewNode).toHaveBeenCalledWith("sheets", "A budget for this year by month");
    expect(onRequested).toHaveBeenCalledWith("sheets", "A budget for this year by month");
    expect(onCreated).not.toHaveBeenCalled();
  });

  it("sends on the platform's Enter shortcut as well", async () => {
    installFetch();
    const { onRequested } = renderDialog("docs");
    fireEvent.change(field(), { target: { value: "Meeting notes" } });
    // A bare Enter is a new line in a text area.
    fireEvent.keyDown(field(), { key: "Enter" });
    expect(chat.requestNewNode).not.toHaveBeenCalled();
    fireEvent.keyDown(field(), { key: "Enter", metaKey: true });
    await waitFor(() => expect(onRequested).toHaveBeenCalledWith("docs", "Meeting notes"));
  });

  it("stays open with what was typed when the request could not be sent", async () => {
    installFetch();
    chat.requestNewNode.mockRejectedValueOnce(new Error("offline"));
    const { onClose, onRequested } = renderDialog("sheets");
    fireEvent.change(field(), { target: { value: "A budget" } });
    fireEvent.click(create());

    const error = await screen.findByTestId("new-node-error");
    expect(error.getAttribute("role")).toBe("alert");
    expect(onClose).not.toHaveBeenCalled();
    expect(onRequested).not.toHaveBeenCalled();
    expect(field().value).toBe("A budget");

    // The second try goes through.
    fireEvent.click(create());
    await waitFor(() => expect(onRequested).toHaveBeenCalledWith("sheets", "A budget"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("starts with an empty node of the type and hands the card on", async () => {
    const calls = installFetch();
    const { onClose, onCreated, onRequested, invalidate } = renderDialog("sheets");
    fireEvent.click(empty());

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(CREATED));
    expect(calls.find((call) => call.method === "POST")).toEqual({
      url: "/api/nodes",
      method: "POST",
      body: { type: "sheets", language: "en" },
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onRequested).not.toHaveBeenCalled();
    expect(chat.requestNewNode).not.toHaveBeenCalled();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["nodes"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["outputs"] });
  });

  it("names the empty node after what was typed", async () => {
    const calls = installFetch();
    const { onCreated } = renderDialog("docs");
    fireEvent.change(field(), { target: { value: " Meeting notes " } });
    fireEvent.click(empty());
    await waitFor(() => expect(onCreated).toHaveBeenCalled());
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      type: "docs",
      title: "Meeting notes",
      language: "en",
    });
  });

  it("says so when the empty node could not be created", async () => {
    installFetch((url, method) => url === "/api/nodes" && method === "POST");
    const { onClose, onCreated } = renderDialog("sheets");
    fireEvent.click(empty());
    await screen.findByTestId("new-node-error");
    expect(onCreated).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(empty().disabled).toBe(false);
  });
});

describe("talking to the assistant", () => {
  const BRIEF: NodeCard = { ...CREATED, key: "brief", id: "n-brief", type: "docs", title: "Website brief" };

  it("sends a new-node request into the lead conversation as the reader's message", async () => {
    const calls = installFetch();
    const real = await vi.importActual<typeof import("./askDodaios")>("./askDodaios");
    expect(real.newNodeRequestText("sheets", "  A budget, $& all  ")).toBe(
      "Create a new node of type Sheets for me: A budget, $& all",
    );

    await real.requestNewNode("sheets", " A budget ");
    expect(calls.map((call) => `${call.method} ${call.url}`)).toEqual([
      "GET /api/agent-chat/lead",
      "POST /api/agent-chat/sessions/lead-1/messages",
    ]);
    expect((calls[1].body as { text: string }).text).toBe("Create a new node of type Sheets for me: A budget");
  });

  it("rejects when the request could not be sent", async () => {
    installFetch((url) => url.endsWith("/messages"));
    const real = await vi.importActual<typeof import("./askDodaios")>("./askDodaios");
    await expect(real.requestNewNode("docs", "Notes")).rejects.toBeTruthy();
  });

  it("drafts a change request in the lead conversation and opens it, without sending", async () => {
    const calls = installFetch();
    const real = await vi.importActual<typeof import("./askDodaios")>("./askDodaios");
    useEventStore.getState().setActiveSection("visualization");

    await real.askDodaiosToChange(BRIEF);

    expect(readComposerDraft(chatStore.hook as never, "lead-1").text).toBe(
      'Change the node "Website brief" (id n-brief): ',
    );
    expect(chatStore.state.openSession).toHaveBeenCalledWith("lead-1");
    expect(useEventStore.getState().activeSection).toBe("chats");
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("drafts into the open conversation when the lead route does not answer", async () => {
    installFetch((url) => url === "/api/agent-chat/lead");
    chatStore.state.activeSessionId = "open-7";
    const real = await vi.importActual<typeof import("./askDodaios")>("./askDodaios");

    await real.askDodaiosToChange(BRIEF);

    expect(readComposerDraft(chatStore.hook as never, "open-7").text).toContain("Website brief");
    expect(chatStore.state.openSession).not.toHaveBeenCalled();
  });
});
