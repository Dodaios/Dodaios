import { afterEach, describe, expect, it, vi } from "vitest";
import { EMPTY_TIMELINE, reduceEvents, type ToolBlock, type TurnItem } from "../reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { claimKeyboardTarget, TARGET_PRIORITY } from "./keyboardTarget";
import { maskedRequest, maskText } from "./redact";
import { parseApprovalCard, parseSavedRule } from "./approvalInfo";
import { shortenHome } from "./approvalCopy";

let seq = 0;
const ev = (kind: string, payload: Record<string, unknown>): AgentChatEvent => ({ seq: ++seq, ts_ms: seq, kind, payload } as AgentChatEvent);

afterEach(() => { seq = 0; });

describe("the keyboard target", () => {
  it("goes to the highest priority, then the newest claim, and releases cleanly", () => {
    const element = document.createElement("div");
    document.body.appendChild(element);
    const calls: string[] = [];
    const releaseApproval = claimKeyboardTarget({ priority: TARGET_PRIORITY.approval, element: () => element, onEscape: () => calls.push("approval") });
    const releaseQuestion = claimKeyboardTarget({ priority: TARGET_PRIORITY.question, element: () => element, onEscape: () => calls.push("question") });
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    releaseApproval();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    releaseQuestion();
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    element.remove();
    expect(calls).toEqual(["approval", "question"]);
  });

  it("ignores a card no longer in the document", () => {
    const onEscape = vi.fn();
    const release = claimKeyboardTarget({ priority: 2, element: () => document.createElement("div"), onEscape });
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    release();
    expect(onEscape).not.toHaveBeenCalled();
  });

  it("stands back while a dialog is open", () => {
    const element = document.createElement("div");
    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    document.body.append(element, dialog);
    const onEscape = vi.fn();
    const release = claimKeyboardTarget({ priority: 2, element: () => element, onEscape });
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    release();
    element.remove();
    dialog.remove();
    expect(onEscape).not.toHaveBeenCalled();
  });

  it("leaves Esc to an open menu or listbox, but not to one kept hidden", () => {
    const element = document.createElement("div");
    const menu = document.createElement("div");
    menu.setAttribute("role", "menu");
    document.body.append(element, menu);
    const onEscape = vi.fn();
    const release = claimKeyboardTarget({ priority: 2, element: () => element, onEscape });
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(onEscape).not.toHaveBeenCalled();
    menu.hidden = true;
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(onEscape).toHaveBeenCalledTimes(1);
    release();
    element.remove();
    menu.remove();
  });

  it("leaves Esc to a focused control whose popup is open", () => {
    const element = document.createElement("div");
    const button = document.createElement("button");
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "true");
    document.body.append(element, button);
    const onEscape = vi.fn();
    const release = claimKeyboardTarget({ priority: 2, element: () => element, onEscape });
    button.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    release();
    element.remove();
    button.remove();
    expect(onEscape).not.toHaveBeenCalled();
  });
});

describe("masking", () => {
  it("masks secret-named fields and credential shapes, keeps the rest readable", () => {
    const text = maskedRequest({ to: "ada@example.com", password: "hunter2-correct-horse", nested: { auth_token: "abcdefgh12345678" }, max_tokens: 400 });
    expect(text).toContain("ada@example.com");
    expect(text).toContain("400");
    expect(text).not.toContain("hunter2");
    expect(text).not.toContain("abcdefgh12345678");
    // Built at runtime so no credential-shaped literal sits in the source.
    const key = ["sk", "proj", "q7".repeat(14)].join("-");
    expect(maskText(`export OPENAI_API_KEY=${key} && run`)).not.toContain(key);
    expect(maskedRequest({ command: "curl -H 'Authorization: Bearer abcdefghijklmnopqrstuv' x" })).not.toContain("abcdefghijklmnopqrstuv");
  });
});

describe("the reducer and the card fields", () => {
  it("parses the backend's card fields, tolerating junk", () => {
    expect(parseApprovalCard({})).toBeUndefined();
    const info = parseApprovalCard({ source: { kind: "nonsense", app: 3 }, caution: "loud", rule: { scopes: ["agent", "world"], chat: "x" } });
    expect(info?.source).toEqual({ kind: "tool", app: "", verb: "" });
    expect(info?.caution).toBeNull();
    expect(info?.rule?.scopes).toEqual(["agent"]);
    expect(info?.rule?.chat).toBe("");
    expect(parseSavedRule({ rule_kind: "always_allow", scope: "galaxy" })).toBeNull();
  });

  it("records the scope of an always and patches the card with a saved rule", () => {
    const tl = reduceEvents(EMPTY_TIMELINE, [
      ev("turn_started", { turn_id: "t1" }),
      ev("approval_required", { turn_id: "t1", approval_id: "a1", call_id: "c1", name: "gmail", input: {}, summary: "s", source: { kind: "connector", app: "Gmail" } }),
      ev("approval_resolved", { turn_id: "t1", approval_id: "a1", decision: "allow_always", scope: "agent" }),
      ev("notice", { kind: "approval_rule", turn_id: "t1", approval_id: "a1", rule_kind: "always_allow", scope: "agent", pattern: "plugin:gmail", app: "Gmail", verb: "", still_asks: true }),
    ]);
    expect(tl.items).toHaveLength(1);
    const block = (tl.items[0] as TurnItem).blocks[0] as ToolBlock;
    expect(block.approval).toMatchObject({
      decision: "allow_always", scope: "agent", card: { source: { kind: "connector", app: "Gmail" } },
      rule: { kind: "always_allow", scope: "agent", pattern: "plugin:gmail", stillAsks: true },
    });
    expect(tl.pendingApprovals).toEqual([]);
  });
});

describe("short paths and narrow rules", () => {
  it("shows the home folder as ~ and leaves other paths alone", () => {
    const win = String.raw`Edit C:\Users\Ada\Desktop\a.py`;
    expect(shortenHome(win)).toBe(String.raw`Edit ~\Desktop\a.py`);
    expect(shortenHome("open c:/users/ada/notes.md")).toBe("open ~/notes.md");
    expect(shortenHome("cat /home/bob/x.txt and /Users/eve")).toBe("cat ~/x.txt and ~");
    expect(shortenHome(String.raw`C:\Users\Public\x`)).toBe(String.raw`C:\Users\Public\x`);
    expect(shortenHome("/srv/home/bob")).toBe("/srv/home/bob");
    expect(shortenHome("")).toBe("");
  });

  it("parses narrow options and a saved narrow rule, tolerating junk", () => {
    const info = parseApprovalCard({
      source: { kind: "files" }, brief: "Edit src/a.py",
      rule: { scopes: [], chat: "runtime", narrow: [{ kind: "folder", label: "src" }, { kind: "disk", label: "x" }, "junk", { kind: "command" }] },
    });
    expect(info?.brief).toBe("Edit src/a.py");
    expect(info?.rule?.narrow).toEqual([{ kind: "folder", label: "src" }]);
    expect(parseApprovalCard({ source: { kind: "files" }, rule: { scopes: [] } })?.rule?.narrow).toEqual([]);
    expect(parseSavedRule({ rule_kind: "always_allow", scope: "chat", narrow: "command", target: "npm test" }))
      .toMatchObject({ narrow: "command", target: "npm test" });
    expect(parseSavedRule({ rule_kind: "always_allow", scope: "chat", narrow: "planet" })?.narrow).toBeUndefined();
  });
});
