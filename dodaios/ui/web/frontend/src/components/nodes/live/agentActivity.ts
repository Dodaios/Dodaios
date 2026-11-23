/**
 * What the agent is doing between its edits, for the tag at its cursor.
 *
 * While an agent builds a node, its turn runs in a conversation: it thinks,
 * reads, searches, and now and then writes the node. The writes play as the
 * build itself; everything in between was a blank "is working…". This reads
 * the running turn of the conversation the node is being built from and says
 * the latest step in the words the conversation's own work trace uses
 * ("Searched the web", "Read sources.md"), or the headline of the agent's
 * thinking when its runner shows it ("Thinking…" when it only says that it
 * thinks).
 *
 * The node window shows that conversation beside the node (`nodePeek`), so
 * its chat store is the one to read; elsewhere the lead's store is tried. A
 * conversation that is not loaded gives "" and the tag keeps its plain line.
 */
import { useCallback } from "react";

import { runningTurn, type ReasoningBlock, type Timeline, type ToolBlock } from "@/components/agentchat/reduce";
import { callOf, type Translate } from "@/components/agentchat/traceEntries";
import { useT } from "@/i18n";
import { useAgentChatStore } from "@/store/agentChat";
import { useNodePeek } from "@/store/nodePeek";

/** The longest step the tag shows; longer ones end in an ellipsis. */
const MAX_STEP_CHARS = 64;
/** The tools that write nodes: their calls are the build itself, not a step between edits. */
const NODE_WRITERS = /(^|[_/.-])(node|whiteboard|clip)$/i;

function oneLine(text: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > MAX_STEP_CHARS ? `${flat.slice(0, MAX_STEP_CHARS - 1).trimEnd()}…` : flat;
}

/**
 * The headline of a thought: a bold title its runner gives it ("**Planning
 * the table**"), else its last line, without Markdown marks.
 */
export function thoughtHeadline(text: string): string {
  const titles = [...text.matchAll(/\*\*([^*\n]{3,80})\*\*/g)];
  if (titles.length > 0) return oneLine(titles[titles.length - 1][1]);
  const lines = text.split(/\n+/).map((line) => line.replace(/[#>*_`-]+/g, " ").trim()).filter(Boolean);
  return lines.length > 0 ? oneLine(lines[lines.length - 1]) : "";
}

/** Is this call one of the tools that write the node (the build plays it already)? */
export function writesNodes(name: string): boolean {
  return NODE_WRITERS.test(name.trim());
}

/** The latest step of the running turn in `timeline`, in words; "" when there is none to tell. */
export function activityOf(timeline: Timeline | null, t: Translate, lang: string): string {
  if (!timeline) return "";
  const turn = runningTurn(timeline);
  if (!turn) return "";
  for (let i = turn.blocks.length - 1; i >= 0; i -= 1) {
    const block = turn.blocks[i];
    if (block.kind === "reasoning") {
      const thought = block as ReasoningBlock;
      const headline = thought.text ? thoughtHeadline(thought.text) : "";
      if (headline) return headline;
      if (thought.live) return t("agent_chat.thinking");
      continue;
    }
    if (block.kind === "tool") {
      const call = block as ToolBlock;
      // The node's own writes are the build; the step before them is what to tell.
      if (writesNodes(call.name)) continue;
      const line = callOf(call, "running", t, lang);
      return oneLine(line.detail ? `${line.text} · ${line.detail}` : line.text);
    }
  }
  return "";
}

/**
 * The agent's latest step in the conversation `sessionId` builds from, for
 * the tag at its cursor; "" when that conversation is not loaded here.
 */
export function useAgentActivity(sessionId: string): string {
  const t = useT();
  const lang = t("trace_report.locale");
  const peekChat = useNodePeek((s) => s.peek?.chat ?? null);
  const chat = peekChat ?? useAgentChatStore;
  const pick = useCallback(
    (s: { activeSessionId: string | null; timeline: Timeline }) =>
      sessionId && s.activeSessionId === sessionId ? activityOf(s.timeline, t, lang) : "",
    [sessionId, t, lang],
  );
  return chat(pick);
}
