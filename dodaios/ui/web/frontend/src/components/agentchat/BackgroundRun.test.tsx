import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en.json";
import { useRoutineNavigation } from "@/components/society/chat/routineNavigation";

import { BackgroundRun } from "./BackgroundRun";
import type { BackgroundRunItem } from "./backgroundLine";
import type { RunFace } from "./InternalMessageRun";
import type { NoticeItem } from "./reduce";

const strings = vi.hoisted(() => ({ overrides: {} as Record<string, string> }));

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => strings.overrides[key] ?? (en.agent_chat as Record<string, string>)[key.split(".")[1]] ?? key,
}));

// The memory file viewer loads the file from the backend; a stand-in says which receipt it opened.
vi.mock("@/components/society/chat/MemoryUpdateNotice", async (original) => ({
  ...(await original<typeof import("@/components/society/chat/MemoryUpdateNotice")>()),
  MemoryNoticeViewer: ({ item }: { item: NoticeItem }) => <div data-testid="memory-viewer">{item.id}</div>,
}));

beforeEach(() => useRoutineNavigation.setState({ target: null }));
afterEach(() => {
  cleanup();
  strings.overrides = {};
});

function notice(id: string, kind: string, extra: Partial<NoticeItem> = {}): NoticeItem {
  return { type: "notice", id, tsMs: 1_000, kind, text: "", agentName: "", agentId: "", status: "", data: {}, resolved: "", ...extra };
}

const routine = (id: string, extra: Partial<NoticeItem> = {}) => notice(id, "routine_run", {
  agentId: "jarvis", agentName: "Nova", text: "Look at the issues opened since yesterday",
  data: { title: "Daily issue check", session_id: `run-${id}`, agent_id: "jarvis" }, ...extra,
});
const memory = (id: string, path = "society/jarvis/USER.md") => notice(id, "memory_updated", {
  agentId: "jarvis", agentName: "Nova", status: "done", text: "Memory updated", data: { path },
});
const report = (id: string, extra: Partial<NoticeItem> = {}) => notice(id, "society_result", {
  agentId: "scout", agentName: "Scout", status: "done", text: "Three new issues, one of them a crash.", ...extra,
});

const palette = { primary: "#111", secondary: "#222", accent: "#333" };
const faces: Record<string, RunFace> = {
  scout: { agentId: "scout", name: "Scout", figure: null, palette },
  jarvis: { agentId: "jarvis", name: "Nova", tier: "lead", figure: null, palette },
};

function draw(...items: NoticeItem[]) {
  const run: BackgroundRunItem = { type: "background_run", id: items[0].id, items };
  return render(<BackgroundRun run={run} agentsById={faces} assistantName="Nova" />);
}

it("is one quiet line with no box: a routine's start names the routine and opens its run", () => {
  draw(routine("a"));
  const root = screen.getByTestId("background-run");
  expect(root.getAttribute("data-count")).toBe("1");
  const line = screen.getByTestId("background-run-open");
  expect(line.parentElement!.className).toContain("text-xs");
  expect(line.parentElement!.className).toContain("text-muted-foreground");
  expect(root.className).not.toMatch(/\bbg-|\bborder\b|rounded-lg/);
  expect(within(line).getByText("Routine started")).toBeTruthy();
  expect(within(line).getByText("· Daily issue check")).toBeTruthy();
  // Nothing to unfold: the line opens the run, like the routine line in an agent's chat.
  expect(screen.queryByTestId("background-run-toggle")).toBeNull();
  fireEvent.click(line);
  expect(useRoutineNavigation.getState().target).toEqual({
    agentId: "jarvis", sessionId: "run-a", title: "Daily issue check", timestamp: 1_000,
  });
});

