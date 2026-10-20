/**
 * The team beside its lead's chat: what the team works on now, what waits,
 * who is on it, what is finished, and how the lead works (mission, initiative,
 * who leads).
 *
 * The chat is where the person talks to the lead. This panel is where they
 * look, and it holds the few controls that are not a sentence: stop a goal,
 * continue a paused one, set the team up.
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDown, Crown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandedSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useT } from "@/i18n";
import {
  TEAM_GOAL_OPEN,
  cancelSocietyTeamGoal,
  createSocietyTeamLead,
  resumeSocietyTeamGoal,
  setSocietyTeamCheckin,
  setSocietyTeamLead,
  setSocietyTeamMission,
  type SocietyChatGroup,
  type SocietyTeam,
  type SocietyTeamGoal,
  type SocietyTeamTask,
} from "@/lib/societyChatGroups";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";
import type { SocietyAgent } from "../data";
import { AgentSwatch } from "../AgentSwatch";
import { Prose } from "./AgentChatPanel";

/** How a lead works without being asked. */
export type InitiativeMode = "off" | "watch" | "drive";
/** The server's check-in intervals that are "on" (jarvis/society/team_lead.py CHECKIN_MINUTES). */
const RHYTHMS = [60, 240, 1440] as const;
const DEFAULT_RHYTHM = 240;
const MODES: readonly InitiativeMode[] = ["off", "watch", "drive"];
/** Reasons a goal waits that have their own sentence; anything else shows as written. */
const NOTE_KEYS = new Set([
  "society_paused", "interrupted", "turn_budget", "lead_busy", "lead_unavailable", "stalled",
]);
/** A report longer than this starts folded. */
const LONG_TEXT = 320;

export function initiativeMode(team: Pick<SocietyTeam, "checkin_minutes" | "initiative">): InitiativeMode {
  return team.checkin_minutes === 0 ? "off" : team.initiative ? "drive" : "watch";
}

const DOT: Record<string, string> = {
  running: "bg-success",
  assigned: "bg-success",
  working: "bg-success",
  needs_input: "bg-warning",
  waiting: "bg-warning",
  paused: "bg-warning",
  queued: "bg-muted-foreground",
  idle: "bg-muted-foreground/40",
  done: "bg-foreground",
  blocked: "bg-destructive",
  failed: "bg-destructive",
  cancelled: "bg-muted-foreground",
};

function StateChip({ state, label }: { state: string; label: string }) {
  return (
    <span data-state={state}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
      <i className={cn("h-1.5 w-1.5 rounded-full", DOT[state] ?? "bg-muted-foreground")} aria-hidden />
      {label}
    </span>
  );
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {title}{count ? <span className="rounded-full bg-secondary px-1.5 text-[11px] normal-case tracking-normal">{count}</span> : null}
      </h3>
      {children}
    </section>
  );
}

/** A section that folds; its heading is the switch. */
function Fold({ title, open, onToggle, testId, children }: {
  title: string; open: boolean; onToggle: () => void; testId?: string; children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2" data-testid={testId}>
      <button type="button" aria-expanded={open} onClick={onToggle}
        className="flex items-center gap-1 rounded-sm text-left text-xs font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", !open && "-rotate-90")} aria-hidden />{title}
      </button>
      {open ? children : null}
    </section>
  );
}

/** Long text folded to a few lines until the person asks for all of it. */
function Folded({ text }: { text: string }) {
  const t = useT();
  const [all, setAll] = useState(false);
  const long = text.length > LONG_TEXT;
  return (
    <div className="rounded-lg bg-secondary/50 px-3 py-2 text-sm">
      <div className={cn(long && !all && "max-h-24 overflow-hidden")}><Prose text={text} /></div>
      {long && <button type="button" aria-expanded={all} onClick={() => setAll((value) => !value)}
        className="mt-1 rounded-sm text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground">
        {t(all ? "society.lead.show_less" : "society.lead.show_more")}
      </button>}
    </div>
  );
}

