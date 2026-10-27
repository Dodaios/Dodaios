import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { createAgentChatStore } from "@/store/agentChat";
import { AgentChatStoreProvider } from "../AgentChatStoreContext";
import { MessengerTurn } from "../MessengerTurn";
import { EMPTY_TIMELINE, reduceEvents, type ToolBlock, type TurnItem } from "../reduce";
import { ApprovalActionCard } from "./ApprovalActionCard";

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>): AgentChatEvent {
  return { seq: ++seq, ts_ms: 1000 + seq, kind, payload } as AgentChatEvent;
}

afterEach(() => {
  cleanup();
  seq = 0;
  vi.restoreAllMocks();
});

const GMAIL_CARD = {
  source: { kind: "connector", app: "Gmail", verb: "send" },
  where: "",
  why: "The weekly report is ready",
  caution: "data_leaves",
  detail: "{\n  \"action\": \"send\",\n  \"to\": \"team@example.com\"\n}",
  rule: { scopes: ["agent", "chat"], chat: "tool", app: "Gmail", verb: "send", pattern: "plugin:gmail:send", broad: "plugin:gmail" },
};

function asking(approvalId = "a1", extra: Record<string, unknown> = GMAIL_CARD, callId = "c1"): AgentChatEvent[] {
  return [
    ev("tool_call", { turn_id: "t1", call_id: callId, name: "gmail", input: { action: "send", to: "team@example.com" } }),
    ev("approval_required", {
      turn_id: "t1", approval_id: approvalId, call_id: callId, name: "gmail",
      input: { action: "send", to: "team@example.com" }, summary: "Send the weekly report to team@example.com", ...extra,
    }),
  ];
}

function turnOf(events: AgentChatEvent[]): TurnItem {
  const tl = reduceEvents(EMPTY_TIMELINE, [ev("turn_started", { turn_id: "t1" }), ...events]);
  return tl.items.find((item) => item.type === "turn") as TurnItem;
}

function blockOf(events: AgentChatEvent[], callId = "c1"): ToolBlock {
  return turnOf(events).blocks.find((b) => b.kind === "tool" && b.callId === callId) as ToolBlock;
}

function drawTurn(events: AgentChatEvent[], onDecide = vi.fn()) {
  const store = createAgentChatStore("society");
  store.setState({ activeSessionId: "society:ada" });
  const view = (current: AgentChatEvent[]) => <AgentChatStoreProvider store={store}>
    <MessengerTurn turn={turnOf(current)} avatar={<span />} color="#888888" onDecide={onDecide} />
  </AgentChatStoreProvider>;
  const rendered = render(view(events));
  return { store, onDecide, rerender: (current: AgentChatEvent[]) => rendered.rerender(view(current)) };
}

