import { describe, expect, it } from "vitest";

import type { TimelineItem } from "@/components/agentchat/reduce";
import { visualUrl } from "@/hooks/useVisualArtifacts";
import {
  CHAT_MIN_WIDTH,
  STAGE_MIN_WIDTH,
  chatMaxWidth,
  conversationPages,
  isNarrowFrame,
  visualFromRef,
} from "./peekModel";

const PLAN = "run-1::tasks/report/artifacts/files/plan.html";
const COSTS = "run-2__node__abc::index.html";

const page = (id: string, artifact: string, text: string): TimelineItem =>
  ({
    type: "notice", id, kind: "report", text, agentName: "", agentId: "",
    status: "", tsMs: 1, data: { kind: "report", artifact }, resolved: "",
  }) as TimelineItem;

describe("the pages of a conversation", () => {
  it("lists each page once, where it was last posted, under its last name", () => {
    const items = [
      { type: "user", id: "u-1" } as TimelineItem,
      page("n-1", PLAN, "Plan"),
      page("n-2", COSTS, "Costs"),
      { type: "turn", id: "t-1" } as TimelineItem,
      // Made, then revised: one page, and it now comes after the sheet.
      page("n-3", PLAN, "Plan, revised"),
      // Another kind of notice, and a page notice that opens nothing.
      { ...page("n-4", COSTS, "Costs"), kind: "chain_result" } as TimelineItem,
      page("n-5", "broken", "Broken"),
    ];
    expect(conversationPages(items)).toEqual([
      { ref: COSTS, title: "Costs" },
      { ref: PLAN, title: "Plan, revised" },
    ]);
    expect(conversationPages([])).toEqual([]);
  });
});

describe("a file drawn from its address alone", () => {
  it("is the page, named by the card until the library answers", () => {
    expect(visualFromRef("run-1", "tasks/report/artifacts/files/plan.html", "Business plan", null)).toMatchObject({
      slug: "run-1",
      path: "tasks/report/artifacts/files/plan.html",
      name: "plan.html",
      title: "Business plan",
      kind: "page",
      url: visualUrl("run-1", "tasks/report/artifacts/files/plan.html"),
    });
    expect(visualFromRef("run-1", "shots/cover.png", "", null)).toMatchObject({ kind: "image", title: "cover.png" });
  });

  it("is nothing for a file the stage cannot draw", () => {
    expect(visualFromRef("run-1", "tasks/t/artifacts/files/notes.md", "Notes", null)).toBeNull();
  });
});

describe("the room the conversation may take", () => {
  it("never takes more than half the window, and leaves the node its minimum", () => {
    expect(chatMaxWidth(1520)).toBe(760);
    expect(chatMaxWidth(900)).toBe(450);
    // A small window: the node's minimum decides, down to the chat's own.
    expect(chatMaxWidth(800)).toBe(800 - STAGE_MIN_WIDTH);
    expect(chatMaxWidth(700)).toBe(CHAT_MIN_WIDTH);
    // Not measured yet: no limit worth applying.
    expect(chatMaxWidth(0)).toBe(720);
  });

  it("calls a window narrow when both columns do not fit", () => {
    expect(isNarrowFrame(CHAT_MIN_WIDTH + STAGE_MIN_WIDTH)).toBe(false);
    expect(isNarrowFrame(CHAT_MIN_WIDTH + STAGE_MIN_WIDTH - 1)).toBe(true);
    expect(isNarrowFrame(0)).toBe(false);
  });
});
