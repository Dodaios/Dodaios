import { useEffect, useState } from "react";
import { Code2 } from "lucide-react";
import { AgentMark } from "@/components/agentic/AgentMark";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { fetchThreadLink, type ThreadLinkInfo } from "@/lib/agentChatApi";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { openCodingThread } from "./openCodingThread";

/** How long a thread's title and agent are taken as read before asking again. */
const FRESH_MS = 30_000;

interface Entry {
  info?: ThreadLinkInfo;
  at: number;
  pending?: Promise<ThreadLinkInfo>;
}

const entries = new Map<string, Entry>();

/** Read one thread link, sharing the request between every chip that shows it. */
function readThreadLink(ref: string): Promise<ThreadLinkInfo> {
  const entry = entries.get(ref) ?? { at: 0 };
  if (entry.pending) return entry.pending;
  if (entry.info && Date.now() - entry.at < FRESH_MS) return Promise.resolve(entry.info);
  const pending = fetchThreadLink(ref)
    .then((info) => {
      entries.set(ref, { info, at: Date.now() });
      return info;
    })
    .catch((error: unknown) => {
      // Keep what was known: a failed refresh must not turn a link into text.
      entries.set(ref, { info: entry.info, at: 0 });
      throw error;
    });
  entries.set(ref, { ...entry, pending });
  return pending;
}

export function resetThreadLinksForTests(): void {
  entries.clear();
}

/** Link words that only repeat an address: a code (`#3f9a2c`), a session id or `thread:…`. */
export function onlyAnAddress(words: string): boolean {
  const text = words.trim();
  return !text || /^#?[0-9a-f]{4,64}$/i.test(text) || /^thread:/i.test(text);
}

/**
 * A coding agent named in a chat answer, with the coding agent's logo behind
 * the words. A click opens the thread in the Agentic IDE; resting the pointer
 * on it names the thread.
 *
 * `threadRef` is the thread's session id or its code. `words` are what the
 * answer wrote inside its sentence ("A [Claude Code agent](thread:…) is on
 * it"): they stay as written, so the link reads as part of the sentence.
 * Without words of its own (a bare code, or the link the chat adds under an
 * answer that did not link the agent) it shows the thread's current title,
 * and `label` until that is known. A thread that no longer exists leaves
 * plain text. A link whose words are only the code ("#bddece", see
 * `linkBareThreadCodes`) stays plain text until the thread is found: such a
 * code may name no thread at all.
 */
export function CodingAgentLink({ threadRef, label, words = "" }: { threadRef: string; label: string; words?: string }) {
  const t = useT();
  const [info, setInfo] = useState<ThreadLinkInfo | undefined>(() => entries.get(threadRef)?.info);
  useEffect(() => {
    let live = true;
    setInfo(entries.get(threadRef)?.info);
    readThreadLink(threadRef).then((next) => { if (live) setInfo(next); }).catch(() => undefined);
    return () => { live = false; };
  }, [threadRef]);

  if (info && !info.found) return <span data-testid="coding-agent-link-gone">{words || label}</span>;
  if (!info && label.trim().toLowerCase() === `#${threadRef}`) return <span data-testid="coding-agent-link-pending">{label}</span>;
  const title = info?.title || label || t("ide_threads.new_thread");
  const shown = onlyAnAddress(words) ? title : words.trim();
  const open = () => {
    if (info?.session_id) { openCodingThread(info.session_id); return; }
    // Clicked before the answer came: a code still has to become a session id.
    void readThreadLink(threadRef).then((next) => { if (next.session_id) openCodingThread(next.session_id); }).catch(() => undefined);
  };
  const hint = fill(t("ide_threads.agent_link.open"), { thread: title, agent: info?.agent_label || t("ide_threads.agent_link.agent") });
  return <button type="button" onClick={open} title={hint} aria-label={hint} data-testid="coding-agent-link"
    className={cn(
      // A tint of the text colour, not a surface token: the link sits on a
      // message bubble in one place and on the page in another.
      "mx-0.5 inline-flex max-w-[min(100%,24rem)] items-center gap-1.5 rounded-md border border-foreground/15 bg-foreground/[0.06] px-1.5 py-px align-baseline text-[0.94em] font-medium leading-snug text-foreground transition-colors",
      "hover:border-foreground/30 hover:bg-foreground/[0.12] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
    )}>
    <span className="min-w-0 truncate">{shown}</span>
    {info?.agent
      ? <AgentMark agent={info.agent} label={info.agent_label || info.agent} variant="plain" size="sm" className="shrink-0" />
      : info?.provider
        ? <ProviderLogo providerId={info.provider} label={info.agent_label || info.provider} size="sm" className="shrink-0" />
        : <Code2 aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
  </button>;
}