describe("the approval action card", () => {
  it("asks in plain words with the source, the reason, the caution and Allow once first", async () => {
    const { onDecide } = drawTurn(asking());
    const card = screen.getByTestId("thread-approval");
    expect(card.textContent).toContain("Gmail");
    expect(screen.getByRole("heading", { name: "Use Gmail to send?" })).toBeTruthy();
    expect(card.textContent).toContain("Send the weekly report");
    expect(card.textContent).toContain("“The weekly report is ready”");
    expect(screen.getByTestId("action-card-caution").textContent).toBe("Something from this chat will be sent elsewhere.");
    const buttons = [...card.querySelectorAll("button[data-tone]")].map((b) => [b.textContent, b.getAttribute("data-tone")]);
    expect(buttons).toEqual([["Allow once", "primary"], ["Always allow…", "secondary"], ["Deny", "tertiary"]]);
    expect(screen.getByRole("group", { name: "Needs approval: Use Gmail to send?" })).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-allow")); });
    expect(onDecide).toHaveBeenCalledWith("a1", "allow");
  });

  it("shows the exact request behind a disclosure, copyable", () => {
    drawTurn(asking());
    expect(screen.queryByTestId("action-card-detail")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByTestId("action-card-detail").textContent).toContain("team@example.com");
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
  });

  it("opens a command's disclosure by default", () => {
    drawTurn([
      ev("approval_required", {
        turn_id: "t1", approval_id: "a1", call_id: "c1", name: "Bash", input: { command: "rm -rf build" },
        summary: "rm -rf build", source: { kind: "terminal" }, where: "C:/work/app", why: "", caution: "irreversible",
        detail: "rm -rf build", rule: { scopes: ["chat"], chat: "all" },
      }),
    ]);
    expect(screen.getByRole("heading", { name: "Run this command?" })).toBeTruthy();
    expect(screen.getByText("In C:/work/app")).toBeTruthy();
    expect(screen.getByTestId("action-card-detail").textContent).toBe("rm -rf build");
    expect(screen.getByTestId("action-card-caution").textContent).toBe("There is no undo for this.");
    // A chat-wide "always" says honestly what it does.
    expect(screen.getByTestId("action-card-always").getAttribute("title")).toBe("Stops asking for anything in this chat.");
  });

  it("turns Always allow into a readable rule the person scopes before saving", async () => {
    const { onDecide } = drawTurn(asking());
    fireEvent.click(screen.getByTestId("action-card-always"));
    expect(screen.getByTestId("action-card-rule-text").textContent).toBe("Always allow “send” with Gmail");
    fireEvent.click(screen.getByRole("radio", { name: "All of Gmail" }));
    expect(screen.getByTestId("action-card-rule-text").textContent).toBe("Always allow Gmail");
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-rule-save")); });
    expect(onDecide).toHaveBeenCalledWith("a1", "allow_always", { scope: "agent", breadth: "app" });
  });

  it("saves an always for this chat only", async () => {
    const { onDecide } = drawTurn(asking());
    fireEvent.click(screen.getByTestId("action-card-always"));
    fireEvent.click(screen.getByRole("radio", { name: "This chat" }));
    expect(screen.queryByRole("radio", { name: "All of Gmail" })).toBeNull();
    expect(screen.getByText("Stops asking in this chat until the app restarts.")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-rule-save")); });
    expect(onDecide).toHaveBeenCalledWith("a1", "allow_always", { scope: "chat", breadth: "action" });
  });

  it("never offers an always on a plan", () => {
    drawTurn([
      ev("approval_required", {
        turn_id: "t1", approval_id: "a1", call_id: "c1", name: "ExitPlanMode",
        input: { plan: "1. Add the table" }, summary: "Plan ready", source: { kind: "plan" }, rule: null,
      }),
    ]);
    expect(screen.queryByTestId("action-card-always")).toBeNull();
    expect(screen.getByText("Start building")).toBeTruthy();
    expect(screen.getByText("Add the table")).toBeTruthy();
  });

  it("keeps working on an event written before the card fields existed", async () => {
    const { onDecide } = drawTurn([
      ev("approval_required", { turn_id: "t1", approval_id: "a1", call_id: "c1", name: "Bash", input: { command: "ls" }, summary: "ls" }),
    ]);
    expect(screen.getByRole("heading", { name: "Run this command?" })).toBeTruthy();
    // Even an old card never saves on the first click: the editor asks first.
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-always")); });
    expect(onDecide).not.toHaveBeenCalled();
    expect(screen.getByTestId("action-card-rule-text").textContent).toBe("Always allow this");
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-rule-save")); });
    expect(onDecide).toHaveBeenCalledWith("a1", "allow_always", { scope: "chat", breadth: "action" });
  });

  it("says why an answer was not sent and lets the person try again", async () => {
    const onDecide = vi.fn().mockRejectedValueOnce(new Error("server error"));
    drawTurn(asking(), onDecide);
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-allow")); });
    expect(screen.getByRole("alert").textContent).toContain("server error");
    expect((screen.getByTestId("action-card-allow") as HTMLButtonElement).disabled).toBe(false);
  });
});

const EDIT_CARD = {
  source: { kind: "files" }, where: "~\\Desktop\\proj", why: "", caution: "",
  detail: "{\n  \"file_path\": \"C:\\\\Users\\\\Ada\\\\Desktop\\\\proj\\\\src\\\\app.py\"\n}",
  brief: "Edit src\\app.py",
  rule: { scopes: [], chat: "runtime", narrow: [{ kind: "folder", label: "src" }] },
};

function editAsking(): AgentChatEvent[] {
  return [
    ev("tool_call", { turn_id: "t1", call_id: "c1", name: "Edit", input: { file_path: "C:\\Users\\Ada\\Desktop\\proj\\src\\app.py" } }),
    ev("approval_required", {
      turn_id: "t1", approval_id: "a1", call_id: "c1", name: "Edit",
      input: { file_path: "C:\\Users\\Ada\\Desktop\\proj\\src\\app.py" },
      summary: "Edit C:\\Users\\Ada\\Desktop\\proj\\src\\app.py", ...EDIT_CARD,
    }),
  ];
}

describe("Always allow as a rule editor", () => {
  it("never saves on the first click, and Cancel saves nothing", async () => {
    const { onDecide } = drawTurn(editAsking());
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-always")); });
    expect(onDecide).not.toHaveBeenCalled();
    expect(screen.getByTestId("action-card-rule")).toBeTruthy();
    fireEvent.click(screen.getByTestId("action-card-rule-cancel"));
    expect(screen.queryByTestId("action-card-rule")).toBeNull();
    expect(onDecide).not.toHaveBeenCalled();
    expect(screen.getByTestId("action-card-allow")).toBeTruthy();
  });

  it("offers this folder first and saves it only on Save", async () => {
    const { onDecide } = drawTurn(editAsking());
    fireEvent.click(screen.getByTestId("action-card-always"));
    expect(screen.getByRole("radio", { name: "Only this folder" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("action-card-rule-text").textContent).toBe("Always allow changes to files in src");
    expect(screen.getByTestId("action-card-rule-where").textContent).toBe("Stops asking in this chat until the app restarts.");
    fireEvent.click(screen.getByRole("radio", { name: "This whole tool" }));
    expect(screen.getByTestId("action-card-rule-text").textContent).toBe("Always allow this");
    fireEvent.click(screen.getByRole("radio", { name: "Only this folder" }));
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-rule-save")); });
    expect(onDecide).toHaveBeenCalledWith("a1", "allow_always", { scope: "chat", breadth: "action", narrow: "folder" });
  });

  it("offers this exact command on a terminal card", async () => {
    const { onDecide } = drawTurn([
      ev("approval_required", {
        turn_id: "t1", approval_id: "a1", call_id: "c1", name: "Bash", input: { command: "npm test" },
        summary: "npm test", source: { kind: "terminal" }, where: "", why: "", caution: "", detail: "npm test",
        rule: { scopes: ["chat"], chat: "all", narrow: [{ kind: "command", label: "npm test" }] },
      }),
    ]);
    fireEvent.click(screen.getByTestId("action-card-always"));
    expect(screen.getByTestId("action-card-rule-text").textContent).toBe("Always allow the command npm test");
    fireEvent.click(screen.getByRole("radio", { name: "Everything in this chat" }));
    expect(screen.getByTestId("action-card-rule-text").textContent).toBe("Always allow everything in this chat");
    expect(screen.getByTestId("action-card-rule-where").textContent).toBe("Stops asking for anything in this chat.");
    fireEvent.click(screen.getByRole("radio", { name: "Only this command" }));
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-rule-save")); });
    expect(onDecide).toHaveBeenCalledWith("a1", "allow_always", { scope: "chat", breadth: "action", narrow: "command" });
  });

  it("reads a saved narrow rule back on the outcome line", () => {
    drawTurn([
      ...editAsking(),
      ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "allow_always", scope: "chat" }),
      ev("notice", {
        kind: "approval_rule", turn_id: "t1", approval_id: "a1", rule_kind: "always_allow", scope: "chat",
        pattern: "folder:C:\\Users\\Ada\\Desktop\\proj\\src", app: "Edit", verb: "", still_asks: false,
        narrow: "folder", target: "src",
      }),
    ]);
    const outcome = screen.getByTestId("approval-outcome");
    expect(outcome.textContent).toContain("Always allowed");
    expect(screen.getByTestId("action-card-rule-saved").getAttribute("title"))
      .toBe("Allowed in this chat: Always allow changes to files in src");
  });
});

describe("paths on an approval card", () => {
  it("shows them short on the card and on its outcome line, in full only in the details", () => {
    const { rerender } = drawTurn(editAsking());
    const card = screen.getByTestId("thread-approval");
    expect(card.textContent).toContain("Edit src\\app.py");
    expect(card.textContent).toContain("In ~\\Desktop\\proj");
    expect(card.textContent).not.toContain("C:\\Users\\Ada");
    fireEvent.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByTestId("action-card-detail").textContent).toContain("Users");
    rerender([...editAsking(), ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "allow" })]);
    const outcome = screen.getByTestId("approval-outcome");
    expect(outcome.textContent).toContain("Edit src\\app.py");
    expect(outcome.textContent).not.toContain("C:\\Users\\Ada");
  });

  it("hides the home folder on an event written before the backend shortened paths", () => {
    drawTurn([
      ev("approval_required", {
        turn_id: "t1", approval_id: "a1", call_id: "c1", name: "Write",
        input: { file_path: "C:\\Users\\Ada\\notes.md", cwd: "C:\\Users\\Ada\\proj" },
        summary: "Write C:\\Users\\Ada\\notes.md",
      }),
    ]);
    const card = screen.getByTestId("thread-approval");
    expect(card.textContent).toContain("Write ~\\notes.md");
    expect(card.textContent).toContain("In ~\\proj");
    expect(card.textContent).not.toContain("C:\\Users\\Ada");
  });
});

