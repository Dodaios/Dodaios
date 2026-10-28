import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import type { TimelineItem } from "@/components/agentchat/reduce";
import RoutineChat, { splitOpening } from "./RoutineChat";
import type { RoutineChatTarget } from "../chat/routineExecution";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useUiLanguage: () => "en" }));
vi.mock("@/components/agentchat/ChatMarkdown", () => ({ ChatMarkdown: ({ text }: { text: string }) => <p>{text}</p> }));
vi.mock("@/components/agentchat/AgentTimeline", () => ({ AgentTimeline: ({ items }: { items: TimelineItem[] }) => <pre data-testid="selected-transcript">{JSON.stringify(items)}</pre> }));

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const instruction = "Scheduled routine daily. Follow your CURRENT standing instructions and permissions.\nUse your memory and conversation archive for prior results. For information watches, check sources and dates, remember last-seen items, and report only meaningful new findings.\n\nRead mail.";
const events = [
  { seq: 1, ts_ms: 10000, kind: "user_message", payload: { text: instruction } },
  { seq: 2, ts_ms: 10001, kind: "turn_started", payload: { turn_id: "first" } },
  { seq: 3, ts_ms: 10500, kind: "assistant_text", payload: { turn_id: "first", text: "FIRST ONLY" } },
  { seq: 4, ts_ms: 11000, kind: "turn_finished", payload: { turn_id: "first", status: "done" } },
  { seq: 5, ts_ms: 20000, kind: "user_message", payload: { text: "PRIVATE MAIN CHAT" } },
];
const target: RoutineChatTarget = { agentId: "mail", sessionId: "society:mail", title: "Inbox", timestamp: 10000,
  legacy: { taskId: "daily", startedMs: 9900, finishedMs: 11100 }, result: "Saved result" };

test("an old execution loads its own turn without opening a writable main chat", async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ session: { title: "Mail" }, events })));
  const socket = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  vi.stubGlobal("WebSocket", socket);
  render(<RoutineChat target={target} onClose={() => {}} />);
  const transcript = await screen.findByTestId("selected-transcript");
  expect(transcript.textContent).toContain("FIRST ONLY");
  expect(transcript.textContent).not.toContain("PRIVATE MAIN CHAT");
  expect(transcript.textContent).not.toContain("Follow your CURRENT");
  expect(socket).not.toHaveBeenCalled();
  expect(screen.queryByRole("textbox")).toBeNull();
  // The seat names may load the chat catalog; the transcript is one read of its session.
  const sessionReads = fetcher.mock.calls.filter((call: unknown[]) => String(call[0]).startsWith("/api/agent-chat/sessions"));
  expect(sessionReads).toEqual([["/api/agent-chat/sessions/society%3Amail"]]);
  // An old task could succeed through a fallback after its chat attempt failed.
  expect(screen.getByTestId("routine-saved-result").textContent).toContain("Saved result");
});

test("does not duplicate a saved result already present in the selected conversation", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ session: { title: "Mail" }, events }))));
  render(<RoutineChat target={{ ...target, result: "FIRST ONLY" }} onClose={() => {}} />);
  await screen.findByTestId("selected-transcript");
  expect(screen.queryByTestId("routine-saved-result")).toBeNull();
});

test("a missing historical turn shows only that execution's saved result", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ session: { title: "Mail" }, events }))));
  render(<RoutineChat target={{ ...target, legacy: { taskId: "daily", startedMs: 90000, finishedMs: 91000 } }} onClose={() => {}} />);
  await screen.findByText("Saved result");
  expect(screen.queryByTestId("selected-transcript")).toBeNull();
  expect(screen.queryByRole("textbox")).toBeNull();
});

test("a run opens with the routine's name; the scheduler's instructions wait behind a toggle", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ session: { title: "Mail" }, events }))));
  render(<RoutineChat target={target} onClose={() => {}} />);
  const opening = await screen.findByTestId("routine-opening");
  expect(opening.textContent).toContain("Inbox");
  expect(opening.querySelector("details")?.textContent).toContain("Read mail.");
  expect(opening.textContent).not.toContain("Scheduled routine");
});

test("the current scheduler envelope never shows raw in a run", () => {
  const current = "Scheduled routine 96a6671f-0b1c-4f7e-9a51-1c2d3e4f5a6b. Follow your CURRENT standing instructions.\n"
    + "This execution has its own background chat and must honor its permission limits.\n"
    + "Use your memory and conversation archive for prior results. For information watches, check sources and dates, remember last-seen items, and report only meaningful new findings.\n\nSummarize the inbox.";
  const items = [
    { type: "user", id: "u1", text: current, attachments: [], tsMs: 1 },
    { type: "user", id: "u2", text: "And the calendar?", attachments: [], tsMs: 2 },
  ] as unknown as TimelineItem[];
  const { prompt, rest } = splitOpening(items);
  expect(prompt).toBe("Summarize the inbox.");
  expect(rest).toHaveLength(1);
  expect(JSON.stringify(rest)).not.toContain("Scheduled routine");
  // A conversation that is not a routine run keeps its first message.
  expect(splitOpening([items[1]]).prompt).toBeNull();
});
