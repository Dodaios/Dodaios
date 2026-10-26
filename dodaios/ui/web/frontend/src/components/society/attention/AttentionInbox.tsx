import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowUpRight,
  Bell,
  BellOff,
  Check,
  Inbox,
  KeyRound,
  MessageCircleQuestion,
  ShieldAlert,
  SlidersHorizontal,
  Sparkles,
  X,
} from "lucide-react";

import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { AgentSwatch } from "@/components/society/AgentSwatch";
import { useSocietyRoster, type SocietyAgent } from "@/components/society/data";
import { openAgent } from "@/views/society/agentNavigation";

import { quickActionsFor, runQuickAction, type AttentionItem, type AttentionKind, type QuickAction } from "./attentionApi";
import {
  desktopNotificationsSupported,
  desktopPermission,
  setDesktopNotices,
  setFinishedNotices,
  toggleAgentMuted,
  useNotificationPrefs,
} from "./notificationPrefs";
import { forgetAttentionItem } from "./attentionStore";
import { useAgentAttention, type AttentionGroup } from "./useAgentAttention";

/**
 * Everything the agents are waiting on the person for, in one calm list.
 *
 * Grouped by agent, the agent who has waited longest first. Each row says
 * what is asked and since when; the simple ones can be settled right here (a
 * one-pick question, an approval, a proposed change) and every row opens its
 * card in the agent's chat. Nothing in this list ever widens a permission:
 * "allow" here always means this once.
 */

const LETTERS = "ABCD";

const KIND_ICON: Record<AttentionKind, typeof ShieldAlert> = {
  question: MessageCircleQuestion,
  approval: ShieldAlert,
  credential: KeyRound,
  proposal: Sparkles,
};

/** A clock that ticks every `ms` while something on screen depends on it. */
function useNow(ms: number): number {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(timer);
  }, [ms]);
  return now;
}