describe("Esc on an approval card", () => {
  it("denies once, and only the newest open card", async () => {
    const onDecide = vi.fn();
    drawTurn([...asking("old", GMAIL_CARD, "c1"), ...asking("new", GMAIL_CARD, "c2")], onDecide);
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(onDecide).toHaveBeenCalledTimes(1);
    expect(onDecide).toHaveBeenCalledWith("new", "deny");
  });

  it("leaves a key meant for a text field, a modifier or a repeat alone", async () => {
    const onDecide = vi.fn();
    drawTurn(asking(), onDecide);
    const field = document.createElement("textarea");
    document.body.appendChild(field);
    await act(async () => {
      fireEvent.keyDown(field, { key: "Escape" });
      fireEvent.keyDown(window, { key: "Escape", ctrlKey: true });
      fireEvent.keyDown(window, { key: "Escape", repeat: true });
    });
    field.remove();
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("first backs out of the rule chooser", async () => {
    const onDecide = vi.fn();
    drawTurn(asking(), onDecide);
    fireEvent.click(screen.getByTestId("action-card-always"));
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(screen.queryByTestId("action-card-rule")).toBeNull();
    expect(onDecide).not.toHaveBeenCalled();
  });

  it("does nothing once the card is answered", async () => {
    const onDecide = vi.fn();
    drawTurn([...asking(), ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "allow" })], onDecide);
    await act(async () => { fireEvent.keyDown(window, { key: "Escape" }); });
    expect(onDecide).not.toHaveBeenCalled();
  });
});

