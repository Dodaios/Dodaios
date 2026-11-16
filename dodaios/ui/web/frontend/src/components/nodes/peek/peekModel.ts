/**
 * What the node window works out without drawing anything.
 */
import { PAGE_NOTICE_KIND, pageCardData } from "@/components/agentchat/PageCard";
import type { TimelineItem } from "@/components/agentchat/reduce";
import { classifyVisual, visualUrl, type VisualArtifact } from "@/hooks/useVisualArtifacts";
import type { OutputSummary } from "@/hooks/useOutputs";

/** One page of a conversation, as the window's previous / next walk it. */
export interface ConversationPage {
  /** `slug::path`. */
  ref: string;
  title: string;
}

/**
 * The pages and nodes a conversation made, each once, in the order they were
 * last posted. A page posted again (made, then revised) takes the place of
 * its last notice, the way the chat draws one card for it.
 */
export function conversationPages(items: readonly TimelineItem[]): ConversationPage[] {
  const pages = new Map<string, ConversationPage>();
  for (const item of items) {
    if (item.type !== "notice" || item.kind !== PAGE_NOTICE_KIND) continue;
    const page = pageCardData(item);
    if (page === null) continue;
    // Deleting first moves a page posted again to the end of the order.
    pages.delete(page.artifact);
    pages.set(page.artifact, { ref: page.artifact, title: page.title });
  }
  return [...pages.values()];
}

/**
 * A file as the stage takes it, made from its address alone. The window
 * draws a page the moment it is asked for, before the library has answered,
 * and still draws one the library does not list. Null for a file the stage
 * cannot draw (no page, picture or PDF).
 */
export function visualFromRef(
  slug: string,
  path: string,
  title: string,
  run: OutputSummary | null,
): VisualArtifact | null {
  const kind = classifyVisual(path);
  if (kind === null) return null;
  const name = path.split("/").pop() ?? path;
  return {
    slug,
    utterance: run?.utterance,
    status: run?.status,
    path,
    name,
    title: title || name,
    kind,
    size: 0,
    mtime: 0,
    url: visualUrl(slug, path),
  };
}

/** The window never takes less room than this, and the node never less than that. */
export const CHAT_MIN_WIDTH = 340;
export const CHAT_DEFAULT_WIDTH = 440;
export const STAGE_MIN_WIDTH = 420;

/**
 * The widest the conversation may be drawn in a window `frameWidth` wide: the
 * node keeps its minimum, and the conversation never takes more than half.
 * Before the window is measured (0) there is no limit to apply.
 */
export function chatMaxWidth(frameWidth: number): number {
  if (frameWidth <= 0) return 720;
  return Math.max(CHAT_MIN_WIDTH, Math.min(Math.floor(frameWidth / 2), frameWidth - STAGE_MIN_WIDTH));
}

/** Too narrow for two columns: the conversation then slides over the node. */
export function isNarrowFrame(frameWidth: number): boolean {
  return frameWidth > 0 && frameWidth < CHAT_MIN_WIDTH + STAGE_MIN_WIDTH;
}
