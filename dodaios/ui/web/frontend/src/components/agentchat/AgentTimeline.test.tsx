import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgentTimeline, timeStamps } from "./AgentTimeline";
import { messageReceipts } from "./messageReceipt";
import { EMPTY_TIMELINE, reduceEvents, type NoticeItem, type TimelineItem } from "./reduce";
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

  it("draws several pictures as small tiles side by side in one row", () => {
    // The person's request (2026-11-16): two app shots stood huge and
    // stacked over the message. Every picture is the same small tile,
    // cropped to fill it, in one row that wraps; a click opens it in full.
    const shots = [
      SHOT,
      { ...SHOT, url: `${SHOT.url}&n=2` },
      { ...SHOT, name: "wide.png", url: "/api/outputs/wide.png" },
      { ...SHOT, name: "tall.png", url: "/api/outputs/tall.png" },
    ];
    draw([ev("user_message", { text: "compare these", attachments: shots })], "files");
    const turn = screen.getByTestId("agent-message-user");
    const row = within(turn).getByTestId("agent-message-pictures");
    expect(row.className).toContain("flex-wrap");
    expect(row.className).toContain("justify-end");
    // A picture sent twice under one name is still drawn twice.
    const tiles = within(row).getAllByTestId("agent-message-image");
    expect(tiles).toHaveLength(4);
    for (const tile of tiles) {
      const button = within(tile).getByRole("button");
      expect(button.className).toContain("h-32");
      expect(button.className).toContain("w-44");
      const image = within(tile).getByRole("img");
      expect(image.className).toContain("object-cover");
      expect(image.className).not.toContain("object-contain");
    }
    fireEvent.click(within(tiles[2]).getByRole("button"));
    expect(within(screen.getByRole("dialog")).getByRole("img", { name: "wide.png" }).className)
      .toContain("object-contain");
  });

  it("keeps a tile in the row for a picture that will not load", () => {
    draw([ev("user_message", { text: "two", attachments: [SHOT, { ...SHOT, name: "gone.png", url: "/api/outputs/gone.png" }] })], "files");
    const tiles = within(screen.getByTestId("agent-message-pictures")).getAllByTestId("agent-message-image");
    fireEvent.error(within(tiles[1]).getByRole("img"));
    const broken = within(tiles[1]).getByRole("status");
    expect(broken.className).toContain("h-32");
    expect(broken.className).toContain("w-44");
    expect(broken.textContent).toContain("gone.png");
    expect(within(broken).getByRole("button")).toBeTruthy();
    expect(within(tiles[0]).getByRole("img", { name: "shot.png" })).toBeTruthy();
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

describe("a routine's result", () => {
  const at = new Date(2026, 10, 15, 8, 0).getTime();
  const notice = (id: string, kind: string, data: Record<string, unknown>, tsMs: number, status = ""): NoticeItem => ({
    type: "notice", id, kind, text: String(data.text ?? ""), agentName: "Nova", agentId: "jarvis",
    status, tsMs, resolved: "", data: { kind, agent_id: "jarvis", agent_name: "Nova", ...data },
  });
  /** What the routine runner posts into the owner's chat when a run answers. */
  const result = (id: string, session: string, tsMs = at + 60_000) => notice(id, "society_result", {
    status: "done", source: "routine", text: "Two new issues since yesterday.", task_id: "task_1",
    session_id: session, title: "Daily issue check",
  }, tsMs, "done");
  /** The "a routine started" line it posts when a run begins. */
  const started = (id: string, session: string, tsMs = at) => notice(id, "routine_run", {
    session_id: session, title: "Daily issue check", text: "Check the open issues on GitHub.",
  }, tsMs);
  const show = (items: TimelineItem[], bubbles = true) =>
    render(<AgentTimeline items={items} assistantName="Nova" providerLabel={(id) => id} onDecide={() => undefined} bubbles={bubbles} />);

  it("is the assistant's own message in the conversation look, never the muted card", () => {
    show([result("n1", "run_s1")]);
    const message = screen.getByTestId("routine-result");
    expect(message.getAttribute("data-look")).toBe("lead");
    expect(message.getAttribute("data-message-id")).toBe("n1");
    expect(within(message).getByTestId("lead-bubble").textContent).toBe("Two new issues since yesterday.");
    // The card for an agent reporting back is headed with who reported.
    expect(screen.queryByText("Nova is done")).toBeNull();
    expect(screen.getAllByText("Two new issues since yesterday.")).toHaveLength(1);
  });

  it("reads as plain type, under the same line, in the document look", () => {
    show([result("n1", "run_s1")], false);
    const message = screen.getByTestId("routine-result");
    expect(message.getAttribute("data-look")).toBe("document");
    expect(within(message).queryByTestId("lead-bubble")).toBeNull();
    expect(within(message).getByTestId("routine-result-line").textContent).toBe("Routine · Daily issue check");
    expect(screen.queryByText("Nova is done")).toBeNull();
  });

  it("takes the place of its run's start line; another run's start line stays", () => {
    show([started("n1", "run_s1"), started("n2", "run_s2", at + 1000), result("n3", "run_s1")]);
    expect(document.querySelector('[data-message-id="n1"]')).toBeNull();
    expect(document.querySelector('[data-message-id="n2"]')).toBeTruthy();
    expect(document.querySelector('[data-message-id="n3"]')?.getAttribute("data-testid")).toBe("routine-result");
  });
});

describe("a ritual's card", () => {
  /** What `dodaios/rituals/service.py` posts when a ritual starts, and later. */
  const card = (more: Record<string, unknown> = {}) => ev("notice", {
    kind: "society_result", source: "ritual", status: "done", agent_name: "Nova",
    ritual_id: "rit_1", ritual_title: "Good morning", via: "voice", text: "", push: false, ...more,
  });
  const show = (events: AgentChatEvent[]) =>
    render(<AgentTimeline items={reduceEvents(EMPTY_TIMELINE, events).items} assistantName="Nova" providerLabel={(id) => id} onDecide={() => undefined} bubbles />);

  it("is the assistant's answer to the phrase, under a line that names the ritual", () => {
    show([card({ text: "## News\n\n- One thing happened." })]);
    const message = screen.getByTestId("routine-result");
    expect(within(message).getByTestId("routine-result-line").textContent).toBe("“Good morning” started");
    expect(within(message).getByTestId("lead-bubble").textContent).toContain("One thing happened.");
  });

  it("says that the rest follows when nothing was ready, also without words of its own", () => {
    show([card({ pending: true })]);
    const message = screen.getByTestId("routine-result");
    expect(within(message).getByTestId("lead-bubble").textContent).toBe("The rest is being gathered and follows shortly.");
  });

  it("is its line alone when it owes nothing and has nothing to say", () => {
    show([card({ pending: false })]);
    const message = screen.getByTestId("routine-result");
    expect(within(message).queryByTestId("lead-bubble")).toBeNull();
    expect(message.textContent).toBe("“Good morning” started");
  });

  it("brings what was gathered in a second message, or says that nothing could be", () => {
    show([
      card({ late: true, text: "- One thing happened." }),
      card({ late: true, status: "failed", text: "No model answered." }),
    ]);
    expect(screen.getAllByTestId("routine-result-line").map((line) => line.textContent))
      .toEqual(["“Good morning”: what was gathered", "“Good morning”: gathering failed"]);
    expect(screen.getByText("One thing happened.")).toBeTruthy();
    expect(screen.getByText("No model answered.")).toBeTruthy();
  });

  it("is never folded into the quiet line of background work", () => {
    show([
      ev("notice", { kind: "memory_learned", text: "Noted something." }, 1000),
      card({ pending: true }),
      ev("notice", { kind: "memory_learned", text: "Noted more." }, 1200),
    ]);
    expect(screen.getAllByTestId("routine-result")).toHaveLength(1);
  });
});

describe("the conversation look's time stamps", () => {
  afterEach(() => { vi.useRealTimers(); });
  const user = (id: string, tsMs: number) =>
    ({ type: "user", id, text: `message ${id}`, attachments: [], tsMs }) as TimelineItem;
  const stampOf = (tsMs: number) => {
    render(<AgentTimeline items={[user("a", tsMs)]} assistantName="Nova" providerLabel={(id) => id} onDecide={() => undefined} bubbles />);
    return screen.getByTestId("agent-time-stamp").textContent ?? "";
  };

  it("say the day in words: today, yesterday", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 10, 15, 12, 0));
    expect(stampOf(new Date(2026, 10, 15, 11, 10).getTime())).toMatch(/^Today \d{1,2}:10/);
    cleanup();
    expect(stampOf(new Date(2026, 10, 14, 8, 57).getTime())).toMatch(/^Yesterday \d{1,2}:57/);
  });
});