describe("a settled approval", () => {
  it("stays as one outcome line rebuilt from the event log", () => {
    drawTurn([
      ...asking(),
      ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "allow_always", scope: "agent" }),
      ev("notice", {
        kind: "approval_rule", turn_id: "t1", approval_id: "a1", rule_kind: "always_allow", scope: "agent",
        pattern: "plugin:gmail:send", app: "Gmail", verb: "send", still_asks: false,
      }),
    ]);
    const line = screen.getByTestId("approval-outcome");
    expect(line.getAttribute("data-state")).toBe("allow_always");
    expect(line.textContent).toContain("Always allowed");
    expect(line.textContent).toContain("Send the weekly report");
    expect(screen.getByTestId("action-card-rule-saved").getAttribute("title")).toBe("Rule saved: Always allow “send” with Gmail");
    // The rule notice patched the card; it never became a line of its own.
    expect(screen.queryAllByTestId("approval-outcome")).toHaveLength(1);
    expect(screen.queryByTestId("thread-approval")).toBeNull();
  });

  it("reads a denial in danger ink and opens to what was asked", () => {
    drawTurn([...asking(), ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "deny" })]);
    const toggle = screen.getByRole("button", { name: /Denied/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(screen.getByText("The agent was told no and did not do it.")).toBeTruthy();
    expect(screen.getByTestId("action-card-detail").textContent).toContain("team@example.com");
  });

  it("offers Allow every time on an expired card and saves it as a rule", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      ok: true, approval_id: "a1",
      rule: { kind: "always_allow", pattern: "plugin:gmail:send", app: "Gmail", verb: "send", still_asks: false },
    }), { status: 200 }));
    const { store, rerender } = drawTurn([...asking(), ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "expired" })]);
    store.setState({ timeline: reduceEvents(EMPTY_TIMELINE, [ev("turn_started", { turn_id: "t1" }), ...asking(), ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "expired" })]) });
    expect(screen.getByText("Expired")).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-always-next")); });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/agent-chat/sessions/society%3Aada/approvals/a1/rule");
    expect(JSON.parse(String(init.body))).toEqual({ kind: "always_allow", scope: "agent", breadth: "action" });
    const patched = store.getState().timeline.items.find((i) => i.type === "turn") as TurnItem;
    const block = patched.blocks.find((b) => b.kind === "tool") as ToolBlock;
    expect(block.approval?.rule).toMatchObject({ kind: "always_allow", scope: "agent", pattern: "plugin:gmail:send" });
    rerender([...asking(), ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "expired" }),
      ev("notice", { kind: "approval_rule", turn_id: "t1", approval_id: "a1", rule_kind: "always_allow", scope: "agent", pattern: "plugin:gmail:send", app: "Gmail", verb: "send" })]);
    await waitFor(() => expect(screen.queryByTestId("action-card-always-next")).toBeNull());
    expect(screen.getByTestId("action-card-rule-saved")).toBeTruthy();
  });

  it("offers Check with me every time after an agent-wide always", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({
      ok: true, rule: { kind: "require_approval", pattern: "plugin:gmail:send", app: "Gmail", verb: "send" },
    }), { status: 200 }));
    drawTurn([...asking(), ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "allow_always", scope: "agent" })]);
    await act(async () => { fireEvent.click(screen.getByTestId("action-card-ask-next")); });
    expect(JSON.parse(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body))).toEqual({
      kind: "require_approval", scope: "agent", breadth: "action",
    });
  });
});

