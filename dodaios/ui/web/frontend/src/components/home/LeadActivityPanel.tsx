import { useEffect, useMemo, useState } from "react";
import { BellRing, CircleCheck, CircleDot, Clock, Hand, Sun, X } from "lucide-react";

import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { useAgentChatStore } from "@/store/agentChat";
import { BrandedSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { LeadTriggersSetting } from "./LeadTriggersSetting";
import type { NoticeItem, TimelineItem, TurnItem } from "@/components/agentchat/reduce";

type Brief = { available: boolean; enabled: boolean; time: string; timezone: string };

/** `GET /api/agent-chat/lead/proactive`: the settings and the check routine's state. */
export type Proactive = {
  available: boolean;
  settings: { level: string; topics: string[]; interval_hours: number; from_hour: number; to_hour: number; timezone: string };
  checks: { enabled: boolean; runs_per_day: number; provider: string; model: string; billed_via_key: boolean };
};

const LEVELS = ["off", "important", "everything"] as const;
const INTERVALS = [1, 3, 6] as const;
const TOPICS = ["mail", "calendar", "agents", "deadlines"] as const;

function fill(text: string, values: Record<string, string | number>): string {
  return Object.entries(values).reduce((out, [key, value]) => out.split(`{${key}}`).join(String(value)), text);
}

/** The honest cost line under the proactivity setting: how often, on what, never on a key. */
export function costLine(p: Proactive, t: (key: string) => string): string {
  if (p.settings.level === "off") return t("home.proactive.hint_off");
  if (p.checks.billed_via_key) return t("home.proactive.cost_billed");
  const values = { n: p.checks.runs_per_day, from: p.settings.from_hour, to: p.settings.to_hour, model: p.checks.model || p.checks.provider };
  return fill(t(values.model ? "home.proactive.cost" : "home.proactive.cost_subscription"), values);
}

/** One row of the panel: what it is, and the conversation message it opens. */
type Row = { id: string; text: string; messageId: string };

const MAX_DONE = 6;

function turnLabel(turn: TurnItem, fallback: string): string {
  for (const block of turn.blocks) {
    if (block.kind === "tool" && block.approval && !block.approval.decision) return block.approval.summary || block.name;
    if (block.kind === "tool" && block.question && !block.question.closed) return block.question.questions[0]?.question || block.name;
  }
  return fallback;
}

/** What waits on the person, what runs, what finished — read off the conversation. */
export function activityOf(items: TimelineItem[], t: (key: string) => string) {
  const waiting: Row[] = [];
  const running: Row[] = [];
  const done: Row[] = [];
  for (const item of items) {
    if (item.type === "turn") {
      const open = item.blocks.some((b) => b.kind === "tool" && ((b.approval && !b.approval.decision) || (b.question && !b.question.closed)));
      if (open) waiting.push({ id: `w-${item.id}`, text: turnLabel(item, t("home.activity.needs_answer")), messageId: item.id });
      else if (item.status === "running") running.push({ id: `r-${item.id}`, text: t("home.activity.answering"), messageId: item.id });
      for (const who of item.background ?? []) running.push({ id: `b-${item.id}-${who}`, text: who, messageId: item.id });
    } else if (item.type === "notice" && item.kind === "society_result") {
      const notice = item as NoticeItem;
      const text = (notice.agentName ? `${notice.agentName}: ` : "") + notice.text.split("\n")[0];
      done.push({ id: `d-${item.id}`, text, messageId: item.id });
    }
  }
  return { waiting, running, done: done.slice(-MAX_DONE).reverse() };
}

function scrollTo(messageId: string) {
  const el = document.querySelector<HTMLElement>(`[data-message-id="${CSS.escape(messageId)}"]`);
  el?.scrollIntoView({ behavior: "smooth", block: "center" });
}

function Section({ icon, title, rows, empty }: { icon: React.ReactNode; title: string; rows: Row[]; empty: string }) {
  return (
    <section className="space-y-1">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">{icon}{title}</h3>
      {rows.length === 0 ? (
        <p className="pl-5 text-xs text-foreground-faint">{empty}</p>
      ) : (
        <ul className="space-y-0.5">
          {rows.map((row) => (
            <li key={row.id}>
              <button type="button" onClick={() => scrollTo(row.messageId)}
                className="w-full truncate rounded-md px-2 py-1 pl-5 text-left text-sm text-foreground hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                {row.text}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function BriefSetting() {
  const t = useT();
  const [brief, setBrief] = useState<Brief | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void fetch("/api/agent-chat/lead/brief").then((r) => (r.ok ? r.json() : null)).then((b: Brief | null) => { if (live) setBrief(b); }, () => undefined);
    return () => { live = false; };
  }, []);
  if (!brief || !brief.available) return null;
  const save = (enabled: boolean, time: string) => {
    setError("");
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    void fetch("/api/agent-chat/lead/brief", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, time, timezone }),
    }).then(async (r) => {
      if (!r.ok) { setError(t("home.activity.brief_failed")); return; }
      setBrief((await r.json()) as Brief);
    }, () => setError(t("home.activity.brief_failed")));
  };
  return (
    <section className="space-y-1.5" data-testid="lead-brief">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Sun aria-hidden className="h-3.5 w-3.5" />{t("home.activity.brief")}</h3>
      <div className="flex items-center gap-2 pl-5">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={brief.enabled} onChange={(e) => save(e.target.checked, brief.time)} data-testid="lead-brief-toggle" />
          {t("home.activity.brief_daily")}
        </label>
        <input type="time" value={brief.time} disabled={!brief.enabled} aria-label={t("home.activity.brief_time")}
          onChange={(e) => e.target.value && save(true, e.target.value)}
          className="rounded-md border border-border bg-transparent px-1.5 py-0.5 text-sm disabled:opacity-50" />
      </div>
      <p className="pl-5 text-xs text-foreground-faint">{error || t("home.activity.brief_hint")}</p>
    </section>
  );
}

/**
 * How much the assistant comes to the person on its own: one level, the
 * topics it looks at, how often. Saved as a whole on every change; the
 * server rebuilds the check routine and shows what it costs.
 */
function ProactiveSetting() {
  const t = useT();
  const [state, setState] = useState<Proactive | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void fetch("/api/agent-chat/lead/proactive").then((r) => (r.ok ? r.json() : null)).then((p: Proactive | null) => { if (live) setState(p); }, () => undefined);
    return () => { live = false; };
  }, []);
  if (!state || !state.available) return null;
  const { settings } = state;
  const save = (patch: Partial<Proactive["settings"]>) => {
    setError("");
    const next = { ...settings, ...patch, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone };
    setState({ ...state, settings: next });
    void fetch("/api/agent-chat/lead/proactive", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(next),
    }).then(async (r) => {
      if (!r.ok) { setError(t("home.proactive.failed")); return; }
      setState((await r.json()) as Proactive);
    }, () => setError(t("home.proactive.failed")));
  };
  const on = settings.level !== "off";
  return (
    <section className="space-y-1.5" data-testid="lead-proactive">
      <h3 className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
        <BellRing aria-hidden className={cn("h-3.5 w-3.5", on && "text-primary")} />{t("home.proactive.title")}
      </h3>
      <div className="space-y-2 pl-5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm text-foreground">{t("home.proactive.level")}</span>
          <BrandedSelect value={settings.level} ariaLabel={t("home.proactive.level")} testId="lead-proactive-level"
            className="h-7 w-36 text-xs" onValueChange={(level) => save({ level })}
            options={LEVELS.map((level) => ({ value: level, label: t(`home.proactive.level_${level}`) }))} />
        </div>
        {on ? (
          <>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-foreground">{t("home.proactive.interval")}</span>
              <BrandedSelect value={String(settings.interval_hours)} ariaLabel={t("home.proactive.interval")} testId="lead-proactive-interval"
                className="h-7 w-36 text-xs" onValueChange={(hours) => save({ interval_hours: Number(hours) })}
                options={INTERVALS.map((hours) => ({ value: String(hours), label: t(`home.proactive.interval_${hours}`) }))} />
            </div>
            <ul className="space-y-1" aria-label={t("home.proactive.topics")}>
              {TOPICS.map((topic) => {
                const checked = settings.topics.includes(topic);
                return (
                  <li key={topic} className="flex items-center justify-between gap-2">
                    <label htmlFor={`lead-proactive-${topic}`} className="text-sm text-foreground">{t(`home.proactive.topic_${topic}`)}</label>
                    <Switch id={`lead-proactive-${topic}`} checked={checked} data-testid={`lead-proactive-${topic}`}
                      onCheckedChange={(next) => save({ topics: next ? [...settings.topics, topic] : settings.topics.filter((x) => x !== topic) })} />
                  </li>
                );
              })}
            </ul>
          </>
        ) : null}
        <p className="text-xs text-foreground-faint" data-testid="lead-proactive-cost">{error || costLine(state, t)}</p>
        {on ? <p className="text-xs text-foreground-faint">{t("home.proactive.checkin_hint")}</p> : null}
      </div>
    </section>
  );
}

