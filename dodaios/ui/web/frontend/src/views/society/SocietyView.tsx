import { useCallback, useMemo, useState, useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useLocaleChunk } from "@/i18n";
import { cn } from "@/lib/utils";
import { AgentCardOverlay } from "@/components/society/card/AgentCardOverlay";
import { useQuickCreateAgent, useSocietyRoster } from "@/components/society/data";
import { isCreateCancelled } from "@/components/society/create/createAgentStore";
import { RosterRail } from "@/components/society/roster/RosterRail";
import { useRosterActivity } from "@/components/society/roster/useRosterActivity";
import { useModelMenuData } from "@/components/society/chat/useModelMenuData";
import { ChatGroupPanel } from "@/components/society/chat/ChatGroupPanel";
import { useSocietyChatStore } from "@/components/society/chat/AgentChatPanel";
import { chatGroupsKnown, createSocietyChatGroup, updateSocietyChatGroup, useSocietyChatGroups } from "@/lib/societyChatGroups";
import { useAgentChatStore } from "@/store/agentChat";
import { forgetLastAgentId, rememberLastAgentId, storedLastAgentId } from "./lastAgent";
import { revealCard, setAgentOnScreen, takeAgentRequest, useAgentNavigation } from "./agentNavigation";

export function SocietyView() {
  const queryClient = useQueryClient();
  useModelMenuData();
  useLocaleChunk("society");
  const roster = useSocietyRoster();
  const agents = useMemo(() => roster.data?.agents ?? [], [roster.data]);
  // Only rows that really are sample rows say so; a roster still loading is not one.
  const sample = roster.data?.sample === true;
  const groupsQuery = useSocietyChatGroups(!sample);
  const groups = useMemo(() => groupsQuery.data ?? [], [groupsQuery.data]);
  const teamsPending = !sample && !chatGroupsKnown(groupsQuery);
  const [openGroupId, setOpenGroupId] = useState<string | null>(null);
  const openGroup = groups.find((group) => group.group_id === openGroupId) ?? null;
  const [openAgentId, setOpenAgentId] = useState<string | null>(storedLastAgentId);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  const quickCreate = useQuickCreateAgent();
  const [groupError, setGroupError] = useState("");

  const openAgent = useMemo(
    () => agents.find((a) => a.agentId === openAgentId) ?? agents.find((a) => a.tier === "lead") ?? agents[0] ?? null,
    [agents, openAgentId],
  );
  // The workspace reads its own; only the bare roster (nobody open) needs this.
  const standaloneActivity = useRosterActivity(agents, useSocietyChatStore, !openAgent && !openGroupId);

  const selectAgent = useCallback((agentId: string | null) => {
    setOpenGroupId(null);
    setOpenAgentId(agentId);
    if (agentId) rememberLastAgentId(agentId);
  }, []);

  const selectGroup = useCallback((groupId: string) => {
    useSocietyChatStore.getState().disconnect();
    setOpenGroupId(groupId);
    setOpenAgentId(null);
  }, []);

  const groupAgents = useCallback((sourceId: string, targetId: string) => {
    const source = agents.find((agent) => agent.agentId === sourceId);
    const target = agents.find((agent) => agent.agentId === targetId);
    if (sample || !source || !target || sourceId === targetId) return;
    setGroupError("");
    void createSocietyChatGroup(`${source.name} + ${target.name}`, [sourceId, targetId])
      .then(async (group) => {
        await queryClient.invalidateQueries({ queryKey: ["society", "chat-groups"] });
        selectGroup(group.group_id);
      })
      .catch((error) => setGroupError(error instanceof Error ? error.message : String(error)));
  }, [agents, queryClient, sample, selectGroup]);

  const addAgentToGroup = useCallback((agentId: string, groupId: string) => {
    const group = groups.find((entry) => entry.group_id === groupId);
    if (sample || !group || group.members.includes(agentId)) return;
    setGroupError("");
    void updateSocietyChatGroup(groupId, group.name, [...group.members, agentId])
      .then(async () => {
        await queryClient.invalidateQueries({ queryKey: ["society", "chat-groups"] });
        selectGroup(groupId);
      })
      .catch((error) => setGroupError(error instanceof Error ? error.message : String(error)));
  }, [groups, queryClient, sample, selectGroup]);

  useEffect(() => {
    if (openGroupId && groupsQuery.data && !groups.some((group) => group.group_id === openGroupId)) setOpenGroupId(null);
  }, [groups, groupsQuery.data, openGroupId]);

  useEffect(() => {
    if (openAgentId && agents.length > 0 && !agents.some((agent) => agent.agentId === openAgentId)) {
      setOpenAgentId(null);
      forgetLastAgentId();
    }
  }, [agents, openAgentId]);

  // The plus opens the "new agent" dialog (name, runtime, companion); the new
  // agent's chat opens after it. Closing the dialog is not an error.
  const createAgent = useCallback(() => {
    if (creating) return;
    setCreating(true);
    setCreateError("");
    void quickCreate()
      .then((agent) => selectAgent(agent.agentId))
      .catch((error) => {
        if (!isCreateCancelled(error)) setCreateError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => setCreating(false));
  }, [creating, quickCreate, selectAgent]);

  // "Needs you": tell the notifier which agent is on screen, and honour a
  // request to open an agent at one of its cards (agentNavigation.openAgent).
  const onScreenId = !openGroup ? openAgent?.agentId ?? null : null;
  useEffect(() => {
    setAgentOnScreen(onScreenId ? { agentId: onScreenId } : null);
  }, [onScreenId]);
  useEffect(() => () => setAgentOnScreen(null), []);

  const navigation = useAgentNavigation((s) => s.request);
  useEffect(() => {
    if (!navigation) return;
    const target = agents.find((agent) => agent.agentId === navigation.agentId);
    if (!target) {
      // Still loading: keep the request. Gone (or only the sample roster): drop it.
      if (!roster.isLoading) takeAgentRequest();
      return;
    }
    const taken = takeAgentRequest();
    if (!taken) return;
    selectAgent(taken.agentId);
    // The lead's card is the front-page chat, which holds many sessions.
    if (target.tier === "lead" && taken.sessionId && !taken.sessionId.startsWith("society:")) {
      const chat = useAgentChatStore.getState();
      if (chat.activeSessionId !== taken.sessionId) chat.openSession(taken.sessionId);
    }
    void revealCard({ cardRef: taken.cardRef, kind: taken.kind });
  }, [navigation, agents, roster.isLoading, selectAgent]);

  return (
    <div className="relative flex h-full min-h-0 w-full flex-col" data-testid="society-view" data-tour="agents-page">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {groupError && <p role="alert" className="bg-card px-4 py-2 text-sm text-destructive">{groupError}</p>}
        {createError && <p role="alert" className="bg-card px-4 py-2 text-sm text-destructive">{createError}</p>}
        <div className={cn("flex min-h-0 flex-1 flex-col [--as-caption-gap:2rem]", !openAgent || openGroup ? "pt-8" : null)}>
        {openGroup ? (
          <ChatGroupPanel group={openGroup} groups={groups} roster={agents} onOpenAgent={selectAgent} onOpenGroup={selectGroup}
            onCreateAgent={createAgent} onDeleted={() => setOpenGroupId(null)}
            onGroupAgents={groupAgents} onAddAgentToGroup={addAgentToGroup} />
        ) : openAgent ? (
          <AgentCardOverlay embedded active agent={openAgent} roster={agents} rosterLoading={roster.isLoading} teamsPending={teamsPending}
            groups={groups} onSelectGroup={selectGroup}
            onGroupAgents={sample ? undefined : groupAgents} onAddAgentToGroup={sample ? undefined : addAgentToGroup}
            sample={sample} onSelectAgent={selectAgent} onCreate={createAgent}
            onClose={() => setOpenAgentId(null)} />
        ) : (
          <RosterRail agents={agents} loading={roster.isLoading} teamsPending={teamsPending} sample={sample}
            groups={groups} onOpenGroup={selectGroup}
            onGroupAgents={sample ? undefined : groupAgents} onAddAgentToGroup={sample ? undefined : addAgentToGroup}
            activeAgentId={null} onOpen={selectAgent} onCreate={createAgent} side="left"
            activity={standaloneActivity} keyboard
            className="w-full border-0" />
        )}
        </div>
      </div>
    </div>
  );
}

export default SocietyView;