describe("secrets in the disclosure", () => {
  // Built at runtime so no credential-shaped literal sits in the source.
  const SECRETS = ["hunter2-correct-horse", ["sk", "proj", "q7".repeat(18)].join("-"), "gh" + "p_" + "Z9".repeat(20)];

  it("are masked on an event without the backend's masked detail", () => {
    drawTurn([
      ev("approval_required", {
        turn_id: "t1", approval_id: "a1", call_id: "c1", name: "mcp__acme__login",
        input: { user: "ada", password: SECRETS[0], api_key: SECRETS[1], note: `token ${SECRETS[2]}` }, summary: "Sign in",
      }),
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Show details" }));
    const detail = screen.getByTestId("action-card-detail").textContent ?? "";
    expect(detail).toContain("ada");
    for (const secret of SECRETS) expect(detail).not.toContain(secret);
    for (const secret of SECRETS) expect(document.body.textContent).not.toContain(secret);
  });

  it("are masked again even if a detail ever carried one", () => {
    const block = blockOf(asking("a1", { ...GMAIL_CARD, detail: `Authorization: Bearer ${"x".repeat(30)} api_key=${SECRETS[1]}` }));
    render(<ApprovalActionCard block={block} onDecide={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByTestId("action-card-detail").textContent).not.toContain(SECRETS[1]);
    expect(screen.getByTestId("action-card-detail").textContent).not.toContain("x".repeat(30));
  });
});
