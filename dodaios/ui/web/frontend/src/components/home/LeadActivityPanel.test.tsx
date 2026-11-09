import { describe, expect, it } from "vitest";
import { activityOf } from "./LeadActivityPanel";
import type { TimelineItem } from "@/components/agentchat/reduce";

const t = (key: string) => key;
const turn = (id: string, extra: Record<string, unknown>): TimelineItem => ({
  type: "turn", id, provider: "openai", model: "m", effort: "", runner: "brain", status: "done",
  blocks: [], startedMs: 1, durationMs: null, usage: null, liveUsage: null, costUsd: null, error: null,
  ...extra,
} as TimelineItem);

describe("activityOf", () => {
  it("sorts the conversation into waiting, running and done", () => {
    const items: TimelineItem[] = [
      turn("t1", { blocks: [{ kind: "tool", id: "c1", name: "gmail", approval: { approvalId: "a1", summary: "Send the reply", decision: null } }] }),
      turn("t2", { status: "running" }),
      turn("t3", { background: ["Research agent"] }),
      { type: "notice", id: "n1", kind: "society_result", text: "Flights found\nmore", agentName: "Scout", agentId: "s",
        status: "done", tsMs: 2, data: {}, resolved: "" },
    ];
    const { waiting, running, done } = activityOf(items, t);
    expect(waiting.map((r) => r.text)).toEqual(["Send the reply"]);
    expect(running.map((r) => r.text)).toEqual(["home.activity.answering", "Research agent"]);
    expect(done.map((r) => r.text)).toEqual(["Scout: Flights found"]);
    expect(done[0].messageId).toBe("n1");
  });
});
