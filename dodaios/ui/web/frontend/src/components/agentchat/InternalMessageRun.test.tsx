import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en.json";

import { InternalMessageRun, groupInternalRuns, rosterFaces, runCounterparts, type InternalRunItem } from "./InternalMessageRun";
import type { InternalMessageItem, TimelineItem } from "./reduce";

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => (en.agent_chat as Record<string, string>)[key.split(".")[1]] ?? key,
}));

afterEach(cleanup);

function msg(id: string, tsMs: number, from: string, opts: { to?: string; status?: string } = {}): InternalMessageItem {
  return {
    type: "internal",
    id,
    tsMs,
    message: {
      message_id: id, sender_id: from.toLowerCase(), sender_name: from, sender_kind: "agent",
      text: `Text ${id}`, prompt: "", trace_id: "", status: opts.status ?? "delivered", turn_id: "", error: "",
    } as InternalMessageItem["message"],
    ...(opts.to ? { outgoing: { recipientId: opts.to.toLowerCase(), recipientName: opts.to } } : {}),
  };
}

const user = { type: "user", id: "u1", tsMs: 5_000, text: "hi", attachments: [] } as unknown as TimelineItem;

it("folds back-to-back agent messages into one run and splits on other items or a long pause", () => {
  const rows = groupInternalRuns([
    msg("a", 1_000, "Scout"),
    msg("b", 2_000, "Jarvis", { to: "Scout" }),
    user,
    msg("c", 6_000, "Scout"),
    msg("d", 6_000 + 21 * 60_000, "Scout"),
  ]);
  expect(rows.map((row) => row.type)).toEqual(["internal_run", "user", "internal_run", "internal_run"]);
  expect((rows[0] as InternalRunItem).items.map((item) => item.id)).toEqual(["a", "b"]);
});

it("keeps excluded messages as their own rows", () => {
  const rows = groupInternalRuns([msg("a", 1, "Scout"), msg("b", 2, "Thread")], (item) => item.message.sender_name !== "Thread");
  expect(rows.map((row) => row.type)).toEqual(["internal_run", "internal"]);
});

it("names each counterpart once: the recipient of a sent message, the sender of a received one", () => {
  const people = runCounterparts([msg("a", 1, "Jarvis", { to: "Grok Bot" }), msg("b", 2, "Grok Bot"), msg("c", 3, "Marketing Lead")]);
  expect(people.map((who) => who.name)).toEqual(["Grok Bot", "Marketing Lead"]);
});

it("reads 'Message sent' for one outgoing message", () => {
  render(<InternalMessageRun run={{ type: "internal_run", id: "a", items: [msg("a", 1, "Jarvis", { to: "Grok Bot" })] }} />);
  expect(screen.getByText("Message sent")).toBeTruthy();
  expect(screen.getByText("Grok Bot")).toBeTruthy();
  expect(screen.queryByTestId("agent-message-run-messages")).toBeNull();
});

it("reads 'N messages with A and B', reports failures, and unfolds the messages on click", () => {
  const run: InternalRunItem = {
    type: "internal_run", id: "a",
    items: [
      msg("a", 1, "Jarvis", { to: "Grok Bot" }),
      msg("b", 2, "Grok Bot"),
      msg("c", 3, "Marketing Lead", { status: "failed" }),
    ],
  };
  render(<InternalMessageRun run={run} />);
  expect(screen.getByText("3 messages with")).toBeTruthy();
  expect(screen.getByText("and")).toBeTruthy();
  expect(screen.getByText("· 1 failed")).toBeTruthy();
  fireEvent.click(screen.getByTestId("agent-message-run-toggle"));
  expect(screen.getAllByTestId("agent-message-internal")).toHaveLength(3);
});

it("draws each counterpart from the roster: its own name and identity, so its own pet", () => {
  const roster = [
    { agentId: "viral-marketing", name: "Viral Marketing", tier: "specialist" as const, figure: null, palette: { primary: "#111", secondary: "#222", accent: "#333" } },
    { agentId: "jarvis", name: "Jarvis", tier: "lead" as const, figure: null, palette: { primary: "#111", secondary: "#222", accent: "#333" } },
  ];
  const faces = rosterFaces(roster, (agent) => (agent.tier === "lead" ? "George" : agent.name));
  expect(faces["viral-marketing"].agentId).toBe("viral-marketing");
  expect(faces.jarvis.name).toBe("George");
  render(<InternalMessageRun agentsById={faces} run={{ type: "internal_run", id: "a", items: [
    { ...msg("a", 1, "Viral Marketing"), message: { ...msg("a", 1, "x").message, sender_id: "viral-marketing", sender_name: "old name" } },
  ] }} />);
  expect(screen.getByText("Message from")).toBeTruthy();
  expect(screen.getByText("Viral Marketing")).toBeTruthy();
});
