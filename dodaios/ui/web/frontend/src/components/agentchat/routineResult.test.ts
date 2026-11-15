import { describe, expect, it } from "vitest";

import type { NoticeItem, TimelineItem } from "./reduce";
import { isRoutineResult, routineResultTitle, withoutReportedRoutineStarts } from "./routineResult";

function notice(id: string, kind: string, data: Record<string, unknown>, status = ""): NoticeItem {
  return {
    type: "notice", id, kind, text: String(data.text ?? ""), agentName: "Nova", agentId: "jarvis",
    status, tsMs: 1000, resolved: "", data: { kind, ...data },
  };
}

/** What `dodaios/society/routine_runner.py` posts when a run ends with an answer. */
const result = (id: string, data: Record<string, unknown> = {}, status = "done") =>
  notice(id, "society_result", { source: "routine", text: "Two new issues.", task_id: "task_1", ...data }, status);

/** The "a routine started" line the runner posts when a run begins. */
const started = (id: string, session: string) =>
  notice(id, "routine_run", { session_id: session, agent_id: "jarvis", title: "Daily issue check" });

const user = (id: string): TimelineItem => ({ type: "user", id, text: "hello", attachments: [], tsMs: 500 }) as TimelineItem;

describe("isRoutineResult", () => {
  it("is a routine's finished result, with or without an outcome on it", () => {
    expect(isRoutineResult(result("n1"))).toBe(true);
    expect(isRoutineResult(result("n1", {}, ""))).toBe(true);
  });

  it("is not a run that failed, was skipped or waits: that is background", () => {
    for (const status of ["blocked", "skipped", "waiting"]) expect(isRoutineResult(result("n1", {}, status))).toBe(false);
  });

  it("is not a delegated task's result, another notice or a message", () => {
    expect(isRoutineResult(notice("n1", "society_result", { text: "Done." }, "done"))).toBe(false);
    expect(isRoutineResult(notice("n1", "society_result", { source: "delegation" }, "done"))).toBe(false);
    expect(isRoutineResult(started("n1", "s1"))).toBe(false);
    expect(isRoutineResult(user("u1"))).toBe(false);
  });
});

describe("routineResultTitle", () => {
  it("names the routine, or the standing task when that is what ran", () => {
    expect(routineResultTitle(result("n1", { title: "  Daily issue check " }))).toBe("Daily issue check");
    expect(routineResultTitle(result("n1", { standing_title: "Inbox watch" }))).toBe("Inbox watch");
    expect(routineResultTitle(result("n1", { title: "Daily issue check", standing_title: "Inbox watch" }))).toBe("Daily issue check");
  });

  it("is empty when the notice names nothing", () => {
    expect(routineResultTitle(result("n1"))).toBe("");
    expect(routineResultTitle(result("n1", { title: 42 }))).toBe("");
  });
});

describe("withoutReportedRoutineStarts", () => {
  it("drops the start line of a run whose result is in the chat", () => {
    const items = [user("u1"), started("n1", "s1"), result("n2", { session_id: "s1" })];
    expect(withoutReportedRoutineStarts(items).map((item) => item.id)).toEqual(["u1", "n2"]);
  });

  it("keeps the start line of a run that has not answered here", () => {
    const items = [started("n1", "s1"), started("n2", "s2"), result("n3", { session_id: "s2" })];
    expect(withoutReportedRoutineStarts(items).map((item) => item.id)).toEqual(["n1", "n3"]);
  });

  it("keeps the start line when the result names no run, or did not finish", () => {
    const loose = [started("n1", "s1"), result("n2")];
    expect(withoutReportedRoutineStarts(loose)).toBe(loose);
    const failed = [started("n1", "s1"), result("n2", { session_id: "s1" }, "blocked")];
    expect(withoutReportedRoutineStarts(failed)).toBe(failed);
  });

  it("gives back the same array when nothing is dropped", () => {
    const items = [user("u1"), started("n1", "s1")];
    expect(withoutReportedRoutineStarts(items)).toBe(items);
    const answered = [user("u1"), result("n2", { session_id: "s9" })];
    expect(withoutReportedRoutineStarts(answered)).toBe(answered);
  });
});
