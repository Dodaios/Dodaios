import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { BrandedSelect } from "@/components/ui/select";
import { deleteSocietyChatGroup, type SocietyChatGroup } from "@/lib/societyChatGroups";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { useEventStore } from "@/store/events";
import { createAgentChatStore } from "@/store/agentChat";
import type { SocietyAgent } from "../data";
import { AgentSwatch } from "../AgentSwatch";
import { RosterRail } from "../roster/RosterRail";
import { AgentChatPanel } from "./AgentChatPanel";
import { ChatGroupDialog } from "./ChatGroupDialog";
import { MeetingChat } from "./MeetingChat";
import { TeamLeadView } from "./TeamLeadView";

/** What the team's main column shows. */
type GroupView = "lead" | "meeting" | "individual";

/** The team's three views as words on one soft track. */
function viewToggle(active: boolean): string {
  return cn("as-seg-pill", active && "as-seg-pill-on");
}

interface Props {
  group: SocietyChatGroup;
  groups: SocietyChatGroup[];
  roster: SocietyAgent[];
  onOpenAgent: (id: string) => void;
  onOpenGroup: (id: string) => void;
  onCreateAgent: () => void;
  onDeleted: () => void;
  onGroupAgents: (sourceId: string, targetId: string) => void;
  onAddAgentToGroup: (agentId: string, groupId: string) => void;
}

