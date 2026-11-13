import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentTimeline, timeStamps } from "./AgentTimeline";
import { messageReceipts } from "./messageReceipt";
import { EMPTY_TIMELINE, reduceEvents, type TimelineItem } from "./reduce";
import type { PictureDisplay } from "./MediaPreview";
import type { AgentChatEvent } from "@/lib/agentChatApi";
let seq = 0;
function ev(kind: string, payload: Record<string, unknown>, tsMs = 1000): AgentChatEvent {
 return { seq: ++seq, ts_ms: tsMs, kind, payload } as AgentChatEvent;
}
function draw(events: AgentChatEvent[], pictures?: PictureDisplay) {
 return render(<AgentTimeline items={reduceEvents(EMPTY_TIMELINE, events).items} assistantName="Jarvis" providerLabel={id => id} onDecide={() => undefined} pictures={pictures} />);
}
afterEach(() => { cleanup(); seq = 0; });
it("replays persisted events through the new shared trace", () => {
 draw([ev("turn_started", { turn_id: "t1" }), ev("tool_call", { turn_id: "t1", call_id: "c1", name: "list_dir", input: { path: "src" } }), ev("tool_result", { turn_id: "t1", call_id: "c1", output: "index.ts", duration_ms: 800 }), ev("turn_finished", { turn_id: "t1", status: "done" })]);
 expect(screen.getByTestId("work-trace")).toBeTruthy();
 // The work stays in view, one quiet line per call.
 expect(screen.getByRole("button", { name: /^Listed src/ })).toBeTruthy();
});
it("closes a coding thread's turn with its time, its usage and the price of a per-token key", () => {
 // The Dodaios chat counts nothing under an answer (maintainer, 2026-11-13,
 // home/ChatStage.test.tsx); every other chat still closes a turn this way.
 const turn = (billedViaKey: boolean) => [ev("user_message", { text: "check the repo" }), ev("turn_started", { turn_id: "t1", provider: "claude-api", model: "claude-opus-5", effort: "high", runner: "claude-cli" }), ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Done." }), ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 12_000, usage: { input_tokens: 2, output_tokens: 219 }, cost_usd: 0.8483, billed_via_key: billedViaKey })];
 draw(turn(true));
 const footer = within(screen.getByTestId("work-trace")).getAllByRole("status").at(-1)!;
 expect(footer.textContent).toContain("12s");
 // Output only: the input side of a CLI re-counts the whole conversation.
 expect(footer.textContent).toContain("219");
 expect(footer.textContent).toContain("$0.8483");
 cleanup();
 // A subscription seat's turn costs nothing extra, so it shows no price.
 draw(turn(false));
 expect(within(screen.getByTestId("work-trace")).getAllByRole("status").at(-1)!.textContent).not.toContain("$");
});
describe("the person's turn with files", () => {
  const SHOT = {
    name: "shot.png",
    kind: "image",
    described_by: "none",
    url: "/api/agentic-ide/workspaces/ide_1/file?path=.jarvis%2Fdrops%2Fshot.png",
  };

  it("draws an image that can be fetched as the picture itself", () => {
    // The complaint (maintainer, 2026-08-27): a screenshot dropped on a pane
    // showed up in the person's turn as "### shot.png - '.jarvis/drops/…'".
    // With a url, the turn shows the person's sentence and the picture.
    draw([ev("user_message", { text: "## Task\nlook", typed: "look at this", attachments: [SHOT] })]);
    const turn = screen.getByTestId("agent-message-user");
    expect(turn.textContent).toContain("look at this");
    expect(turn.textContent).not.toContain("## Task");
    const preview = within(turn).getByTestId("agent-message-image");
    const image = within(preview).getByRole("img", { name: "shot.png" });
    expect(image.getAttribute("src")).toBe(SHOT.url);
    expect(image.getAttribute("alt")).toBe("shot.png");
    fireEvent.click(within(preview).getByRole("button"));
    expect(within(screen.getByRole("dialog")).getByRole("img", { name: "shot.png" }).getAttribute("src"))
      .toBe(SHOT.url);
  });

  it("draws the picture above the person's words, also in the Dodaios chat", () => {
    // The person's request (2026-11-13): a picture they send is shown, not
    // listed as a download, and it stands on top of the message. The
    // Dodaios chat lists only the pictures in answers as files.
    draw([ev("user_message", { text: "## Task\nlook", typed: "look at this", attachments: [SHOT] })], "files");
    const turn = screen.getByTestId("agent-message-user");
    const image = within(turn).getByRole("img", { name: "shot.png" });
    expect(image.getAttribute("src")).toBe(SHOT.url);
    expect(within(turn).queryByRole("link", { name: /shot\.png/ })).toBeNull();
    const pictures = within(turn).getByTestId("agent-message-pictures");
    const words = within(turn).getByText("look at this");
    expect(pictures.compareDocumentPosition(words) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(pictures.contains(words)).toBe(false);
  });

  it("draws a picture sent without words and no empty bubble", () => {
    draw([ev("user_message", { text: "", attachments: [SHOT] })], "files");
    const turn = screen.getByTestId("agent-message-user");
    expect(within(turn).getByRole("img", { name: "shot.png" })).toBeTruthy();
    expect(turn.querySelector(".lead-bubble-own, .jarvis-user-bubble")).toBeNull();
  });

  it("keeps the chip for a file with nothing to draw", () => {
    draw([
      ev("user_message", {
        text: "read these",
        attachments: [
          { name: "notes.md", kind: "text", described_by: "extraction" },
          { name: "front-page.png", kind: "image", described_by: "vision" },
        ],
      }),
    ]);
    const turn = screen.getByTestId("agent-message-user");
    expect(within(turn).queryByTestId("agent-message-image")).toBeNull();
    expect(turn.textContent).toContain("notes.md");
    expect(turn.textContent).toContain("front-page.png");
    // Fill bubble, not inverted cream (`bg-foreground/70` on near-black).
    expect(turn.querySelector(".jarvis-user-bubble")).not.toBeNull();
  });
});

describe("timeStamps", () => {
  const MIN = 60_000;
  const user = (id: string, tsMs: number) =>
    ({ type: "user", id, text: id, attachments: [], tsMs }) as TimelineItem;

  it("stamps the first message and every one after a 20-minute pause", () => {
    const t0 = new Date(2026, 9, 1, 9, 0).getTime();
    const items = [user("a", t0), user("b", t0 + MIN), user("c", t0 + 5 * MIN), user("d", t0 + 40 * MIN)];
    expect([...timeStamps(items, new Date(2026, 9, 1, 12, 0)).keys()]).toEqual(["a", "d"]);
  });

  it("leads with the date when the message is not from today", () => {
    const t0 = new Date(2026, 8, 24, 8, 13).getTime();
    expect(timeStamps([user("a", t0)], new Date(2026, 9, 1)).get("a")).toContain(",");
  });
});

describe("the receipt under the person's message", () => {
  const user = (id: string, tsMs: number, origin?: "control" | "background") =>
    ({ type: "user", id, text: id, attachments: [], tsMs, ...(origin ? { origin } : {}) }) as TimelineItem;
  const turn = (id: string, startedMs: number) => ({ type: "turn", id, startedMs, blocks: [] }) as unknown as TimelineItem;

  it("is sent until the answering turn starts, and read from then on", () => {
    const receipts = messageReceipts([user("a", 1000), turn("t1", 3000), user("b", 9000)]);
    expect(receipts.get("a")).toEqual({ read: true, atMs: 3000 });
    expect(receipts.get("b")).toEqual({ read: false, atMs: 9000 });
  });

  it("gives the turn to the newest message, and none to a command or an earlier request's result", () => {
    const receipts = messageReceipts([user("a", 1000), user("b", 2000), turn("t1", 3000), user("c", 4000, "background"), turn("t2", 5000)]);
    expect(receipts.get("a")).toEqual({ read: false, atMs: 1000 });
    expect(receipts.get("b")).toEqual({ read: true, atMs: 3000 });
    expect(receipts.has("c")).toBe(false);
  });

  it("stamps a turn without a recorded start with the message's own time", () => {
    expect(messageReceipts([user("a", 1000), turn("t1", 0)]).get("a")).toEqual({ read: true, atMs: 1000 });
  });

  const at = new Date(2026, 10, 12, 21, 56).getTime();
  const conversation = (...more: AgentChatEvent[]) =>
    reduceEvents(EMPTY_TIMELINE, [ev("user_message", { text: "hello" }, at), ...more]).items;
  const show = (items: TimelineItem[], bubbles: boolean) =>
    render(<AgentTimeline items={items} assistantName="Dodaios" providerLabel={(id) => id} onDecide={() => undefined} bubbles={bubbles} />);

  it("says when the message was sent, under its bubble, in the conversation look", () => {
    show(conversation(), true);
    const receipt = screen.getByTestId("agent-message-receipt");
    expect(receipt.getAttribute("data-read")).toBe("false");
    expect(receipt.textContent).toMatch(/^Sent .*56/);
    // The message itself stays the bubble's words alone.
    expect(screen.getByTestId("agent-message-user").textContent).toBe("hello");
  });

  it("says when it was read once the assistant took it up", () => {
    show(conversation(ev("turn_started", { turn_id: "t1" }, at + 2 * 60_000)), true);
    const receipt = screen.getByTestId("agent-message-receipt");
    expect(receipt.getAttribute("data-read")).toBe("true");
    expect(receipt.textContent).toMatch(/^Read .*58/);
  });

  it("stays out of the document look", () => {
    show(conversation(ev("turn_started", { turn_id: "t1" }, at + 1000)), false);
    expect(screen.queryByTestId("agent-message-receipt")).toBeNull();
  });
});

describe("several orders in one chat", () => {
  it("draws neither a bubble nor a line for the result of an earlier request", () => {
    draw([
      ev("user_message", {
        text: "Continue the original user task using the delegated results below.",
        typed: "Brief the agent in terminal two",
        origin: "background",
      }),
    ]);
    expect(screen.queryByTestId("agent-message-user")).toBeNull();
    expect(screen.queryByText(/Brief the agent in terminal two/)).toBeNull();
    expect(screen.queryByText(/Continue the original/)).toBeNull();
  });

  it("shows a message waiting behind the running turn until it starts", () => {
    const queued = ev("notice", { kind: "message_queued", queue_id: "q1", text: "and this too" });
    draw([queued]);
    expect(screen.getByTestId("message-queued").textContent).toContain("and this too");
    cleanup();
    draw([queued, ev("notice", { kind: "message_dequeued", queue_id: "q1", status: "sent" })]);
    expect(screen.queryByTestId("message-queued")).toBeNull();
  });
});

it("draws no small-print line for work a turn left running in the background", () => {
  draw([
    ev("turn_started", { turn_id: "t1" }),
    ev("assistant_text", { turn_id: "t1", text: "Sent to the agent in terminal two." }),
    ev("turn_finished", { turn_id: "t1", status: "done", background: ["Agent T2"] }),
  ]);
  expect(screen.getByText("Sent to the agent in terminal two.")).toBeTruthy();
  expect(screen.queryByText(/Agent T2/)).toBeNull();
});

describe("the turn header's seat", () => {
  it("names the provider and model by their readable names", () => {
    const events = [
      ev("turn_started", { turn_id: "s1", provider: "claude-api", model: "claude-sonnet-5-5" }),
      ev("assistant_text", { turn_id: "s1", message_id: "m", text: "ok" }),
      ev("turn_finished", { turn_id: "s1", status: "done" }),
    ];
    render(<AgentTimeline items={reduceEvents(EMPTY_TIMELINE, events).items} assistantName="Mailbox"
      providerLabel={(id) => (id === "claude-api" ? "Anthropic Claude" : id)}
      modelLabel={(_p, model) => (model === "claude-sonnet-5-5" ? "Claude Sonnet 5.5" : model)}
      onDecide={() => undefined} />);
    const turn = screen.getByTestId("agent-turn");
    expect(turn.textContent).toContain("Anthropic Claude · Claude Sonnet 5.5");
    expect(turn.textContent).not.toContain("claude-sonnet-5-5");
  });
});

describe("a delegated agent's result nobody answered", () => {
  const RESULT = {
    kind: "coding_result", agent_name: "Claude Code", assignment_id: "a1", status: "completed",
    text: "Claude Code has finished: # Review of the five pull requests. None of them can be merged as",
    report: "{\"request\":\"Review the pull requests\",\"report\":\"# Review of the five pull requests\"}",
  };

  it("is one line that opens the agent's thread, without the agent's report", () => {
    draw([ev("notice", { ...RESULT, thread_id: "t1" })]);
    const line = screen.getByTestId("coding-thread-activity");
    expect(line.textContent).toContain("Claude Code is finished");
    expect(line.textContent).toContain("Open thread");
    expect(document.body.textContent).not.toContain("has finished:");
    expect(document.body.textContent).not.toContain("Review of the five pull requests");
  });

  it("is a plain line for a notice that names no thread, a failed one in the warning colour", () => {
    draw([ev("notice", { ...RESULT, status: "failed" })]);
    const line = screen.getByTestId("agent-result-line");
    expect(line.textContent).toBe("Claude Code failed");
    expect(line.className).toContain("text-destructive");
    expect(document.body.textContent).not.toContain("has finished:");
  });
});
