import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Transcript } from "@/components/society/chat/AgentChatPanel";
import { EMPTY_TIMELINE, reduceEvents } from "@/components/agentchat/reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import type { SocietyAgent } from "@/components/society/data";

/**
 * The society transcript's run view: time stamps that mark a pause, a
 * "N new" pill for a reader who scrolled up, and the work inspector one
 * click from each turn.
 */

const agent = { agentId: "a1", name: "Scout", tier: "worker" } as unknown as SocietyAgent;
const MIN = 60_000;
const BASE = new Date(2026, 9, 26, 9, 0).getTime();

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>, ts: number): AgentChatEvent {
  seq += 1;
  return { seq, ts_ms: ts, kind, payload } as AgentChatEvent;
}

function exchange(n: number, at: number): AgentChatEvent[] {
  const id = `t${n}`;
  return [
    ev("user_message", { text: `question ${n}` }, at),
    ev("turn_started", { turn_id: id, provider: "openai", runner: "brain" }, at + 1_000),
    ev("tool_call", { turn_id: id, call_id: `c${n}`, name: "Read", input: { file_path: `f${n}.ts` } }, at + 2_000),
    ev("tool_result", { turn_id: id, call_id: `c${n}`, output: "ok", is_error: false }, at + 3_000),
    ev("assistant_text", { turn_id: id, message_id: `m${n}`, text: `answer ${n}` }, at + 4_000),
    ev("turn_finished", { turn_id: id, status: "done", duration_ms: 3_000 }, at + 5_000),
  ];
}

function draw(events: AgentChatEvent[]) {
  const { items } = reduceEvents(EMPTY_TIMELINE, events);
  return render(<Transcript items={items} agent={agent} roster={[]} onDecide={async () => {}} />);
}

function measure(el: HTMLElement, scrollTop: number, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(el, "scrollHeight", { value: scrollHeight, configurable: true });
  Object.defineProperty(el, "clientHeight", { value: clientHeight, configurable: true });
  el.scrollTop = scrollTop;
}

afterEach(() => {
  cleanup();
  seq = 0;
  vi.useRealTimers();
});

describe("transcript time stamps", () => {
  it("stamps the start and every pause of 15 minutes, never inside a reply", () => {
    draw([...exchange(1, BASE), ...exchange(2, BASE + 5 * MIN), ...exchange(3, BASE + 30 * MIN)]);
    const stamps = screen.getAllByTestId("transcript-stamp");
    expect(stamps).toHaveLength(2);
    expect(stamps[0].querySelector("time")?.getAttribute("datetime")).toBe(new Date(BASE).toISOString());
  });
});

describe("catch-up pill", () => {
  it("counts what arrived while the reader was scrolled up, and dismisses", () => {
    const first = exchange(1, BASE);
    const { rerender } = draw(first);
    const el = screen.getByTestId("society-transcript");
    measure(el, 100, 2_000, 400);
    act(() => { fireEvent.scroll(el); });
    // Away from the end with nothing new: just the way back.
    expect(screen.getByTestId("society-scroll-end")).toBeTruthy();
    const more = reduceEvents(EMPTY_TIMELINE, [...first, ...exchange(2, BASE + MIN)]).items;
    rerender(<Transcript items={more} agent={agent} roster={[]} onDecide={async () => {}} />);
    const pill = screen.getByTestId("transcript-new-pill");
    expect(pill.textContent).toContain("2 new messages");
    expect(screen.queryByTestId("society-scroll-end")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByTestId("transcript-new-pill")).toBeNull();
    expect(screen.getByTestId("society-scroll-end")).toBeTruthy();
  });

  it("offers no way back within 80 px of the end", () => {
    draw(exchange(1, BASE));
    const el = screen.getByTestId("society-transcript");
    measure(el, 1_525, 2_000, 400);
    act(() => { fireEvent.scroll(el); });
    expect(screen.queryByTestId("society-scroll-end")).toBeNull();
  });
});

describe("work inspector from the chat", () => {
  it("opens a turn's work beside the conversation and closes again", () => {
    draw(exchange(1, BASE));
    expect(screen.queryByTestId("work-inspector")).toBeNull();
    fireEvent.click(screen.getByTestId("work-disclosure"));
    const pane = screen.getByTestId("work-inspector");
    expect(pane.dataset.turn).toBe("t1");
    // The request that started the turn leads its trace.
    expect(screen.getAllByTestId("work-inspector-row")[0].dataset.kind).toBe("prompt");
    fireEvent.click(screen.getByTestId("work-inspector-close"));
    expect(screen.queryByTestId("work-inspector")).toBeNull();
  });
});

describe("announcer", () => {
  it("says when the agent replies, not what was already there", () => {
    const start = [
      ev("user_message", { text: "hi" }, BASE),
      ev("turn_started", { turn_id: "t1", provider: "openai" }, BASE + 1),
    ];
    const { rerender } = draw(start);
    expect(screen.getByTestId("run-announcer").textContent).toBe("");
    const done = reduceEvents(EMPTY_TIMELINE, [
      ...start,
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Hello!" }, BASE + 2),
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 10 }, BASE + 3),
    ]).items;
    rerender(<Transcript items={done} agent={agent} roster={[]} onDecide={async () => {}} />);
    expect(screen.getByTestId("run-announcer").textContent).toBe("Scout replied.");
  });
});

describe("live turn", () => {
  it("keeps the same turn mounted when it finishes, so the done flourish can play", () => {
    const start = [
      ev("user_message", { text: "hi" }, BASE),
      ev("turn_started", { turn_id: "t1", provider: "openai" }, BASE + 1),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Hello!" }, BASE + 2),
    ];
    const { rerender } = draw(start);
    const running = screen.getByTestId("messenger-turn");
    expect(running.dataset.status).toBe("running");
    const done = reduceEvents(EMPTY_TIMELINE, [
      ...start,
      ev("turn_finished", { turn_id: "t1", status: "done", duration_ms: 10 }, BASE + 3),
    ]).items;
    rerender(<Transcript items={done} agent={agent} roster={[]} onDecide={async () => {}} />);
    const finished = screen.getByTestId("messenger-turn");
    expect(finished).toBe(running);
    expect(finished.dataset.status).toBe("done");
  });
});