it("names an older routine notice by its first line, and draws plain text when it names no run", () => {
  draw(routine("a", { data: {} }));
  expect(screen.getByText("· Look at the issues opened since yesterday")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

it("reads 'Noted · USER.md' for a memory receipt and opens the file", () => {
  draw(memory("m"));
  const line = screen.getByTestId("background-run-open");
  expect(within(line).getByText("Noted")).toBeTruthy();
  expect(within(line).getByText("· USER.md")).toBeTruthy();
  fireEvent.click(line);
  expect(screen.getByTestId("memory-viewer").textContent).toBe("m");
});

it("opens the assistant's own file for a receipt in its chat that names no agent", () => {
  // The lead's conversation stores memory receipts without an agent id.
  draw(notice("m2", "memory_updated", { status: "done", text: "Memory updated", data: { path: "society/jarvis/MEMORY.md" } }));
  fireEvent.click(screen.getByTestId("background-run-open"));
  expect(screen.getByTestId("memory-viewer").textContent).toBe("m2");
});

it("opens no file for a memory receipt whose path leaves the agent's folder", () => {
  draw(memory("m", "society/scout/../jarvis/USER.md"));
  expect(screen.getByText("Noted")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

it("reads 'Report from Scout' with the agent's face and unfolds the report on click", () => {
  draw(report("r"));
  const toggle = screen.getByTestId("background-run-toggle");
  expect(within(toggle).getByText("Report from")).toBeTruthy();
  expect(within(toggle).getByTestId("background-run-person").textContent).toContain("Scout");
  // The report itself stays folded away.
  expect(screen.queryByText("Three new issues, one of them a crash.")).toBeNull();
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(toggle.getAttribute("aria-label")).toBe("Show what happened in the background");

  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(toggle.getAttribute("aria-label")).toBe("Hide");
  expect(screen.getByTestId("background-run-body").textContent).toContain("Three new issues, one of them a crash.");
  // A lone notice's line is the header: no second copy of it.
  expect(screen.queryByTestId("background-run-row")).toBeNull();

  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByTestId("background-run-items")).toBeNull();
});

it("puts the agent where the translation puts it", () => {
  strings.overrides["agent_chat.bg_report_from"] = "{0} reported";
  draw(report("r"));
  const person = screen.getByTestId("background-run-person");
  const word = screen.getByText("reported");
  expect(person.compareDocumentPosition(word) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("reads 'Update from Nova' with the first line for any other notice, and unfolds a longer text", () => {
  draw(notice("w", "watchdog", { text: "**Something needs a look.**\n- The app was not running for 16 minutes" }));
  const toggle = screen.getByTestId("background-run-toggle");
  expect(within(toggle).getByText("Update from")).toBeTruthy();
  expect(within(toggle).getByTestId("background-run-person").textContent).toContain("Nova");
  expect(within(toggle).getByText("· Something needs a look.")).toBeTruthy();
  fireEvent.click(toggle);
  expect(screen.getByTestId("background-run-body").textContent).toContain("The app was not running for 16 minutes");
});

it("draws a one-line notice from the assistant as plain text: there is nothing more to show", () => {
  draw(notice("w", "learned_skill", { agentId: "jarvis", text: "Learned how to file an expense." }));
  expect(screen.getByText("· Learned how to file an expense.")).toBeTruthy();
  expect(screen.queryByRole("button")).toBeNull();
});

it("counts several notices, names each sender once, reports failures, and lists them on click", () => {
  draw(
    routine("a"),
    memory("b"),
    report("c"),
    notice("d", "watchdog", { text: "Something needs a look.", status: "failed" }),
  );
  const root = screen.getByTestId("background-run");
  expect(root.getAttribute("data-count")).toBe("4");
  const toggle = screen.getByTestId("background-run-toggle");
  expect(within(toggle).getByText("4 updates from")).toBeTruthy();
  // The lead and a notice with no agent are both the assistant.
  const people = within(toggle).getAllByTestId("background-run-person").map((person) => person.textContent);
  expect(people).toEqual(["Nova", "Scout"]);
  expect(within(toggle).getByText("and")).toBeTruthy();
  const failed = within(toggle).getByText("· 1 failed");
  expect(failed.className).toContain("text-destructive");
  expect(screen.queryByTestId("background-run-items")).toBeNull();

  fireEvent.click(toggle);
  const rows = screen.getAllByTestId("background-run-row");
  expect(rows.map((row) => row.tagName)).toEqual(["BUTTON", "BUTTON", "P", "P"]);
  expect(rows[0].textContent).toContain("Routine started");
  expect(rows[1].textContent).toContain("Noted");
  expect(rows[2].textContent).toContain("Report from");
  expect(rows[3].className).toContain("text-destructive");
  // The report shows its text under its row; the short notice says it all in its row.
  expect(screen.getAllByTestId("background-run-body").map((body) => body.textContent)).toEqual(["Three new issues, one of them a crash."]);

  fireEvent.click(rows[0]);
  expect(useRoutineNavigation.getState().target?.sessionId).toBe("run-a");
  fireEvent.click(rows[1]);
  expect(screen.getByTestId("memory-viewer").textContent).toBe("b");
});

it("joins three senders with a comma and 'and'", () => {
  draw(report("a"), report("b", { agentId: "lead-2", agentName: "Marketing Lead" }), routine("c"));
  const toggle = screen.getByTestId("background-run-toggle");
  expect(within(toggle).getAllByTestId("background-run-person").map((person) => person.textContent)).toEqual(["Scout", "Marketing Lead", "Nova"]);
  expect(within(toggle).getByText(",")).toBeTruthy();
  expect(within(toggle).getByText("and")).toBeTruthy();
});

it("carries every notice's id, so a desktop notification can scroll to any of them", () => {
  draw(routine("a"), memory("b"), report("c"));
  const root = screen.getByTestId("background-run");
  expect(root.getAttribute("data-message-id")).toBe("a");
  const hidden = [...root.querySelectorAll<HTMLElement>("span[data-message-id]")];
  expect(hidden.map((span) => span.getAttribute("data-message-id"))).toEqual(["b", "c"]);
  expect(hidden.every((span) => span.hidden)).toBe(true);
});
