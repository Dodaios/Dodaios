import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, test } from "vitest";

import { useEventStore } from "@/store/events";

import { isBackgroundNotice } from "./backgroundNotices";
import { groupBackgroundRuns } from "./backgroundLine";
import { ProactiveMessage } from "./ProactiveMessage";
import type { NoticeItem } from "./reduce";

function notice(kind: string, text: string, data: Record<string, unknown> = {}): NoticeItem {
  return {
    type: "notice", id: `n-${kind}`, kind, text, agentName: "", agentId: "", status: "done", tsMs: 1, resolved: "",
    data: { kind, text, ...data },
  };
}

afterEach(cleanup);

describe("ProactiveMessage", () => {
  test("the memory tidy-up reads as the assistant's own message in the words it wrote", () => {
    const words = "Ich habe mein Gedächtnis über dich aufgeräumt und zwei doppelte Einträge zusammengeführt.";  // i18n-allow
    render(<ProactiveMessage item={notice("memory_tidy", "Tidied the memory: merged 2 - review it in Memory.", { voice: words, merged: 2 })} />);
    const message = screen.getByTestId("proactive-message");
    expect(message.textContent).toContain(words);
    expect(message.textContent).not.toMatch(/Tidied the memory|Update from/);
    fireEvent.click(screen.getByTestId("proactive-open-memory"));
    expect(useEventStore.getState().activeSection).toBe("memory");
  });

  test("an older tidy-up without words says its changes in a sentence", () => {
    render(<ProactiveMessage item={notice("memory_tidy", "Tidied the memory: merged 2, retired 1 - review it in Memory.")} />);
    expect(screen.getByTestId("proactive-message").textContent)
      .toContain("I tidied up my memory of you: joined 2 duplicates and dropped one outdated entry.");
  });

  test("never folds into the grey background line", () => {
    const runs = groupBackgroundRuns([notice("memory_tidy", "x"), notice("event_trigger", "y")]);
    expect(runs.map((item) => item.type)).toEqual(["notice", "notice"]);
  });
});

describe("log lines", () => {
  test("a routine's start and a memory write receipt are not drawn in the chat", () => {
    expect(isBackgroundNotice(notice("routine_run", "Daily check"))).toBe(true);
    expect(isBackgroundNotice(notice("memory_updated", "Memory updated"))).toBe(true);
    expect(isBackgroundNotice(notice("memory_tidy", "Tidied"))).toBe(false);
  });
});
