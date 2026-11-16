import type { ToolBlock } from "./reduce";

/**
 * A coding agent compacting its own conversation (the `compaction` event,
 * dodaios/agent_chat/events.py). The reducer files each compaction as a call
 * of this name, so it sits in the turn's work where it happened, runs live
 * while the agent compacts and keeps its time once it is done.
 */
export const COMPACTION_TOOL = "context_compaction";

export interface CompactionInfo {
  /** `auto` when the window was full, `manual` for `/compact`, "" when unsaid. */
  trigger: string;
  tokensBefore: number | null;
  tokensAfter: number | null;
  error: string;
}

export function isCompaction(block: { kind: string; name?: string }): block is ToolBlock {
  return block.kind === "tool" && block.name === COMPACTION_TOOL;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

/** What a finished compaction reported; empty while it runs. */
export function compactionInfo(block: ToolBlock): CompactionInfo {
  let raw: Record<string, unknown> = {};
  try {
    const parsed: unknown = block.output ? JSON.parse(block.output) : {};
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) raw = parsed as Record<string, unknown>;
  } catch {
    raw = {};
  }
  return {
    trigger: typeof raw.trigger === "string" ? raw.trigger : "",
    tokensBefore: count(raw.tokens_before),
    tokensAfter: count(raw.tokens_after),
    error: typeof raw.error === "string" ? raw.error : "",
  };
}