function TaskRow({ task, agent, name }: { task: SocietyTeamTask; agent: SocietyAgent | undefined; name: string }) {
  const t = useT();
  const [shown, setShown] = useState(false);
  return (
    <li className="flex flex-col gap-1.5 py-2" data-testid={`team-task-${task.task_id}`}>
      <div className="flex items-center gap-2">
        {agent ? <AgentSwatch agent={agent} size={20} /> : null}
        <span className="min-w-0 flex-1 text-sm text-foreground">
          <span className="block truncate font-medium">{name}</span>
          <span className="block truncate text-xs text-muted-foreground" title={task.title}>{task.title}</span>
        </span>
        <StateChip state={task.state} label={t(`society.lead.task_state_${task.state}`)} />
      </div>
      {task.result && <button type="button" aria-expanded={shown} onClick={() => setShown((value) => !value)}
        className="self-start rounded-sm text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground">
        {t(shown ? "society.lead.hide_result" : "society.lead.show_result")}
      </button>}
      {shown && <Folded text={task.result} />}
    </li>
  );
}

interface GoalProps {
  goal: SocietyTeamGoal;
  leadName: string;
  assistantName: string;
  agentOf: (id: string) => SocietyAgent | undefined;
  nameOf: (id: string) => string;
  busy: string;
  onResume: () => void;
  onCancel: () => void;
}

function GoalCard({ goal, leadName, assistantName, agentOf, nameOf, busy, onResume, onCancel }: GoalProps) {
  const t = useT();
  const waiting = goal.state === "needs_input";
  const source = goal.source === "jarvis" ? t("society.lead.source_jarvis").replace("{0}", assistantName)
    : goal.source === "lead" ? t("society.lead.source_lead").replace("{0}", leadName)
    : goal.source === "assignment" ? t("society.lead.source_assignment") : "";
  // The title is the goal's first line, cut short when it is long. Show the
  // line in full as the heading and only what the text adds to it below.
  const text = goal.text.trim();
  const firstLine = text.split("\n", 1)[0].trim();
  const stem = goal.title.endsWith("…") ? goal.title.slice(0, -1).trimEnd() : goal.title;
  const ownsTitle = stem.length > 0 && firstLine.replace(/\s+/g, " ").startsWith(stem);
  const heading = ownsTitle ? firstLine : goal.title;
  const detailText = ownsTitle ? text.slice(text.indexOf(firstLine) + firstLine.length).trim() : text === goal.title ? "" : text;
  const detail = goal.note.startsWith("error:") ? goal.note.slice(6) : "";
  const note = goal.state !== "paused" && goal.state !== "failed" ? ""
    : detail ? t("society.lead.note_error").replace("{0}", detail)
    : NOTE_KEYS.has(goal.note) ? t(`society.lead.note_${goal.note}`) : "";
  const closed = goal.state === "done" || goal.state === "cancelled";

  return (
    <article className={cn("flex flex-col gap-2.5 rounded-xl border bg-card p-3", waiting ? "border-warning/50" : "border-border")}
      data-testid={`team-goal-${goal.goal_id}`} data-state={goal.state}>
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h4 className="line-clamp-3 text-sm font-semibold text-foreground [overflow-wrap:anywhere]" title={heading}>{heading}</h4>
          {detailText && <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-xs text-muted-foreground" title={detailText}>{detailText}</p>}
          {source && <p className="mt-1 text-xs text-muted-foreground">{source}</p>}
        </div>
        <StateChip state={goal.state} label={t(`society.lead.state_${goal.state}`)} />
      </header>

      {note && <p className="text-xs text-muted-foreground">{note}</p>}

      {goal.tasks.length > 0 && <ul className="divide-y divide-border border-y border-border">
        {goal.tasks.map((task) => <TaskRow key={task.task_id} task={task} agent={agentOf(task.agent_id)} name={nameOf(task.agent_id)} />)}
      </ul>}
      {goal.tasks.length === 0 && goal.state === "running" && <p className="text-xs text-muted-foreground">{t("society.lead.tasks_none").replace("{0}", leadName)}</p>}

      {goal.report && <div className="flex flex-col gap-1">
        <p className="text-xs font-medium text-muted-foreground">
          {t(waiting ? "society.lead.question" : "society.lead.report").replace("{0}", leadName)}
        </p>
        <Folded text={goal.report} />
      </div>}
      {waiting && <p className="text-xs font-medium text-warning">{t("society.lead.answer_in_chat").replace("{0}", leadName)}</p>}

      {!closed && <div className="flex flex-wrap justify-end gap-2">
        {goal.state === "paused" && <Button size="sm" disabled={Boolean(busy)} onClick={onResume}>{t("society.lead.resume")}</Button>}
        {goal.state === "failed" && <Button size="sm" variant="secondary" disabled={Boolean(busy)} onClick={onResume}>{t("society.lead.retry")}</Button>}
        {goal.state === "queued" && <Button size="sm" variant="secondary" disabled={Boolean(busy)} onClick={onResume}>{t("society.lead.start_now")}</Button>}
        {goal.state !== "failed" && <Button size="sm" variant="ghost" disabled={Boolean(busy)} onClick={onCancel}>
          {t(goal.state === "queued" ? "society.lead.remove_goal" : "society.lead.stop")}
        </Button>}
      </div>}
    </article>
  );
}

/** A finished goal: one line until opened. */
function FinishedRow(props: GoalProps) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const { goal } = props;
  if (open) {
    return <div className="flex flex-col gap-1">
      <GoalCard {...props} />
      <button type="button" onClick={() => setOpen(false)}
        className="self-end rounded-sm text-xs text-muted-foreground underline underline-offset-4 hover:text-foreground">{t("society.lead.show_less")}</button>
    </div>;
  }
  return (
    <button type="button" aria-expanded={false} onClick={() => setOpen(true)} data-testid={`team-goal-${goal.goal_id}`} data-state={goal.state}
      className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <i className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT[goal.state] ?? "bg-muted-foreground")} aria-hidden />
      <span className="min-w-0 flex-1 truncate text-sm text-foreground">{goal.title}</span>
      <span className="shrink-0 text-xs text-muted-foreground">{t(`society.lead.state_${goal.state}`)}</span>
    </button>
  );
}

