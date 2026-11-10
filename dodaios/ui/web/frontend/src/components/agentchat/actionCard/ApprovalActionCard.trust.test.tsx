import { cleanup, render, screen } from "@testing-library/react";
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

const GMAIL = {
  source: { kind: "connector", app: "Gmail", verb: "send_message" },
  where: "", why: "", caution: "data_leaves", detail: "", brief: "",
  rule: { scopes: ["chat"], chat: "tool", app: "Gmail", verb: "send_message", pattern: "", broad: "" },
};

function blockFor(extra: Record<string, unknown>, name = "gmail", input: Record<string, unknown> = { action: "send_message" }): ToolBlock {
  const tl = reduceEvents(EMPTY_TIMELINE, [
    ev("turn_started", { turn_id: "t1" }),
    ev("tool_call", { turn_id: "t1", call_id: "c1", name, input }),
    ev("approval_required", { turn_id: "t1", approval_id: "a1", call_id: "c1", name, input, summary: "Do it", ...GMAIL, ...extra }),
  ]);
  const turn = tl.items.find((item) => item.type === "turn") as TurnItem;
  return turn.blocks.find((b) => b.kind === "tool") as ToolBlock;
}

function draw(block: ToolBlock) {
  const store = createAgentChatStore("jarvis");
  store.setState({ activeSessionId: "s1" });
  return render(<AgentChatStoreProvider store={store}><ApprovalActionCard block={block} onDecide={vi.fn()} /></AgentChatStoreProvider>);
}

describe("the approval card and the trust layer", () => {
  it("parses the hard limit and the checks, and drops unknown codes", () => {
    const info = parseApprovalCard({ ...GMAIL, hard_limit: "permanent_delete", checks: [{ code: "secret", severity: "block" }, { code: "nonsense" }] });
    expect(info?.hardLimit).toBe("permanent_delete");
    expect(info?.checks).toEqual([{ code: "secret", severity: "block", detail: "" }]);
    expect(parseApprovalCard({ ...GMAIL, hard_limit: "whatever" })?.hardLimit).toBeUndefined();
  });

  it("offers no Always allow for deleting for good, and says why", () => {
    draw(blockFor({ hard_limit: "permanent_delete" }, "gmail", { action: "delete_message", message_id: "m1" }));
    const buttons = [...screen.getByTestId("thread-approval").querySelectorAll("button[data-tone]")].map((b) => b.textContent);
    expect(buttons).toEqual(["Allow once", "Deny"]);
    expect(screen.getByTestId("action-card-hard-limit").textContent).toBe("This deletes for good. This always asks; no rule skips it.");
  });

  it("keeps Always allow for a first mail to someone, and reads out the outbound findings", () => {
    draw(blockFor({
      hard_limit: "new_recipient",
      checks: [
        { code: "unknown_recipient", severity: "ask", detail: "bob@gmial.com" },
        { code: "mistyped_domain", severity: "ask", detail: "bob@gmial.com → gmail.com" },
      ],
    }));
    const buttons = [...screen.getByTestId("thread-approval").querySelectorAll("button[data-tone]")].map((b) => b.textContent);
    expect(buttons).toEqual(["Allow once", "Always allow…", "Deny"]);
    expect(screen.getByTestId("action-card-hard-limit").textContent).toBe("First message to this recipient from here.");
    expect(screen.queryByTestId("action-card-check-unknown_recipient")).toBeNull();
    expect(screen.getByTestId("action-card-check-mistyped_domain").textContent).toBe("Did you mean bob@gmial.com → gmail.com?");
  });
});