export function ChatGroupPanel({
  group, groups, roster, onOpenAgent, onOpenGroup, onCreateAgent, onDeleted,
  onGroupAgents, onAddAgentToGroup,
}: Props) {
  const t = useT();
  const assistantName = useEventStore((s) => s.assistantName);
  const client = useQueryClient();
  const [leftId, setLeftId] = useState(group.members[0] ?? "");
  const [rightId, setRightId] = useState(group.members[1] ?? "");
  const [editing, setEditing] = useState(false);
  // A team that has a lead opens on the chat with its lead; the others on their meeting.
  const [view, setView] = useState<GroupView>(group.lead_agent_id ? "lead" : "meeting");
  const [confirmUngroup, setConfirmUngroup] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState("");
  const leftStore = useMemo(() => createAgentChatStore("society", `group:${group.group_id}:left`), [group.group_id]);
  const rightStore = useMemo(() => createAgentChatStore("society", `group:${group.group_id}:right`), [group.group_id]);

  useEffect(() => () => {
    leftStore.getState().disconnect();
    rightStore.getState().disconnect();
  }, [leftStore, rightStore]);

  const members = group.members
    .map((id) => roster.find((agent) => agent.agentId === id))
    .filter((agent): agent is SocietyAgent => Boolean(agent));
  const left = members.find((agent) => agent.agentId === leftId) ?? members[0];
  const right = members.find((agent) => agent.agentId === rightId && agent.agentId !== left?.agentId)
    ?? members.find((agent) => agent.agentId !== left?.agentId);

  const remove = async () => {
    setRemoving(true);
    setError("");
    try {
      await deleteSocietyChatGroup(group.group_id);
      await client.invalidateQueries({ queryKey: ["society", "chat-groups"] });
      onDeleted();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      setRemoving(false);
    }
  };

  const pane = (side: "left" | "right", agent: SocietyAgent | undefined) => (
    <section key={side} data-testid={`society-group-pane-${side}`} className="flex min-h-0 min-w-0 flex-col bg-background">
      {agent ? <>
        <header data-testid={`society-group-identity-${side}`}
          className="flex shrink-0 items-center gap-3 px-4 py-3">
          <span data-testid={`society-group-avatar-${side}`} className="grid shrink-0 place-items-center">
            <AgentSwatch agent={agent} size={36} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="sr-only">
              {t(side === "left" ? "society.groups.left_chat" : "society.groups.right_chat")}
            </p>
            {members.length > 2 ? <BrandedSelect
              ariaLabel={t(side === "left" ? "society.groups.left_chat" : "society.groups.right_chat")}
              testId={`society-group-select-${side}`}
              value={agent.agentId}
              onValueChange={(value) => side === "left" ? setLeftId(value) : setRightId(value)}
              className="mt-1 w-full"
              options={members.filter((member) => member.agentId !== (side === "left" ? right?.agentId : left?.agentId))
                .map((member) => ({ value: member.agentId, label: societyDisplayName(member, assistantName) }))}
            /> : <h2 className="truncate text-base font-semibold text-foreground">{societyDisplayName(agent, assistantName)}</h2>}
            <p className="truncate text-xs text-muted-foreground">{agent.title}</p>
          </div>
          <button type="button" onClick={() => onOpenAgent(agent.agentId)}
            className="as-pill-button h-8 px-3 font-normal"
            aria-label={t("society.groups.open_individual").replace("{0}", societyDisplayName(agent, assistantName))}>
            {t("society.groups.open")}
          </button>
        </header>
        <div className="min-h-0 flex-1">
          <AgentChatPanel key={agent.agentId} agent={agent} roster={roster}
            chatStore={side === "left" ? leftStore : rightStore} />
        </div>
      </> : <p className="m-auto p-6 text-center text-sm text-muted-foreground">{t("society.groups.missing_member")}</p>}
    </section>
  );

  const teamFooter = <div className="shrink-0 px-3 py-3">
    {confirmUngroup ? <div role="alertdialog" aria-label={t("society.groups.delete")}
      className="space-y-3 text-[13px] text-foreground">
      <p>{t("society.groups.delete_confirm")}</p>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={() => setConfirmUngroup(false)} disabled={removing}
          className="as-pill-button h-8 px-3 font-normal">
          {t("society.groups.cancel")}
        </button>
        <button type="button" onClick={() => void remove()} disabled={removing}
          className="as-pill-button h-8 bg-destructive px-3 text-destructive-foreground hover:bg-destructive disabled:opacity-50">
          {t("society.groups.delete")}
        </button>
      </div>
    </div> : <div className="flex items-center gap-2">
      <button type="button" onClick={() => setEditing(true)}
        className="as-pill-button h-8 min-w-0 flex-1 px-3 font-normal">
        <span className="truncate">{t("society.groups.edit")}</span>
      </button>
      <button type="button" onClick={() => setConfirmUngroup(true)}
        className="as-pill-button h-8 shrink-0 bg-transparent px-3 font-normal text-muted-foreground hover:text-destructive">
        {t("society.groups.delete")}
      </button>
    </div>}
    {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}</p>}
  </div>;

  return <div className="agent-section grid min-h-0 flex-1 grid-cols-[minmax(240px,280px)_minmax(0,1fr)] bg-background" data-testid="society-group-chat">
    <RosterRail agents={roster} groups={groups} activeGroupId={group.group_id} activeAgentId={null}
      onOpen={onOpenAgent} onOpenGroup={onOpenGroup} onCreate={onCreateAgent}
      onGroupAgents={onGroupAgents} onAddAgentToGroup={onAddAgentToGroup}
      loading={false} sample={false} side="left" className="w-full border-0 jarvis-nav-surface"
      footer={teamFooter} />
    <div className="flex min-h-0 min-w-0 flex-col">
      <div className="flex shrink-0 justify-center px-4 pt-3">
        <div className="as-seg-pills" role="group" aria-label={group.name}>
        <button type="button" aria-pressed={view === "lead"} onClick={() => setView("lead")}
          className={viewToggle(view === "lead")}>{t("society.lead.tab")}</button>
        <button type="button" aria-pressed={view === "meeting"} onClick={() => setView("meeting")}
          className={viewToggle(view === "meeting")}>{t("society.meeting.title")}</button>
        <button type="button" aria-pressed={view === "individual"} onClick={() => setView("individual")}
          className={viewToggle(view === "individual")}>{t("society.meeting.individual")}</button>
        </div>
      </div>
      {view === "lead" ? <TeamLeadView key={group.group_id} group={group} roster={roster} onOpenAgent={onOpenAgent} />
        : view === "meeting" ? <MeetingChat key={group.group_id} group={group} roster={roster} />
        : <div className="grid min-h-0 min-w-0 flex-1 grid-cols-2 divide-x divide-border overflow-hidden bg-background"
          data-testid="society-group-split">
          {pane("left", left)}
          {pane("right", right)}
        </div>}
    </div>
    {editing && <ChatGroupDialog group={group} agents={roster} onClose={() => setEditing(false)} onSaved={onOpenGroup} />}
  </div>;
}