interface PanelProps {
  team: SocietyTeam;
  group: SocietyChatGroup;
  roster: SocietyAgent[];
  busy: string;
  setupOpen: boolean;
  onSetupOpen: (open: boolean) => void;
  /** Run one team action; the answer replaces the team, a refusal shows as written. */
  run: (key: string, action: () => Promise<SocietyTeam>) => Promise<boolean>;
  /** As `run`, for an action that changes who leads (the roster and the group change too). */
  leadChanged: (key: string, action: () => Promise<SocietyTeam>) => Promise<boolean>;
  onOpenAgent: (id: string) => void;
}

export function TeamLeadPanel({ team, group, roster, busy, setupOpen, onSetupOpen, run, leadChanged, onOpenAgent }: PanelProps) {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName);
  const [finishedOpen, setFinishedOpen] = useState(false);
  const [picked, setPicked] = useState("");
  const [mission, setMission] = useState(team.mission);
  const savedMission = useRef(team.mission);

  // The saved mission fills the field until the person starts editing it.
  useEffect(() => {
    const previous = savedMission.current;
    savedMission.current = team.mission;
    setMission((current) => (current === previous ? team.mission : current));
  }, [team.mission]);

  const agentOf = (id: string | null | undefined) => roster.find((agent) => agent.agentId === id);
  const nameOf = (id: string | null | undefined) => {
    const agent = agentOf(id);
    return agent ? societyDisplayName(agent, assistantName) : (id ?? "");
  };
  const leadName = nameOf(team.lead_agent_id);
  const everyone = group.members.map(agentOf).filter((agent): agent is SocietyAgent => Boolean(agent));
  const members = everyone.filter((agent) => agent.tier !== "lead" && agent.agentId !== team.lead_agent_id && agent.lifecycle !== "archived");

  const open = team.goals.filter((goal) => TEAM_GOAL_OPEN.includes(goal.state));
  const now = open.filter((goal) => goal.state !== "queued").sort((a, b) => a.created_ms - b.created_ms);
  const next = open.filter((goal) => goal.state === "queued").sort((a, b) => a.created_ms - b.created_ms);
  const finished = team.goals.filter((goal) => !TEAM_GOAL_OPEN.includes(goal.state));
  /** What each member is on right now, from the goals in progress. */
  const taskOf = (agentId: string) => now.flatMap((goal) => goal.tasks)
    .find((task) => task.agent_id === agentId && ["waiting", "assigned", "running"].includes(task.state));

  const card = (goal: SocietyTeamGoal) => ({
    goal, leadName, assistantName, agentOf, nameOf, busy,
    onResume: () => void run(`resume:${goal.goal_id}`, () => resumeSocietyTeamGoal(group.group_id, goal.goal_id)),
    onCancel: () => void run(`cancel:${goal.goal_id}`, () => cancelSocietyTeamGoal(group.group_id, goal.goal_id)),
  });

  const mode = initiativeMode(team);
  const rhythm = team.checkin_minutes || DEFAULT_RHYTHM;
  const setMode = (nextMode: InitiativeMode, minutes = rhythm) => void run("initiative", () =>
    setSocietyTeamCheckin(group.group_id, nextMode === "off" ? 0 : minutes, nextMode === "drive"));

  return (
    <aside data-testid="team-lead-panel" aria-label={t("society.lead.panel_title")}
      className="flex min-h-0 w-[340px] shrink-0 flex-col gap-5 overflow-y-auto border-l border-border bg-background px-4 py-4 max-xl:absolute max-xl:inset-y-0 max-xl:right-0 max-xl:z-10 max-xl:w-[min(340px,100%)] max-xl:shadow-float">
      <Section title={t("society.lead.now")}>
        {now.length === 0 && <p className="rounded-xl border border-dashed border-border px-3 py-4 text-center text-sm text-muted-foreground">
          {t("society.lead.now_empty").replace("{0}", leadName)}
        </p>}
        {now.map((goal) => <GoalCard key={goal.goal_id} {...card(goal)} />)}
      </Section>

      {next.length > 0 && <Section title={t("society.lead.next")} count={next.length}>
        {next.map((goal) => <GoalCard key={goal.goal_id} {...card(goal)} />)}
      </Section>}

      <Section title={t("society.lead.members")}>
        {members.length === 0 && <p className="text-sm text-muted-foreground">{t("society.lead.members_empty")}</p>}
        <ul className="flex flex-col">
          {members.map((agent) => {
            const task = taskOf(agent.agentId);
            const state = task ? "working" : agent.state;
            return <li key={agent.agentId}>
              <button type="button" onClick={() => onOpenAgent(agent.agentId)} data-testid={`team-member-${agent.agentId}`}
                className="flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left hover:bg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <AgentSwatch agent={agent} size={26} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">{societyDisplayName(agent, assistantName)}</span>
                  <span className="block truncate text-xs text-muted-foreground">{task ? task.title : agent.title}</span>
                </span>
                <StateChip state={state} label={t(`society.lead.member_${state}`)} />
              </button>
            </li>;
          })}
        </ul>
      </Section>

      {finished.length > 0 && <Fold title={t("society.lead.finished").replace("{0}", String(finished.length))}
        open={finishedOpen} onToggle={() => setFinishedOpen((value) => !value)} testId="team-lead-finished">
        <div className="flex flex-col gap-1">
          {finished.map((goal) => <FinishedRow key={goal.goal_id} {...card(goal)} onCancel={() => undefined} />)}
        </div>
      </Fold>}

      <Fold title={t("society.lead.setup")} open={setupOpen} onToggle={() => onSetupOpen(!setupOpen)} testId="team-lead-setup">
        <div className="flex flex-col gap-4 pt-1">
          <div className="flex flex-col gap-2">
            <label htmlFor="team-mission" className="text-sm font-medium text-foreground">{t("society.lead.mission")}</label>
            <Textarea id="team-mission" value={mission} maxLength={4000} rows={3}
              placeholder={t("society.lead.mission_placeholder")} onChange={(event) => setMission(event.target.value)} />
            {mission.trim() !== team.mission && <div>
              <Button size="sm" variant="secondary" disabled={Boolean(busy)}
                onClick={() => void run("mission", () => setSocietyTeamMission(group.group_id, mission))}>
                {t("society.lead.mission_save")}
              </Button>
            </div>}
          </div>

          <div className="flex flex-col gap-2">
            <p id="team-initiative" className="text-sm font-medium text-foreground">{t("society.lead.initiative")}</p>
            <div role="radiogroup" aria-labelledby="team-initiative" className="flex flex-col gap-1.5">
              {MODES.map((value) => <button key={value} type="button" role="radio" aria-checked={mode === value}
                disabled={Boolean(busy)} data-testid={`team-initiative-${value}`} onClick={() => { if (mode !== value) setMode(value); }}
                className={cn("flex items-start gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                  mode === value ? "border-border-strong bg-secondary" : "border-border hover:bg-secondary/60")}>
                <i className={cn("mt-1 grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full border", mode === value ? "border-foreground" : "border-muted-foreground")} aria-hidden>
                  {mode === value && <i className="h-1.5 w-1.5 rounded-full bg-foreground" />}
                </i>
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-foreground">{t(`society.lead.initiative_${value}`)}</span>
                  <span className="block text-xs text-muted-foreground">{t(`society.lead.initiative_${value}_hint`).replace("{0}", leadName)}</span>
                </span>
              </button>)}
            </div>
            {mode !== "off" && <div className="flex flex-wrap items-center gap-2">
              <BrandedSelect
                ariaLabel={t("society.lead.initiative_rhythm")}
                testId="team-lead-checkin"
                value={String(rhythm)}
                disabled={Boolean(busy)}
                onValueChange={(value) => setMode(mode, Number(value))}
                className="w-[11rem]"
                options={RHYTHMS.map((minutes) => ({ value: String(minutes), label: t(`society.lead.checkin_${minutes}`) }))}
              />
              <p className="min-w-[10rem] flex-1 text-xs text-muted-foreground">{t("society.lead.initiative_cost")}</p>
            </div>}
            {mode === "drive" && !team.mission.trim() && <p role="note" className="text-xs text-warning">
              {t("society.lead.initiative_needs_mission").replace("{0}", leadName)}
            </p>}
          </div>

          <div className="flex flex-col gap-2">
            <p className="text-sm font-medium text-foreground">{t("society.lead.change")}</p>
            {members.length > 0 && <div className="flex flex-wrap items-center gap-2">
              <BrandedSelect
                ariaLabel={t("society.lead.pick")}
                testId="team-lead-pick"
                value={picked}
                onValueChange={setPicked}
                placeholder={t("society.lead.pick_placeholder")}
                className="min-w-[9rem] flex-1"
                options={members.map((agent) => ({ value: agent.agentId, label: societyDisplayName(agent, assistantName) }))}
              />
              <Button size="sm" variant="secondary" disabled={!picked || Boolean(busy)}
                onClick={() => void leadChanged("pick", () => setSocietyTeamLead(group.group_id, picked)).then((done) => { if (done) setPicked(""); })}>
                {t("society.lead.make")}
              </Button>
            </div>}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" disabled={Boolean(busy)} data-testid="team-lead-create"
                onClick={() => void leadChanged("create", () => createSocietyTeamLead(group.group_id))}>
                {busy === "create" ? <Loader2 className="animate-spin" aria-hidden /> : <Crown aria-hidden />}
                {t("society.lead.create")}
              </Button>
              <Button size="sm" variant="ghost" disabled={Boolean(busy)}
                onClick={() => void leadChanged("remove", () => setSocietyTeamLead(group.group_id, null))}>
                {t("society.lead.remove")}
              </Button>
            </div>
          </div>
        </div>
      </Fold>
    </aside>
  );
}
