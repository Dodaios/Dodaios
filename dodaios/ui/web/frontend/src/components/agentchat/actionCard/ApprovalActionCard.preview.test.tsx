import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { createAgentChatStore } from "@/store/agentChat";
import { AgentChatStoreProvider } from "../AgentChatStoreContext";
import { EMPTY_TIMELINE, reduceEvents, type ToolBlock, type TurnItem } from "../reduce";
import { parseApprovalCard } from "./approvalInfo";
import { ApprovalActionCard } from "./ApprovalActionCard";

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>): AgentChatEvent {
  return { seq: ++seq, ts_ms: 1000 + seq, kind, payload } as AgentChatEvent;
}

afterEach(() => {
  cleanup();
  seq = 0;
});

const MAIL_PREVIEW = {
  class: "mail",
  irreversible: true,
  compact: "To: ada@known.example",
  fields: [
    { key: "to", arg: "to", kind: "people", editable: false, items: [{ text: "ada@known.example", new: false }, { text: "new@stranger.example", new: true }] },
    { key: "subject", arg: "subject", kind: "text", editable: true, value: "Quarterly numbers" },
    { key: "body", arg: "body", kind: "multiline", editable: true, value: "Hi Ada" },
  ],
};

const CARD = {
  source: { kind: "connector", app: "Gmail", verb: "send_message" },
  where: "", why: "", caution: "data_leaves", detail: "", brief: "",
  rule: { scopes: ["chat"], chat: "tool", app: "Gmail", verb: "send_message", pattern: "", broad: "" },
};

function blockOf(events: AgentChatEvent[]): ToolBlock {
  const tl = reduceEvents(EMPTY_TIMELINE, events);
  const turn = tl.items.find((item) => item.type === "turn") as TurnItem;
  return turn.blocks.find((b) => b.kind === "tool") as ToolBlock;
}

function opened(extra: Record<string, unknown> = {}, more: AgentChatEvent[] = []): ToolBlock {
  const input = { action: "send_message", to: "ada@known.example" };
  return blockOf([
    ev("turn_started", { turn_id: "t1" }),
    ev("tool_call", { turn_id: "t1", call_id: "c1", name: "gmail", input }),
    ev("approval_required", { turn_id: "t1", approval_id: "a1", call_id: "c1", name: "gmail", input, summary: "Mail", ...CARD, preview: MAIL_PREVIEW, ...extra }),
    ...more,
  ]);
}

function draw(block: ToolBlock, onDecide = vi.fn()) {
  const store = createAgentChatStore("jarvis");
  store.setState({ activeSessionId: "s1" });
  render(<AgentChatStoreProvider store={store}><ApprovalActionCard block={block} onDecide={onDecide} /></AgentChatStoreProvider>);
  return onDecide;
}

describe("the exact-action preview on the approval card", () => {
  it("parses the preview and drops an unknown class", () => {
    const info = parseApprovalCard({ ...CARD, preview: MAIL_PREVIEW });
    expect(info?.preview?.cls).toBe("mail");
    expect(info?.preview?.fields[0].items[1]).toEqual({ text: "new@stranger.example", new: true });
    expect(parseApprovalCard({ ...CARD, preview: { ...MAIL_PREVIEW, class: "nonsense" } })?.preview).toBeUndefined();
  });

  it("shows every field, marks the new recipient and says the action cannot be undone", () => {
    draw(opened());
    expect(screen.getByTestId("approval-preview-irreversible").textContent).toBe("This cannot be undone once it runs.");
    expect(screen.getByTestId("approval-preview-subject").textContent).toContain("Quarterly numbers");
    expect(screen.getByTestId("approval-preview-body").textContent).toContain("Hi Ada");
    expect(screen.getAllByTestId("approval-preview-new")).toHaveLength(1);
    expect(screen.getByTestId("approval-preview-to").textContent).toContain("new@stranger.example");
    // Recipients are never editable.
    expect(screen.queryByTestId("approval-preview-edit-to")).toBeNull();
  });

  it("sends the edited text with the answer", async () => {
    const onDecide = draw(opened());
    fireEvent.click(screen.getByTestId("approval-preview-edit-subject"));
    fireEvent.change(screen.getByTestId("approval-preview-input-subject"), { target: { value: "Q3 numbers" } });
    const allow = screen.getByTestId("action-card-allow");
    expect(allow.textContent).toBe("Allow with my changes");
    fireEvent.click(allow);
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(1));
    expect(onDecide).toHaveBeenCalledWith("a1", "allow", undefined, undefined, { subject: "Q3 numbers" });
  });

  it("answers plainly when nothing was edited, and never sends edits with a deny", async () => {
    const onDecide = draw(opened());
    fireEvent.click(screen.getByTestId("approval-preview-edit-subject"));
    fireEvent.change(screen.getByTestId("approval-preview-input-subject"), { target: { value: "Changed" } });
    fireEvent.click(screen.getByTestId("action-card-deny"));
    await waitFor(() => expect(onDecide).toHaveBeenCalledTimes(1));
    expect(onDecide).toHaveBeenCalledWith("a1", "deny");
  });

  it("renders a diff for an overwrite", () => {
    const preview = {
      class: "file_write", irreversible: true, compact: "",
      fields: [{ key: "path", arg: "path", kind: "path", editable: false, value: "notes.txt" }],
      diff: { path: "notes.txt", creates: false, added: 1, removed: 1, truncated: false, lines: [{ op: "-", text: "two" }, { op: "+", text: "2" }] },
    };
    draw(opened({ preview }));
    const diff = screen.getByTestId("approval-preview-diff");
    expect(diff.textContent).toContain("- two");
    expect(diff.textContent).toContain("+ 2");
  });

  it("keeps a set-aside card open after its turn ends and offers no Always allow", () => {
    const block = opened({}, [
      ev("approval_deferred", { turn_id: "t1", approval_id: "a1" }),
      ev("turn_finished", { turn_id: "t1", status: "done" }),
    ]);
    expect(block.approval?.decision).toBeNull();
    expect(block.approval?.deferred).toBe(true);
    draw(block);
    expect(screen.getByTestId("thread-approval").textContent).toContain("Set aside");
    expect(screen.queryByTestId("action-card-always")).toBeNull();
  });

  it("shows what the person edited once the card is settled", () => {
    const block = opened({}, [
      ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "allow", edited: { subject: { before: "Quarterly numbers", after: "Q3 numbers" } } }),
    ]);
    expect(block.approval?.edited?.subject.after).toBe("Q3 numbers");
    draw(block);
    fireEvent.click(screen.getByRole("button", { name: /./ }));
    expect(screen.getByTestId("approval-edited").textContent).toContain("Q3 numbers");
  });
});
