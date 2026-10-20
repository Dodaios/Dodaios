import { CheckCircle2, Flag, MessageCircleQuestion, XCircle } from "lucide-react";
import { ChatMarkdown } from "@/components/agentchat/ChatMarkdown";
import type { NoticeItem } from "@/components/agentchat/reduce";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

/** How each report status reads in the chat: its line, its mark, its edge. */
const LOOK = {
  done: { key: "society.lead.card_done", Icon: CheckCircle2, edge: "border-l-success", tone: "text-success" },
  needs_input: { key: "society.lead.card_needs_input", Icon: MessageCircleQuestion, edge: "border-l-warning", tone: "text-warning" },
  failed: { key: "society.lead.card_failed", Icon: XCircle, edge: "border-l-destructive", tone: "text-destructive" },
  progress: { key: "society.lead.card_progress", Icon: Flag, edge: "border-l-border-strong", tone: "text-muted-foreground" },
} as const;

/**
 * A team lead's report in its own chat: the result of a goal, an interim
 * update, a failure, or the one question the lead needs answered. The lead
 * reports with a tool, so without this card the words would sit on the team
 * panel only and the conversation would skip its most important lines.
 */
export function TeamReportNotice({ item }: { item: NoticeItem }) {
  const t = useT();
  const look = LOOK[item.status as keyof typeof LOOK] ?? LOOK.progress;
  const title = typeof item.data.title === "string" ? item.data.title : "";
  return (
    <section data-testid="team-report-notice" data-status={item.status}
      className={cn("my-2 w-full min-w-0 rounded-xl border border-border border-l-2 bg-card px-4 py-3", look.edge)}>
      <p className="flex min-w-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <look.Icon className={cn("h-3.5 w-3.5 shrink-0", look.tone)} aria-hidden />
        <span className="shrink-0">{t(look.key).replace("{0}", item.agentName)}</span>
        {title ? <span className="min-w-0 truncate font-normal">· {title}</span> : null}
      </p>
      <div className="mt-1.5 text-sm text-foreground [overflow-wrap:anywhere]">
        <ChatMarkdown text={item.text} className="leading-relaxed" />
      </div>
    </section>
  );
}
