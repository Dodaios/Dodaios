import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { AgentTimeline, timeStamps } from "./AgentTimeline";
import { EMPTY_TIMELINE, reduceEvents, type TimelineItem } from "./reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";
let seq = 0;
function ev(kind: string, payload: Record<string, unknown>, tsMs = 1000): AgentChatEvent {
 return { seq: ++seq, ts_ms: tsMs, kind, payload } as AgentChatEvent;
}
function draw(events: AgentChatEvent[]) {
 return render(<AgentTimeline items={reduceEvents(EMPTY_TIMELINE, events).items} assistantName="Jarvis" providerLabel={id => id} onDecide={() => undefined} />);
}
afterEach(() => { cleanup(); seq = 0; });
it("replays persisted events through the new shared trace", () => {
 draw([ev("turn_started", { turn_id: "t1" }), ev("tool_call", { turn_id: "t1", call_id: "c1", name: "list_dir", input: { path: "src" } }), ev("tool_result", { turn_id: "t1", call_id: "c1", output: "index.ts", duration_ms: 800 }), ev("turn_finished", { turn_id: "t1", status: "done" })]);
 expect(screen.getByTestId("work-trace")).toBeTruthy();
 // The work stays in view, one quiet line per call.
 expect(screen.getByRole("button", { name: /^Listed src/ })).toBeTruthy();
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
    const image = within(turn).getByTestId("agent-message-image") as HTMLImageElement;
    expect(image.getAttribute("src")).toBe(SHOT.url);
    expect(image.getAttribute("alt")).toBe("shot.png");
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

describe("several orders in one chat", () => {
  it("marks the result of an earlier request instead of drawing a second bubble", () => {
    draw([
      ev("user_message", {
        text: "Continue the original user task using the delegated results below.",
        typed: "Brief the agent in terminal two",
        origin: "background",
      }),
    ]);
    expect(screen.queryByTestId("agent-message-user")).toBeNull();
    const marker = screen.getByTestId("background-result");
    expect(marker.textContent).toContain("Brief the agent in terminal two");
    expect(marker.textContent).not.toContain("Continue the original");
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

it("says who still works on a request whose turn made room for the next message", () => {
  draw([
    ev("turn_started", { turn_id: "t1" }),
    ev("assistant_text", { turn_id: "t1", text: "Sent to the agent in terminal two." }),
    ev("turn_finished", { turn_id: "t1", status: "done", background: ["Agent T2"] }),
  ]);
  expect(screen.getByTestId("turn-background").textContent).toContain("Agent T2");
});