/** "now", "4 min", "2 h", "3 d". */
export function ageLabel(t: (key: string) => string, sinceMs: number, now: number): string {
  const minutes = Math.floor(Math.max(0, now - sinceMs) / 60_000);
  if (minutes < 1) return t("agent_attention.age_now");
  if (minutes < 60) return fill(t("agent_attention.age_minutes"), { n: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return fill(t("agent_attention.age_hours"), { n: hours });
  return fill(t("agent_attention.age_days"), { n: Math.floor(hours / 24) });
}

function clock(ms: number): string {
  const seconds = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function open(item: AttentionItem, onDone?: () => void) {
  openAgent(item.agentId, { sessionId: item.sessionId, cardRef: item.refId, kind: item.kind });
  onDone?.();
}

export function AttentionInbox({ onClose, className }: { onClose?: () => void; className?: string }) {
  const t = useT();
  const { groups, count, isLoading, isError } = useAgentAttention();
  const roster = useSocietyRoster();
  const agents = useMemo(() => {
    const map = new Map<string, SocietyAgent>();
    for (const agent of roster.data?.agents ?? []) map.set(agent.agentId, agent);
    return map;
  }, [roster.data]);
  const [settings, setSettings] = useState(false);
  const timed = groups.some((group) => group.items.some((item) => item.expiresMs !== null));
  const now = useNow(timed ? 1000 : 30_000);

  return (
    <div className={cn("flex max-h-[min(70vh,560px)] min-h-0 flex-col", className)} data-testid="attention-inbox">
      <header className="flex items-center gap-2 border-b border-border px-4 pb-2.5 pt-3">
        <h2 className="m-0 text-sm font-semibold text-foreground-strong">{t("agent_attention.title")}</h2>
        {count > 0 && (
          <span className="rounded-full bg-secondary px-1.5 text-xs font-medium tabular-nums text-muted-foreground" data-testid="attention-inbox-count">
            {count}
          </span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => setSettings((on) => !on)}
          aria-expanded={settings}
          aria-label={t("agent_attention.settings")}
          title={t("agent_attention.settings")}
          className={cn(
            "inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150",
            "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            settings && "bg-secondary text-foreground",
          )}
        >
          <SlidersHorizontal className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
        </button>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            aria-label={t("agent_attention.close")}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
          </button>
        )}
      </header>
      {settings && <NotificationSettings />}
      <div className="chat-scroller min-h-0 flex-1 overflow-y-auto px-2 py-2">
        {isLoading && groups.length === 0 ? (
          <p role="status" className="px-3 py-6 text-center text-xs text-muted-foreground">{t("agent_attention.loading")}</p>
        ) : isError && groups.length === 0 ? (
          <p role="alert" className="px-3 py-6 text-center text-xs text-muted-foreground">{t("agent_attention.unavailable")}</p>
        ) : groups.length === 0 ? (
          <EmptyInbox />
        ) : (
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {groups.map((group) => (
              <AgentGroupRow key={group.agentId} group={group} agent={agents.get(group.agentId)} now={now} onOpened={onClose} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function EmptyInbox() {
  const t = useT();
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-8 text-center" data-testid="attention-inbox-empty">
      <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-secondary text-muted-foreground">
        <Inbox className="h-4 w-4" strokeWidth={1.8} aria-hidden />
      </span>
      <p className="m-0 text-sm font-medium text-foreground">{t("agent_attention.empty_title")}</p>
      <p className="m-0 max-w-[260px] text-xs leading-relaxed text-muted-foreground">{t("agent_attention.empty_body")}</p>
    </div>
  );
}

function AgentGroupRow({ group, agent, now, onOpened }: {
  group: AttentionGroup; agent: SocietyAgent | undefined; now: number; onOpened?: () => void;
}) {
  const t = useT();
  const muted = useNotificationPrefs((s) => s.muted.includes(group.agentId));
  const name = agent?.name || group.agentId;
  const muteLabel = fill(t(muted ? "agent_attention.unmute" : "agent_attention.mute"), { agent: name });
  return (
    <li className="group/agent rounded-lg" data-testid="attention-group" data-agent-id={group.agentId}>
      <div className="flex items-center gap-2 px-2 pb-1 pt-1.5">
        {agent ? <AgentSwatch agent={agent} size={20} /> : <span aria-hidden className="h-5 w-5 rounded-full bg-secondary" />}
        <span className="min-w-0 truncate text-xs font-semibold text-foreground">{name}</span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {fill(t("agent_attention.waiting_count"), { count: group.items.length })}
        </span>
        <span className="flex-1" />
        {muted && <span className="text-[11px] text-muted-foreground">{t("agent_attention.muted")}</span>}
        <button
          type="button"
          onClick={() => toggleAgentMuted(group.agentId)}
          aria-pressed={muted}
          aria-label={muteLabel}
          title={muteLabel}
          className={cn(
            "inline-flex h-6 w-6 items-center justify-center rounded-md text-muted-foreground transition-[opacity,color,background-color] duration-150",
            "hover:bg-secondary hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            muted ? "opacity-100" : "opacity-0 group-hover/agent:opacity-100",
          )}
        >
          {muted ? <BellOff className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden /> : <Bell className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />}
        </button>
      </div>
      <ul className="m-0 flex list-none flex-col p-0">
        {group.items.map((item) => (
          <AttentionRow key={`${item.sessionId}:${item.refId}`} item={item} now={now} onOpened={onOpened} />
        ))}
      </ul>
    </li>
  );
}

function kindLabel(t: (key: string) => string, item: AttentionItem): string {
  if (item.kind === "approval" && item.source === "queue") return t("agent_attention.kind_parked");
  return t(`agent_attention.kind_${item.kind}`);
}

function AttentionRow({ item, now, onOpened }: { item: AttentionItem; now: number; onOpened?: () => void }) {
  const t = useT();
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState(false);
  const [done, setDone] = useState(false);
  const actions = quickActionsFor(item);
  const Icon = KIND_ICON[item.kind] ?? MessageCircleQuestion;
  const live = item.source === "chat";

  const run = async (action: QuickAction, index: number) => {
    if (busy !== null) return;
    setBusy(index);
    setError(false);
    try {
      await runQuickAction(item, action);
      setDone(true);
      // Leave the check on screen for a beat, then let the row go.
      window.setTimeout(() => forgetAttentionItem(item), 450);
    } catch {
      setError(true);
    } finally {
      setBusy(null);
    }
  };

  const meta: ReactNode[] = [kindLabel(t, item)];
  if (item.kind === "question" && (item.detail.count ?? 1) > 1) {
    meta.push(fill(t("agent_attention.step"), { step: (item.detail.step ?? 0) + 1, count: item.detail.count ?? 1 }));
  }
  meta.push(ageLabel(t, item.sinceMs, now));
  if (item.expiresMs !== null && item.kind === "question" && !item.deferred) {
    meta.push(fill(t("agent_attention.closes_in"), { time: clock(item.expiresMs - now) }));
  }

  return (
    <li
      className={cn(
        "group/item relative flex gap-2.5 rounded-lg px-2 py-2 transition-[background-color,opacity] duration-200",
        "hover:bg-secondary focus-within:bg-secondary",
        done && "opacity-60",
      )}
      data-testid="attention-item"
      data-kind={item.kind}
      data-ref={item.refId}
    >
      <span
        aria-hidden
        className={cn(
          "mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-secondary group-hover/item:bg-background",
          live ? "text-warning" : "text-muted-foreground",
        )}
      >
        {done ? <Check className="h-3.5 w-3.5 text-foreground" strokeWidth={2.2} /> : <Icon className="h-3.5 w-3.5" strokeWidth={1.9} />}
      </span>
      <div className="min-w-0 flex-1">
        <button
          type="button"
          onClick={() => open(item, onOpened)}
          className="block w-full rounded-sm text-left text-sm leading-snug text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="line-clamp-2 [overflow-wrap:anywhere]">{item.summary || kindLabel(t, item)}</span>
        </button>
        <p className="m-0 mt-0.5 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
          {meta.map((part, index) => (
            <span key={index} className="inline-flex items-center gap-1.5">
              {index > 0 && <span aria-hidden className="text-border-strong">·</span>}
              {part}
            </span>
          ))}
        </p>
        {actions.length > 0 && !done && (
          <div className="mt-2 flex flex-wrap gap-1.5" role="group" aria-label={t("agent_attention.quick_answer")}>
            {actions.map((action, index) => (
              <QuickButton key={index} item={item} action={action} index={index} busy={busy} onRun={run} />
            ))}
          </div>
        )}
        {error && (
          <p role="alert" className="m-0 mt-1.5 text-xs text-destructive">{t("agent_attention.failed")}</p>
        )}
      </div>
      <button
        type="button"
        onClick={() => open(item, onOpened)}
        aria-label={t("agent_attention.open_card")}
        title={t("agent_attention.open_card")}
        className={cn(
          "mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-[opacity,color] duration-150",
          "opacity-0 hover:text-foreground group-hover/item:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        )}
      >
        <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={1.9} aria-hidden />
      </button>
    </li>
  );
}

const QUIET_BUTTON =
  "inline-flex h-7 max-w-full items-center gap-1.5 rounded-md border border-border bg-background px-2 text-xs text-foreground " +
  "transition-colors duration-150 hover:border-border-strong hover:bg-surface-raised disabled:opacity-50 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

const INK_BUTTON =
  "inline-flex h-7 items-center gap-1.5 rounded-md bg-foreground px-2.5 text-xs font-medium text-background " +
  "transition-opacity duration-150 hover:opacity-90 disabled:opacity-50 " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background";

function QuickButton({ item, action, index, busy, onRun }: {
  item: AttentionItem;
  action: QuickAction;
  index: number;
  busy: number | null;
  onRun: (action: QuickAction, index: number) => void;
}) {
  const t = useT();
  const disabled = busy !== null;
  if (action.type === "option") {
    const label = item.detail.options?.[action.index] ?? "";
    return (
      <button type="button" disabled={disabled} onClick={() => onRun(action, index)} className={QUIET_BUTTON}
        aria-label={label} data-testid="attention-option">
        <span aria-hidden className="font-mono text-[10px] text-muted-foreground">{LETTERS[action.index]}</span>
        <span className="truncate">{label}</span>
      </button>
    );
  }
  const allow = action.type === "allow";
  const proposal = item.kind === "proposal";
  const key = allow
    ? proposal ? "agent_attention.approve" : item.source === "queue" ? "agent_attention.approve" : "agent_attention.allow_once"
    : proposal ? "agent_attention.decline" : "agent_attention.deny";
  return (
    <button type="button" disabled={disabled} onClick={() => onRun(action, index)}
      className={allow ? INK_BUTTON : QUIET_BUTTON} data-testid={allow ? "attention-allow" : "attention-deny"}>
      {t(key)}
    </button>
  );
}

function NotificationSettings() {
  const t = useT();
  const desktop = useNotificationPrefs((s) => s.desktop);
  const finished = useNotificationPrefs((s) => s.finished);
  const [permission, setPermission] = useState(desktopPermission);
  const supported = desktopNotificationsSupported();
  const hint = !supported
    ? t("agent_attention.desktop_unsupported")
    : permission === "denied"
      ? t("agent_attention.desktop_blocked")
      : t("agent_attention.desktop_hint");
  const switching = useRef(false);
  return (
    <section className="flex flex-col gap-3 border-b border-border bg-sidebar px-4 py-3" aria-label={t("agent_attention.settings")}
      data-testid="attention-settings">
      <SettingRow
        id="attention-desktop"
        label={t("agent_attention.desktop")}
        hint={hint}
        checked={desktop && permission === "granted"}
        disabled={!supported || permission === "denied"}
        onChange={(on) => {
          if (switching.current) return;
          switching.current = true;
          void setDesktopNotices(on).finally(() => {
            switching.current = false;
            setPermission(desktopPermission());
          });
        }}
      />
      <SettingRow
        id="attention-finished"
        label={t("agent_attention.finished")}
        hint={t("agent_attention.finished_hint")}
        checked={finished}
        onChange={setFinishedNotices}
      />
    </section>
  );
}

function SettingRow({ id, label, hint, checked, disabled = false, onChange }: {
  id: string; label: string; hint: string; checked: boolean; disabled?: boolean; onChange: (on: boolean) => void;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1">
        <label htmlFor={id} className="block text-xs font-medium text-foreground">{label}</label>
        <p id={`${id}-hint`} className="m-0 mt-0.5 text-[11px] leading-relaxed text-muted-foreground">{hint}</p>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} aria-describedby={`${id}-hint`} />
    </div>
  );
}
