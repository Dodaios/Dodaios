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

/**
 * A coding agent named in a chat answer: the thread's title with the coding
 * agent's logo behind it. A click opens the thread in the Agentic IDE.
 *
 * `threadRef` is the thread's session id or its code. The words the answer
 * wrote are shown until the thread's own title is known, and stay as plain
 * text when the thread no longer exists. A link whose words are only the code
 * ("#bddece", see `linkBareThreadCodes`) stays plain text until the thread is
 * found: such a code may name no thread at all.
 */
export function CodingAgentLink({ threadRef, label }: { threadRef: string; label: string }) {
  const t = useT();
  const [info, setInfo] = useState<ThreadLinkInfo | undefined>(() => entries.get(threadRef)?.info);
  useEffect(() => {
    let live = true;
    setInfo(entries.get(threadRef)?.info);
    readThreadLink(threadRef).then((next) => { if (live) setInfo(next); }).catch(() => undefined);
    return () => { live = false; };
  }, [threadRef]);

  if (info && !info.found) return <span data-testid="coding-agent-link-gone">{label}</span>;
  if (!info && label.trim().toLowerCase() === `#${threadRef}`) return <span data-testid="coding-agent-link-pending">{label}</span>;
  const title = info?.title || label || t("ide_threads.new_thread");
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
    <span className="min-w-0 truncate">{title}</span>
    {info?.agent
      ? <AgentMark agent={info.agent} label={info.agent_label || info.agent} variant="plain" size="sm" className="shrink-0" />
      : info?.provider
        ? <ProviderLogo providerId={info.provider} label={info.agent_label || info.provider} size="sm" className="shrink-0" />
        : <Code2 aria-hidden className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
  </button>;
}