/**
 * The right side of the front page: what the assistant is doing for the
 * person. Waiting on you, running, finished — each opens its place in the
 * conversation — and the morning brief. Read from the one conversation,
 * so it costs no extra request beyond the brief's setting.
 */
export function LeadActivityPanel({ onClose }: { onClose: () => void }) {
  const t = useT();
  const items = useAgentChatStore((s) => s.timeline.items);
  const { waiting, running, done } = useMemo(() => activityOf(items, t), [items, t]);
  return (
    <aside data-testid="lead-activity" aria-label={t("home.activity.title")}
      className="flex h-full w-72 shrink-0 flex-col gap-5 overflow-y-auto border-l border-border px-3 py-4">
      <header className="flex items-center justify-between">
        <h2 className="text-sm font-medium text-foreground-strong">{t("home.activity.title")}</h2>
        <button type="button" onClick={onClose} aria-label={t("home.activity.close")}
          className="rounded-md p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          <X aria-hidden className="h-4 w-4" />
        </button>
      </header>
      <Section icon={<Hand aria-hidden className={cn("h-3.5 w-3.5", waiting.length > 0 && "text-primary")} />}
        title={t("home.activity.waiting")} rows={waiting} empty={t("home.activity.nothing")} />
      <Section icon={<CircleDot aria-hidden className="h-3.5 w-3.5" />} title={t("home.activity.running")} rows={running} empty={t("home.activity.nothing")} />
      <Section icon={<CircleCheck aria-hidden className="h-3.5 w-3.5" />} title={t("home.activity.done")} rows={done} empty={t("home.activity.nothing")} />
      <BriefSetting />
      <ProactiveSetting />
      <LeadTriggersSetting />
      <p className="mt-auto flex items-center gap-2 text-xs text-foreground-faint"><Clock aria-hidden className="h-3.5 w-3.5" />{t("home.activity.scheduled_hint")}</p>
    </aside>
  );
}
