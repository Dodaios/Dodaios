/**
 * The team's lead and its work: who manages the team, what the team is for,
 * the goals the person gave it, and every task the lead handed out.
 *
 * The person only sets a goal. The lead plans it, hands tasks to the members,
 * is woken with each result and reports back; this board follows that live
 * (`useSocietyTeam`) and offers the few moments that are the person's: answer
 * the lead's question, continue a paused goal, stop one.
 */
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Crown, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandedSelect } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useT } from "@/i18n";
import {
  TEAM_GOAL_OPEN,
  cancelSocietyTeamGoal,
  createSocietyTeamLead,
  messageSocietyTeamGoal,
  resumeSocietyTeamGoal,
  setSocietyTeamCheckin,
  setSocietyTeamLead,
  setSocietyTeamMission,
  startSocietyTeamGoal,
  useSocietyTeam,
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

/** The server's check-in intervals (jarvis/society/team_lead.py CHECKIN_MINUTES). */
const CHECKIN_CHOICES = [0, 60, 240, 1440] as const;
/** Reasons a goal waits that have their own sentence; anything else shows as written. */
const NOTE_KEYS = new Set([
  "society_paused", "interrupted", "turn_budget", "lead_busy", "lead_unavailable", "stalled",
]);

const DOT: Record<string, string> = {
  running: "bg-success",
  assigned: "bg-success",
  needs_input: "bg-warning",
  waiting: "bg-warning",
  paused: "bg-warning",
  queued: "bg-muted-foreground",
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

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

interface Props {
  group: SocietyChatGroup;
  roster: SocietyAgent[];
  onOpenAgent: (id: string) => void;
}

export function TeamLeadBoard({ group, roster, onOpenAgent }: Props) {
  const t = useT();
  const client = useQueryClient();
  const assistantName = useEventStore((s) => s.assistantName);
  const query = useSocietyTeam(group.group_id);
  const team = query.data;
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const [picked, setPicked] = useState("");
  const [changing, setChanging] = useState(false);
  const [goalText, setGoalText] = useState("");
  const [mission, setMission] = useState("");
  const savedMission = useRef("");
  const serverMission = team?.mission;

  // The saved mission fills the field until the person starts editing it.
  useEffect(() => {
    if (serverMission === undefined) return;
    const previous = savedMission.current;
    savedMission.current = serverMission;
    setMission((current) => (current === previous ? serverMission : current));
  }, [serverMission]);

  const agentOf = (id: string | null | undefined) => roster.find((agent) => agent.agentId === id);
  const nameOf = (id: string | null | undefined) => {
    const agent = agentOf(id);
    return agent ? societyDisplayName(agent, assistantName) : (id ?? "");
  };
  const lead = agentOf(team?.lead_agent_id);
  const leadName = nameOf(team?.lead_agent_id);
  const members = group.members.map(agentOf).filter((agent): agent is SocietyAgent => Boolean(agent));
  // Jarvis already leads every agent; a team lead is one of the others.
  const candidates = members.filter((agent) => agent.tier !== "lead" && agent.lifecycle !== "archived"
    && agent.agentId !== team?.lead_agent_id);

  /** Run one board action: the answer replaces the board, a refusal shows as written. */
  const run = async (key: string, action: () => Promise<SocietyTeam>): Promise<boolean> => {
    if (busy) return false;
    setBusy(key);
    setProblem("");
    try {
      client.setQueryData(["society", "team", group.group_id], await action());
      return true;
    } catch (cause) {
      setProblem(cause instanceof Error ? cause.message : String(cause));
      return false;
    } finally {
      setBusy("");
    }
  };
  /** A lead change also changes the roster (tier) and the group (members). */
  const leadChanged = async (key: string, action: () => Promise<SocietyTeam>) => {
    if (!(await run(key, action))) return;
    setChanging(false);
    setPicked("");
    await Promise.all([
      client.invalidateQueries({ queryKey: ["society", "chat-groups"] }),
      client.invalidateQueries({ queryKey: ["society", "roster"] }),
    ]);
  };

  const submitGoal = async (event: FormEvent) => {
    event.preventDefault();
    const text = goalText.trim();
    if (!text) return;
    if (await run("goal", () => startSocietyTeamGoal(group.group_id, text))) setGoalText("");
  };

  if (query.isLoading) {
    return <p className="m-auto p-6 text-sm text-muted-foreground" role="status">{t("society.lead.loading")}</p>;
  }
  if (query.isError || !team) {
    return <p className="m-auto p-6 text-sm text-destructive" role="alert">{String(query.error ?? "")}</p>;
  }

  const picker = (
    <div className="flex flex-wrap items-center gap-2">
      <BrandedSelect
        ariaLabel={t("society.lead.pick")}
        testId="team-lead-pick"
        value={picked}
        onValueChange={setPicked}
        placeholder={t("society.lead.pick_placeholder")}
        className="min-w-[12rem] flex-1"
        options={candidates.map((agent) => ({ value: agent.agentId, label: societyDisplayName(agent, assistantName) }))}
      />
      <Button size="sm" variant="secondary" disabled={!picked || Boolean(busy)}
        onClick={() => void leadChanged("pick", () => setSocietyTeamLead(group.group_id, picked))}>
        {t("society.lead.make")}
      </Button>
    </div>
  );

  const createButton = (variant: "default" | "secondary") => (
    <Button size="sm" variant={variant} disabled={Boolean(busy)} data-testid="team-lead-create"
      onClick={() => void leadChanged("create", () => createSocietyTeamLead(group.group_id))}>
      {busy === "create" ? <Loader2 className="animate-spin" aria-hidden /> : <Crown aria-hidden />}
      {t("society.lead.create")}
    </Button>
  );

  if (!team.lead_agent_id) {
    return (
      <section className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background" data-testid="team-lead-board">
        <div className="mx-auto flex w-full max-w-[36rem] flex-col gap-4 px-6 py-12">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-secondary text-foreground"><Crown className="h-5 w-5" aria-hidden /></span>
          <h2 className="text-lg font-semibold text-foreground">{t("society.lead.none_title")}</h2>
          <p className="text-sm text-muted-foreground">{t("society.lead.none_body")}</p>
          <div>{createButton("default")}</div>
          {candidates.length > 0 && <>
            <p className="pt-2 text-sm font-medium text-foreground">{t("society.lead.pick")}</p>
            {picker}
          </>}
          {problem && <p role="alert" className="text-sm text-destructive">{problem}</p>}
        </div>
      </section>
    );
  }

  const open = team.goals.filter((goal) => TEAM_GOAL_OPEN.includes(goal.state))
    .sort((a, b) => Number(b.state !== "queued") - Number(a.state !== "queued") || a.created_ms - b.created_ms);
  const finished = team.goals.filter((goal) => !TEAM_GOAL_OPEN.includes(goal.state));

  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background" data-testid="team-lead-board">
      <div className="mx-auto flex w-full max-w-[52rem] flex-col gap-6 px-4 py-5 sm:px-6">
        <header className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card p-3">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-secondary">
            {lead ? <AgentSwatch agent={lead} size={38} /> : <Crown className="h-5 w-5" aria-hidden />}
          </span>
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              <Crown className="h-3 w-3" aria-hidden />{t("society.lead.role")}
            </p>
            <h2 className="truncate text-base font-semibold text-foreground">{leadName}</h2>
            <p className="truncate text-xs text-muted-foreground" role="status">
              {!team.lead_available ? t("society.lead.unavailable")
                : team.working ? t("society.lead.working").replace("{0}", leadName)
                : (lead?.title ?? "")}
            </p>
          </div>
          {lead && <Button size="sm" variant="secondary" onClick={() => onOpenAgent(lead.agentId)}>{t("society.lead.open_chat")}</Button>}
          <Button size="sm" variant="ghost" aria-expanded={changing} onClick={() => setChanging((value) => !value)}>
            {t("society.lead.change")}<ChevronDown className={cn("transition-transform", changing && "rotate-180")} aria-hidden />
          </Button>
          {changing && <div className="flex w-full flex-col gap-2 border-t border-border pt-3">
            {candidates.length > 0 && picker}
            <div className="flex flex-wrap gap-2">
              {createButton("secondary")}
              <Button size="sm" variant="ghost" disabled={Boolean(busy)}
                onClick={() => void leadChanged("remove", () => setSocietyTeamLead(group.group_id, null))}>
                {t("society.lead.remove")}
              </Button>
            </div>
          </div>}
        </header>

        {problem && <p role="alert" className="text-sm text-destructive">{problem}</p>}

        <form onSubmit={(event) => void submitGoal(event)} className="flex flex-col gap-2">
          <label htmlFor="team-goal" className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{t("society.lead.goal_label")}</label>
          <Textarea id="team-goal" value={goalText} maxLength={20000} rows={3}
            placeholder={t("society.lead.goal_placeholder")}
            onChange={(event) => setGoalText(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void submitGoal(event); }} />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">{t("society.lead.goal_hint").replace("{0}", leadName)}</p>
            <Button type="submit" size="sm" disabled={!goalText.trim() || Boolean(busy) || !team.lead_available}>
              {busy === "goal" && <Loader2 className="animate-spin" aria-hidden />}{t("society.lead.goal_send")}
            </Button>
          </div>
        </form>

        <Section title={t("society.lead.goals")}>
          {open.length === 0 && <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
            {t("society.lead.goals_empty").replace("{0}", leadName)}
          </p>}
          {open.map((goal) => <GoalCard key={goal.goal_id} goal={goal} leadName={leadName} assistantName={assistantName}
            agentOf={agentOf} nameOf={nameOf} busy={busy}
            onMessage={(text) => run(`message:${goal.goal_id}`, () => messageSocietyTeamGoal(group.group_id, goal.goal_id, text))}
            onResume={() => void run(`resume:${goal.goal_id}`, () => resumeSocietyTeamGoal(group.group_id, goal.goal_id))}
            onCancel={() => void run(`cancel:${goal.goal_id}`, () => cancelSocietyTeamGoal(group.group_id, goal.goal_id))} />)}
        </Section>

        {finished.length > 0 && <details className="group/finished">
          <summary className="cursor-pointer list-none text-xs font-medium uppercase tracking-wide text-muted-foreground hover:text-foreground">
            <ChevronDown className="mr-1 inline h-3.5 w-3.5 -rotate-90 transition-transform group-open/finished:rotate-0" aria-hidden />
            {t("society.lead.finished").replace("{0}", String(finished.length))}
          </summary>
          <div className="mt-2 flex flex-col gap-2">
            {finished.map((goal) => <GoalCard key={goal.goal_id} goal={goal} leadName={leadName} assistantName={assistantName}
              agentOf={agentOf} nameOf={nameOf} busy={busy}
              onMessage={async () => false}
              onResume={() => void run(`resume:${goal.goal_id}`, () => resumeSocietyTeamGoal(group.group_id, goal.goal_id))}
              onCancel={() => undefined} />)}
          </div>
        </details>}

        <Section title={t("society.lead.mission")}>
          <Textarea value={mission} maxLength={4000} rows={2} aria-label={t("society.lead.mission")}
            placeholder={t("society.lead.mission_placeholder")} onChange={(event) => setMission(event.target.value)} />
          {mission.trim() !== team.mission && <div>
            <Button size="sm" variant="secondary" disabled={Boolean(busy)}
              onClick={() => void run("mission", () => setSocietyTeamMission(group.group_id, mission))}>
              {t("society.lead.mission_save")}
            </Button>
          </div>}
        </Section>

        <Section title={t("society.lead.checkin")}>
          <div className="flex flex-wrap items-center gap-3">
            <BrandedSelect
              ariaLabel={t("society.lead.checkin")}
              testId="team-lead-checkin"
              value={String(team.checkin_minutes)}
              disabled={Boolean(busy)}
              onValueChange={(value) => void run("checkin", () => setSocietyTeamCheckin(group.group_id, Number(value)))}
              className="w-[12rem]"
              options={CHECKIN_CHOICES.map((minutes) => ({ value: String(minutes), label: t(`society.lead.checkin_${minutes}`) }))}
            />
            <p className="min-w-[14rem] flex-1 text-xs text-muted-foreground">{t("society.lead.checkin_hint").replace("{0}", leadName)}</p>
          </div>
        </Section>
      </div>
    </section>
  );
}

function TaskRow({ task, agent, name }: { task: SocietyTeamTask; agent: SocietyAgent | undefined; name: string }) {
  const t = useT();
  const [shown, setShown] = useState(false);
  return (
    <li className="flex flex-col gap-1.5 py-2" data-testid={`team-task-${task.task_id}`}>
      <div className="flex items-center gap-2">
        {agent ? <AgentSwatch agent={agent} size={22} /> : null}
        <span className="min-w-0 flex-1 truncate text-sm text-foreground">
          <span className="font-medium">{name}</span>
          <span className="text-muted-foreground"> · {task.title}</span>
        </span>
        {task.result && <button type="button" aria-expanded={shown} onClick={() => setShown((value) => !value)}
          className="shrink-0 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground">
          {t(shown ? "society.lead.hide_result" : "society.lead.show_result")}
        </button>}
        <StateChip state={task.state} label={t(`society.lead.task_state_${task.state}`)} />
      </div>
      {shown && <div className="ml-7 rounded-lg bg-secondary/50 px-3 py-2 text-sm"><Prose text={task.result} /></div>}
    </li>
  );
}

function GoalCard({ goal, leadName, assistantName, agentOf, nameOf, busy, onMessage, onResume, onCancel }: {
  goal: SocietyTeamGoal;
  leadName: string;
  assistantName: string;
  agentOf: (id: string) => SocietyAgent | undefined;
  nameOf: (id: string) => string;
  busy: string;
  onMessage: (text: string) => Promise<boolean>;
  onResume: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const [reply, setReply] = useState("");
  const waiting = goal.state === "needs_input";
  const live = goal.state === "running" || waiting;
  const source = goal.source === "jarvis" ? t("society.lead.source_jarvis").replace("{0}", assistantName)
    : goal.source === "lead" ? t("society.lead.source_lead").replace("{0}", leadName)
    : goal.source === "assignment" ? t("society.lead.source_assignment") : "";
  // The title is the goal's first line, cut short when it is long. Show the
  // line in full as the heading and only what the text adds to it below.
  const text = goal.text.trim();
  const firstLine = text.split("\n", 1)[0].trim();
  const stem = goal.title.endsWith("\u2026") ? goal.title.slice(0, -1).trimEnd() : goal.title;
  const ownsTitle = stem.length > 0 && firstLine.replace(/\s+/g, " ").startsWith(stem);
  const heading = ownsTitle ? firstLine : goal.title;
  const detailText = ownsTitle ? text.slice(text.indexOf(firstLine) + firstLine.length).trim() : text;
  const detail = goal.note.startsWith("error:") ? goal.note.slice(6) : "";
  const note = goal.state !== "paused" && goal.state !== "failed" ? ""
    : detail ? t("society.lead.note_error").replace("{0}", detail)
    : NOTE_KEYS.has(goal.note) ? t(`society.lead.note_${goal.note}`) : "";

  const send = async (event: FormEvent) => {
    event.preventDefault();
    const text = reply.trim();
    if (text && await onMessage(text)) setReply("");
  };

  return (
    <article className={cn("flex flex-col gap-3 rounded-xl border bg-card p-4", waiting ? "border-warning/50" : "border-border")}
      data-testid={`team-goal-${goal.goal_id}`} data-state={goal.state}>
      <header className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h4 className="text-sm font-semibold text-foreground">{heading}</h4>
          {detailText && <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">{detailText}</p>}
          {source && <p className="mt-1 text-xs text-muted-foreground">{source}</p>}
        </div>
        <StateChip state={goal.state} label={t(`society.lead.state_${goal.state}`)} />
      </header>

      {note && <p className="text-sm text-muted-foreground">{note}</p>}

      {goal.tasks.length > 0 && <ul className="divide-y divide-border border-y border-border">
        {goal.tasks.map((task) => <TaskRow key={task.task_id} task={task} agent={agentOf(task.agent_id)} name={nameOf(task.agent_id)} />)}
      </ul>}
      {goal.tasks.length === 0 && goal.state === "running" && <p className="text-xs text-muted-foreground">{t("society.lead.tasks_none").replace("{0}", leadName)}</p>}

      {goal.report && <div className="flex flex-col gap-1">
        <p className="text-xs font-medium text-muted-foreground">
          {t(waiting ? "society.lead.question" : "society.lead.report").replace("{0}", leadName)}
        </p>
        <div className="rounded-lg bg-secondary/50 px-3 py-2 text-sm"><Prose text={goal.report} /></div>
      </div>}

      {live && <form onSubmit={(event) => void send(event)} className="flex items-end gap-2">
        <Textarea value={reply} rows={1} maxLength={20000} className="min-h-[36px] flex-1"
          aria-label={t(waiting ? "society.lead.answer_placeholder" : "society.lead.message_placeholder").replace("{0}", leadName)}
          placeholder={t(waiting ? "society.lead.answer_placeholder" : "society.lead.message_placeholder").replace("{0}", leadName)}
          onChange={(event) => setReply(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) void send(event); }} />
        <Button type="submit" size="sm" variant={waiting ? "default" : "secondary"} disabled={!reply.trim() || Boolean(busy)}>
          {t("society.lead.send")}
        </Button>
      </form>}

      {goal.state !== "done" && goal.state !== "cancelled" && <div className="flex flex-wrap justify-end gap-2">
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
