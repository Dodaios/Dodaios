import { CodingThreadActivity } from "@/components/agentic/threads/CodingThreadLink";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { agentResultLabel } from "./agentResults";
import type { NoticeItem } from "./reduce";

/**
 * A delegated agent's result that the assistant did not take up
 * (`withoutAnsweredResults` drops the ones it did): one line saying who is
 * done and how, which opens the agent's thread when the notice names it. The
 * report itself stays in the thread.
 */
export function AgentResultLine({ item }: { item: NoticeItem }) {
  const t = useT();
  const label = agentResultLabel(t, item);
  const failed = item.status === "failed";
  const threadId = String(item.data.thread_id ?? "");
  if (threadId) return <CodingThreadActivity label={label} threadId={threadId} failed={failed} />;
  return (
    <p data-message-id={item.id} data-testid="agent-result-line"
      className={cn("mx-auto my-3 max-w-[85%] px-2 py-1.5 text-center text-xs text-muted-foreground", failed && "text-destructive")}>
      {label}
    </p>
  );
}
