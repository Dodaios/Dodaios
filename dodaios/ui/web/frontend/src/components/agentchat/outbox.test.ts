import { describe, expect, it } from "vitest";

import { outboxEntry, pendingEntries, withOutbox } from "./outbox";
import type { TimelineItem, UserItem } from "./reduce";

function said(id: string, text: string, tsMs: number): UserItem {
  return { type: "user", id, text, attachments: [], tsMs };
}

describe("outbox", () => {
  it("draws a sent message at the foot of its chat until it is recorded", () => {
    const entry = outboxEntry("lead", "hello", [], 10_000);
    const older = said("u-1", "earlier", 1_000);
    expect(withOutbox([older], [entry], "lead").map((item) => item.id)).toEqual(["u-1", entry.id]);
    const recorded: TimelineItem[] = [older, said("u-2", "hello", 10_400)];
    expect(withOutbox(recorded, [entry], "lead")).toBe(recorded);
  });

  it("does not take an identical message from before the send for this one", () => {
    const entry = outboxEntry("lead", "ok", [], 60_000);
    expect(pendingEntries([entry], [said("u-1", "ok", 1_000)])).toEqual([entry]);
  });

  it("lets two identical messages each wait for their own", () => {
    const first = outboxEntry("lead", "ok", [], 10_000);
    const second = outboxEntry("lead", "ok", [], 10_100);
    expect(pendingEntries([first, second], [said("u-1", "ok", 10_300)])).toEqual([second]);
  });

  it("lists the files a message carries, by name", () => {
    const entry = outboxEntry(null, "", [
      { name: "shot.png", reference: "@shot.png", kind: "image", detail: "", described_by: "vision", note: "" },
    ], 1);
    expect(entry.item.attachments).toEqual([{ name: "shot.png", kind: "image", describedBy: "vision" }]);
    expect(withOutbox([], [entry], null)).toEqual([entry.item]);
  });
});
