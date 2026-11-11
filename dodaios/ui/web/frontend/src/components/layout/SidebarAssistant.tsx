import { lazy, Suspense, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, MessageCircle } from "lucide-react";
import { EarlierChatsLink } from "@/components/home/EarlierChatsLink";
import { chatRowLabel, useChatRows } from "@/components/home/chatRows";
import { useRunLocale } from "@/components/runs/format";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";

// The routine's own page (schedule, runs, pause) is only fetched when one is opened.
const SidebarRoutineDialog = lazy(() => import("@/components/layout/SidebarRoutineDialog"));

/** The assistant's own id in the roster; its routines are the automations listed here. */
const ASSISTANT_ID = "jarvis";
const RECENTS_SHOWN = 6;
const SECTIONS_KEY = "jarvis.sidebar.assistantSections.v1";
const AGENT_TITLE_PREFIX = /^\[agent:[^\]]+\]\s*/i;
const ROW =
  "flex min-h-8 w-full min-w-0 items-center gap-2.5 rounded-lg px-3 text-left text-base transition-colors " +
  "hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

interface Automation {
  id: string;
  title: string;
  state: string;
  dueMs: number | null;
}

function readSections(): Record<string, boolean> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(SECTIONS_KEY) ?? "{}");
    return parsed && typeof parsed === "object" ? (parsed as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

/** When a routine runs next: the time today, else the weekday and the time. */
export function nextRunLabel(dueMs: number, now: Date, locale: string): string {
  const due = new Date(dueMs);
  const time = due.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const sameDay = due.getFullYear() === now.getFullYear() && due.getMonth() === now.getMonth() && due.getDate() === now.getDate();
  return sameDay ? time : `${due.toLocaleDateString(locale, { weekday: "short" })} ${time}`;
}

function useAutomations() {
  return useQuery({
    queryKey: ["sidebar", "automations"],
    staleTime: 30_000,
    refetchInterval: import.meta.env.MODE === "test" ? false : 60_000,
    retry: false,
    queryFn: async (): Promise<Automation[]> => {
      const response = await fetch(`/api/society/agents/${ASSISTANT_ID}/routines`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = (await response.json()) as { routines?: { id?: string; title?: string; state?: string; due_at_ns?: number }[] };
      return (body.routines ?? []).flatMap((row) =>
        row.id
          ? [{
            id: row.id,
            title: (row.title ?? "").replace(AGENT_TITLE_PREFIX, "").trim(),
            state: row.state ?? "",
            dueMs: row.due_at_ns ? Math.round(row.due_at_ns / 1e6) : null,
          }]
          : [],
      );
    },
  });
}

function Section({ id, title, open, onToggle, children }: {
  id: string; title: string; open: boolean; onToggle: () => void; children: ReactNode;
}) {
  return (
    <section className="mt-3" aria-label={title} data-testid={`sidebar-assistant-${id}`}>
      <button type="button" aria-expanded={open} onClick={onToggle} data-testid={`sidebar-assistant-${id}-toggle`}
        className="flex h-7 w-full items-center gap-1 rounded-md px-3 text-left text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <span className="truncate">{title}</span>
        {open ? <ChevronDown aria-hidden className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0" />}
      </button>
      {open && <div className="mt-px flex flex-col gap-px">{children}</div>}
    </section>
  );
}

/**
 * The sidebar beside the assistant's conversation.
 *
 * The conversation is the page, so this column stays short: the way back to
 * the conversation, what the assistant runs on its own (its routines), and
 * the chats from before. Nothing of the Agentic IDE is listed here; that has
 * its own side of the switch.
 */
export default function SidebarAssistant({ onConversation }: { onConversation: () => void }) {
  const t = useT();
  const locale = useRunLocale();
  const automations = useAutomations();
  const { rows, isActive, open: openRow } = useChatRows();
  const [sections, setSections] = useState(readSections);
  const [routineId, setRoutineId] = useState<string | null>(null);

  const toggle = (id: string) => setSections((previous) => {
    const next = { ...previous, [id]: !(previous[id] ?? true) };
    try { localStorage.setItem(SECTIONS_KEY, JSON.stringify(next)); } catch { /* a convenience only */ }
    return next;
  });

  const recents = rows.slice(0, RECENTS_SHOWN);
  const earlierOnStage = recents.some((row) => isActive(row));
  const list = automations.data ?? [];
  const now = new Date();

  return (
    <nav aria-label={t("sidebar.conversation")} data-testid="sidebar-assistant" className="flex min-h-0 flex-1 flex-col px-2 pb-3 pt-1">
      <button type="button" data-testid="sidebar-assistant-conversation" onClick={onConversation}
        aria-current={earlierOnStage ? undefined : "page"}
        className={cn(ROW, earlierOnStage ? "text-foreground" : "bg-secondary text-foreground-strong")}>
        <MessageCircle aria-hidden strokeWidth={1.75} className="h-[18px] w-[18px] shrink-0" />
        <span className="truncate">{t("sidebar.conversation")}</span>
      </button>

      <Section id="automations" title={t("sidebar.automations")} open={sections.automations ?? true} onToggle={() => toggle("automations")}>
        {list.map((routine) => {
          const paused = routine.state === "paused";
          return (
            <button key={routine.id} type="button" data-testid={`sidebar-automation-${routine.id}`}
              onClick={() => setRoutineId(routine.id)} title={routine.title}
              className={cn(ROW, "text-sm", paused ? "text-muted-foreground" : "text-foreground")}>
              <span className="min-w-0 flex-1 truncate">{routine.title}</span>
              <span className="shrink-0 text-xs tabular-nums text-foreground-faint">
                {paused ? t("sidebar.agent_state.paused") : routine.dueMs ? nextRunLabel(routine.dueMs, now, locale) : ""}
              </span>
            </button>
          );
        })}
        {list.length === 0 && (
          <p data-testid="sidebar-automations-empty" className="px-3 py-1 text-sm text-foreground-faint">
            {automations.isLoading ? t("common.loading") : t("sidebar.automations_empty")}
          </p>
        )}
      </Section>

      <Section id="recents" title={t("sidebar.recent_chats")} open={sections.recents ?? true} onToggle={() => toggle("recents")}>
        {recents.map((row) => {
          const label = chatRowLabel(row, t);
          const active = isActive(row);
          return (
            <button key={`${row.kind}:${row.id}`} type="button" data-testid={`sidebar-recent-${row.id}`}
              onClick={() => openRow(row)} title={label.text} aria-current={active ? "page" : undefined}
              className={cn(ROW, "text-sm", active ? "bg-secondary text-foreground-strong" : label.untitled ? "text-muted-foreground" : "text-foreground")}>
              <span className="min-w-0 flex-1 truncate">{label.text}</span>
            </button>
          );
        })}
        <EarlierChatsLink />
      </Section>

      {routineId && (
        <Suspense fallback={null}>
          <SidebarRoutineDialog agentId={ASSISTANT_ID} routineId={routineId} onClose={() => setRoutineId(null)} />
        </Suspense>
      )}
    </nav>
  );
}
