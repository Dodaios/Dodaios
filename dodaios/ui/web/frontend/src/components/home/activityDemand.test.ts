import { afterEach, describe, expect, it } from "vitest";

import type { TimelineItem } from "@/components/agentchat/reduce";
import { PANEL_KEY, hasActivityDemand, panelOpen, readPanelChoice, writePanelChoice } from "./activityDemand";

const turn = (extra: Record<string, unknown>) =>
  ({ type: "turn", id: "t1", status: "done", blocks: [], ...extra }) as unknown as TimelineItem;

afterEach(() => localStorage.clear());

describe("hasActivityDemand", () => {
  it("is quiet on an empty or finished conversation", () => {
    expect(hasActivityDemand([])).toBe(false);
    expect(hasActivityDemand([turn({})])).toBe(false);
    expect(hasActivityDemand([{ type: "notice", id: "n" } as unknown as TimelineItem])).toBe(false);
  });

  it("sees a running turn and background work", () => {
    expect(hasActivityDemand([turn({ status: "running" })])).toBe(true);
    expect(hasActivityDemand([turn({ background: ["Researcher"] })])).toBe(true);
  });

  it("sees an open approval or question, not a decided one", () => {
    const approval = (decision?: string) => turn({ blocks: [{ kind: "tool", name: "x", approval: { summary: "s", decision } }] });
    expect(hasActivityDemand([approval()])).toBe(true);
    expect(hasActivityDemand([approval("allow")])).toBe(false);
    const question = (closed: boolean) => turn({ blocks: [{ kind: "tool", name: "q", question: { closed, questions: [] } }] });
    expect(hasActivityDemand([question(false)])).toBe(true);
    expect(hasActivityDemand([question(true)])).toBe(false);
  });
});

describe("panelOpen", () => {
  it("is closed by default and opens with demand", () => {
    expect(panelOpen(null, false)).toBe(false);
    expect(panelOpen(null, true)).toBe(true);
  });

  it("lets the person's choice win", () => {
    expect(panelOpen("open", false)).toBe(true);
    expect(panelOpen("closed", true)).toBe(false);
  });
});

describe("the remembered choice", () => {
  it("keeps the existing storage key and values", () => {
    expect(PANEL_KEY).toBe("dodaios.home.activity.v1");
    expect(readPanelChoice()).toBeNull();
    writePanelChoice("closed");
    expect(localStorage.getItem(PANEL_KEY)).toBe("closed");
    expect(readPanelChoice()).toBe("closed");
    localStorage.setItem(PANEL_KEY, "garbage");
    expect(readPanelChoice()).toBeNull();
  });
});
