/**
 * A team's lead, as a chat.
 *
 * The person talks to the lead the way they talk to any agent: one
 * conversation, one composer. The lead plans, hands the work to the members
 * and reports in that same conversation; what the person writes there is their
 * goal, their answer or their go-ahead. What marks this chat as the lead's are
 * the actions above the composer (status, next steps, a look at the team,
 * taking the initiative) and the team panel beside it (`TeamLeadPanel`), which
 * follows the work live through `useSocietyTeam`.
 */
import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Crown, Loader2 } from "lucide-react";
import { runningTurn } from "@/components/agentchat/reduce";
import { Button } from "@/components/ui/button";
import { BrandedSelect } from "@/components/ui/select";
import { useT } from "@/i18n";
import {
  TEAM_GOAL_OPEN,
  createSocietyTeamLead,
  setSocietyTeamLead,
  useSocietyTeam,
  type SocietyChatGroup,
  type SocietyTeam,
} from "@/lib/societyChatGroups";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { cn } from "@/lib/utils";
import { createAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import type { SocietyAgent } from "../data";
import { AgentSwatch } from "../AgentSwatch";
import { AgentChatPanel, CHAT_MEASURE } from "./AgentChatPanel";
import { TeamLeadPanel, initiativeMode } from "./TeamLeadPanel";

/** What only a lead is asked: each sends its sentence as the person's message. */
const LEAD_ACTIONS = ["status", "next", "check", "drive"] as const;

const PANEL_KEY = "society.lead.panel";
/** The team panel starts closed, like an agent's details: the chat comes first. */
function readPanelOpen(): boolean {
  try {
    return window.localStorage.getItem(PANEL_KEY) === "open";
  } catch {
    // Storage is unavailable (a private window): closed.
    return false;
  }
}

function LeadActions({ store, sessionId, leadName }: { store: AgentChatStoreHook; sessionId: string | null; leadName: string }) {
  const t = useT();
  // Held back while a message is on its way or the lead is in a turn: an
  // action is a whole request, and a second click must not queue it twice.
  const busy = store((state) => state.busy || runningTurn(state.timeline) !== null);
  const ready = store((state) => Boolean(sessionId) && state.activeSessionId === sessionId);
  return (
    <div className="shrink-0 px-4 pt-1 sm:px-6">
      <div role="group" aria-label={t("society.lead.actions_label").replace("{0}", leadName)}
        className={cn(CHAT_MEASURE, "flex flex-wrap gap-1.5")} data-testid="team-lead-actions">
        {LEAD_ACTIONS.map((id) => <button key={id} type="button" disabled={busy || !ready}
          data-testid={`team-lead-action-${id}`} title={t(`society.lead.action_${id}_prompt`)}
          onClick={() => void store.getState().send(t(`society.lead.action_${id}_prompt`))}
          className="as-pill-button h-8 bg-transparent px-3.5 font-normal text-muted-foreground shadow-[inset_0_0_0_1px_hsl(var(--border))] hover:text-foreground disabled:pointer-events-none disabled:opacity-50">
          {t(`society.lead.action_${id}`)}
        </button>)}
      </div>
    </div>
  );
}

interface Props {
  group: SocietyChatGroup;
  roster: SocietyAgent[];
  onOpenAgent: (id: string) => void;
}

export function TeamLeadView({ group, roster, onOpenAgent }: Props) {
  const t = useT();
  const client = useQueryClient();
  const assistantName = useEventStore((s) => s.assistantName);
  const query = useSocietyTeam(group.group_id);
  const team = query.data;
  const [busy, setBusy] = useState("");
  const [problem, setProblem] = useState("");
  const [picked, setPicked] = useState("");
  const [panelOpen, setPanelOpen] = useState(readPanelOpen);
  const [setupOpen, setSetupOpen] = useState(false);
  // The lead's chat has a store of its own, so it stays open beside the members' chats.
  const leadStore = useMemo(() => createAgentChatStore("society", `group:${group.group_id}:lead`), [group.group_id]);
  useEffect(() => () => leadStore.getState().disconnect(), [leadStore]);

  const agentOf = (id: string | null | undefined) => roster.find((agent) => agent.agentId === id);
  const lead = agentOf(team?.lead_agent_id);
  const leadName = lead ? societyDisplayName(lead, assistantName) : (team?.lead_agent_id ?? "");
  // The assistant already leads every agent; a team lead is one of the others.
  const candidates = group.members.map(agentOf)
    .filter((agent): agent is SocietyAgent => Boolean(agent) && agent!.tier !== "lead" && agent!.lifecycle !== "archived");

  /** Run one team action: the answer replaces the team, a refusal shows as written. */
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
  const leadChanged = async (key: string, action: () => Promise<SocietyTeam>): Promise<boolean> => {
    if (!(await run(key, action))) return false;
    setPicked("");
    await Promise.all([
      client.invalidateQueries({ queryKey: ["society", "chat-groups"] }),
      client.invalidateQueries({ queryKey: ["society", "roster"] }),
    ]);
    return true;
  };

  const togglePanel = (open: boolean) => {
    setPanelOpen(open);
    try {
      window.localStorage.setItem(PANEL_KEY, open ? "open" : "closed");
    } catch {
      // Storage is unavailable: the choice holds for this visit.
    }
  };
  const openSetup = () => {
    togglePanel(true);
    setSetupOpen(true);
  };

  if (query.isLoading) {
    return <p className="m-auto p-6 text-sm text-muted-foreground" role="status">{t("society.lead.loading")}</p>;
  }
  if (query.isError || !team) {
    return <p className="m-auto p-6 text-sm text-destructive" role="alert">{String(query.error ?? "")}</p>;
  }

  if (!team.lead_agent_id) {
    return (
      <section className="flex min-h-0 flex-1 flex-col overflow-y-auto bg-background" data-testid="team-lead-view">
        <div className="mx-auto flex w-full max-w-[36rem] flex-col gap-4 px-6 py-12">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-secondary text-foreground"><Crown className="h-5 w-5" aria-hidden /></span>
          <h2 className="text-lg font-semibold text-foreground">{t("society.lead.none_title")}</h2>
          <p className="text-sm text-muted-foreground">{t("society.lead.none_body")}</p>
          <div>
            <Button size="sm" disabled={Boolean(busy)} data-testid="team-lead-create"
              onClick={() => void leadChanged("create", () => createSocietyTeamLead(group.group_id))}>
              {busy === "create" ? <Loader2 className="animate-spin" aria-hidden /> : <Crown aria-hidden />}
              {t("society.lead.create")}
            </Button>
          </div>
          {candidates.length > 0 && <>
            <p className="pt-2 text-sm font-medium text-foreground">{t("society.lead.pick")}</p>
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
          </>}
          {problem && <p role="alert" className="text-sm text-destructive">{problem}</p>}
        </div>
      </section>
    );
  }

  const open = team.goals.filter((goal) => TEAM_GOAL_OPEN.includes(goal.state));
  const asking = open.find((goal) => goal.state === "needs_input");
  const running = open.find((goal) => goal.state === "running");
  const paused = open.find((goal) => goal.state === "paused");
  const status = !team.lead_available ? t("society.lead.unavailable")
    : asking ? t("society.lead.status_needs_input").replace("{0}", leadName)
    : team.working ? t("society.lead.working").replace("{0}", leadName)
    : running ? t("society.lead.status_running").replace("{0}", running.title)
    : paused ? t("society.lead.status_paused").replace("{0}", paused.title)
    : t("society.lead.status_idle").replace("{0}", leadName);
  const mode = initiativeMode(team);

  return (
    <section className="flex min-h-0 flex-1 flex-col bg-background" data-testid="team-lead-view">
      {/* Like an agent's chat: one name pill in the middle; the team's two
          controls sit quietly on the right as words. */}
      <header className="relative flex h-14 shrink-0 items-center justify-center gap-2 px-4">
        <div className="as-name-pill" title={t("society.lead.role")}>
          <span className="as-avatar">{lead ? <AgentSwatch agent={lead} size={24} /> : null}</span>
          <span className="as-pill-name">{leadName}</span>
          <p role="status" data-testid="team-lead-status"
            className={cn("as-pill-status", !team.lead_available ? "text-destructive" : asking ? "text-warning" : "")}>
            {status}
          </p>
        </div>
        <div className="absolute right-4 flex items-center gap-1.5">
          <button type="button" onClick={openSetup} data-testid="team-lead-initiative" data-mode={mode}
            title={t(`society.lead.initiative_${mode}_hint`).replace("{0}", leadName)}
            className="as-pill-button h-8 bg-transparent px-3 font-normal text-muted-foreground hover:text-foreground">
            <i className={cn("h-1.5 w-1.5 rounded-full", mode === "off" ? "bg-muted-foreground/40" : "bg-success")} aria-hidden />
            {t(`society.lead.initiative_${mode}`)}
          </button>
          <button type="button" aria-pressed={panelOpen} onClick={() => togglePanel(!panelOpen)} data-testid="team-lead-panel-toggle"
            className={cn("as-pill-button h-8 px-3", !panelOpen && "bg-transparent font-normal text-muted-foreground hover:text-foreground")}>
            {t("society.lead.panel_title")}
            {!panelOpen && open.length > 0 && <span className={cn("rounded-full px-1.5 text-[12px]", asking ? "bg-warning/20 text-warning" : "bg-secondary text-muted-foreground")}>{open.length}</span>}
          </button>
        </div>
      </header>

      {problem && <p role="alert" className="shrink-0 border-b border-border px-4 py-2 text-sm text-destructive">{problem}</p>}

      <div className="relative flex min-h-0 flex-1">
        <div className="min-h-0 min-w-0 flex-1">
          {lead ? <AgentChatPanel key={lead.agentId} agent={lead} roster={roster} chatStore={leadStore}
            composerExtras={<LeadActions store={leadStore} sessionId={lead.chatSessionId ?? null} leadName={leadName} />} />
            : <p className="m-auto p-6 text-center text-sm text-muted-foreground">{t("society.lead.unavailable")}</p>}
        </div>
        {panelOpen && <TeamLeadPanel team={team} group={group} roster={roster} busy={busy}
          setupOpen={setupOpen} onSetupOpen={setSetupOpen} run={run} leadChanged={leadChanged} onOpenAgent={onOpenAgent} />}
      </div>
    </section>
  );
}
