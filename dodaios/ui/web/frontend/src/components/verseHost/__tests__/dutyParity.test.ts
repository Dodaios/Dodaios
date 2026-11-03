/**
 * Parity of the backend's duty and chat-line ports (`dodaios/verse_host/duty.py`,
 * `chat_lines.py`) with the web Verse's TS code (bridge contract 4.1, BW11).
 * The table `tests/unit/verse_host/parity/duty_cases.json` is asserted by
 * pytest against Python and here against TypeScript.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { dotKindFor, stateKeyFor } from "@/components/agentic/sidePanel/agentStatus";
import { chatLines } from "@/components/society/crewFeeds/deskChat";
import { dutyOf, dutyOfPane } from "@/components/society/verse/ranks/dutyStatus";
import type { WorkspacePaneRow } from "@/lib/agenticIdeApi";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import type { AgentRunState } from "@/components/society/data";

interface Cases {
  agents: { state: AgentRunState; lifecycle: "active" | "paused" | null; asking: boolean; error: boolean; duty: string }[];
  panes: { pane: Record<string, unknown>; dot: string; state_key: string; duty: string }[];
  chat: { events: AgentChatEvent[]; lines: { kind: string; text: string }[] }[];
}

const cases = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../../../../../tests/unit/verse_host/parity/duty_cases.json"), "utf-8"),
) as Cases;

describe("duty status parity with the backend port", () => {
  it.each(cases.agents)("agent %#", (c) => {
    expect(dutyOf({ state: c.state, lifecycle: c.lifecycle ?? undefined }, { asking: c.asking, error: c.error })).toBe(c.duty);
  });

  it.each(cases.panes)("pane %#", (c) => {
    const pane = c.pane as unknown as WorkspacePaneRow;
    const dot = dotKindFor(pane);
    const key = stateKeyFor(pane, dot);
    expect(dot).toBe(c.dot);
    expect(key).toBe(c.state_key);
    expect(dutyOfPane(dot, key)).toBe(c.duty);
  });
});

describe("chat lines parity with the backend port", () => {
  it.each(cases.chat)("chat %#", (c) => {
    // Short texts only: the backend cuts long lines on a word boundary (contract 6).
    expect(chatLines(c.events).map(({ kind, text }) => ({ kind, text }))).toEqual(c.lines);
  });
});
