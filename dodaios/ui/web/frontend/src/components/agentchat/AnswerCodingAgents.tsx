import { useMemo } from "react";

import { CodingAgentLink } from "@/components/agentic/threads/CodingAgentLink";
import { linkedThreadRefs, linksThread } from "./chatLinks";
import type { CodingThreadRef } from "./reduce";

/**
 * The coding agents an answer started, each as a link that opens its thread
 * (the thread's title with the agent's logo). The answer shows them whether
 * or not its words link to them; one the words already link to is not shown
 * twice.
 */
export function AnswerCodingAgents({ threads, texts }: { threads: readonly CodingThreadRef[] | undefined; texts: readonly string[] }) {
  const shown = useMemo(() => {
    if (!threads?.length) return [];
    const linked = texts.flatMap(linkedThreadRefs);
    return threads.filter((thread) => !linksThread(linked, thread.threadId));
  }, [threads, texts]);
  if (!shown.length) return null;
  return (
    <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5 text-[15px] leading-[23px]" data-testid="answer-coding-agents">
      {shown.map((thread) => (
        <CodingAgentLink key={thread.threadId} threadRef={thread.threadId} label={thread.title || thread.agent} />
      ))}
    </div>
  );
}
