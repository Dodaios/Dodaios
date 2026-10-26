import { lazy, Suspense, useCallback, useMemo, useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Orbit, Users } from "lucide-react";

import { setMapFullscreen } from "@/lib/mapFullscreen";
import { inDesktopShell } from "@/lib/nativeDrop";
import { useLocaleChunk, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { CAPTION_ICON_STROKE, CAPTION_SEGMENT_OFF, CAPTION_SEGMENT_ON, CAPTION_TRACK } from "@/components/layout/captionSwitch";
import { AgentCardOverlay } from "@/components/society/card/AgentCardOverlay";
import { BrowserProfilesButton } from "@/components/society/browser/BrowserProfilesButton";
import { BUILDING_CARDS, isBuildingPlace, type BuildingPlace } from "@/components/society/card/buildingCards";
import { DeferredSocietyDialog } from "@/components/society/card/DeferredSocietyDialog";
import type { PlaceId } from "@/components/society/world/islandLayout";
import { useQuickCreateAgent, useSocietyRoster } from "@/components/society/data";
import { isCreateCancelled } from "@/components/society/create/createAgentStore";
import { RosterRail } from "@/components/society/roster/RosterRail";
import { useRosterActivity } from "@/components/society/roster/useRosterActivity";
import { useModelMenuData } from "@/components/society/chat/useModelMenuData";
import { ChatGroupPanel } from "@/components/society/chat/ChatGroupPanel";
import { useSocietyChatStore } from "@/components/society/chat/AgentChatPanel";
import { chatGroupsKnown, createSocietyChatGroup, updateSocietyChatGroup, useSocietyChatGroups } from "@/lib/societyChatGroups";
import { CanvasActivity } from "@/hooks/useCanvasAwake";
import { AttentionBell } from "@/components/society/attention/AttentionBell";
import { useAgentChatStore } from "@/store/agentChat";
import { forgetLastAgentId, rememberLastAgentId, storedLastAgentId } from "./lastAgent";
import { revealCard, setAgentOnScreen, takeAgentRequest, useAgentNavigation } from "./agentNavigation";

/** The page's two faces, in caption order: the agents, then the Verse. */
const MODES = [
  { value: "agents", labelKey: "society.roster.title", titleKey: "society.roster.title", Icon: Users },
  { value: "world", labelKey: "society.shell.mode_verse", titleKey: "society.world.mode_map", Icon: Orbit },
] as const;

// Small and three.js-free: the fallback in front of the lazy Verse chunk.
import { VerseLoadingScreen, preloadLoadingArt } from "@/components/society/verse/VerseLoadingScreen";

/** A labelled segment on the caption track: icon plus word, the "on" one lifted. */
const MODE_SEGMENT =
  "relative z-[1] flex h-full items-center gap-1.5 rounded-full border px-3 text-xs font-medium " +
  "transition-[background-color,color,border-color,box-shadow] duration-150 ease-out motion-reduce:transition-none " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const MODE_SEGMENT_ON =
  "border-border-strong/60 bg-background shadow-[0_1px_2px_rgb(var(--scrim-rgb)/0.25)] dark:border-border-strong dark:bg-surface-raised";

const loadWorld = () => import("@/views/DodaiosAgentsView").then((m) => ({ default: m.DodaiosAgentsView }));
const JarvisAgentsBoard = lazy(loadWorld);
const preloadWorld = () => { preloadLoadingArt(); void loadWorld().catch((error) => console.debug("World preload unavailable", error)); };

// Do not evaluate either dialog's 3D dependencies until someone opens it.
const loadBuildingDialog = () => import("@/components/society/card/BuildingCardOverlay")
  .then((module) => ({ default: module.BuildingCardOverlay }));


function isProtectedMarsInteraction(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest("[data-mars-ui], [data-mars-mode=\'player\'], [data-mars-mode=\'follow\']"));
}

export function SocietyView() {
  const queryClient = useQueryClient();
  useModelMenuData();
  const t = useT();
  useLocaleChunk("society");
  const [mode, setMode] = useState<"agents" | "world">("agents");
  const [worldVisited, setWorldVisited] = useState(false);
  const roster = useSocietyRoster();
  const agents = useMemo(() => roster.data?.agents ?? [], [roster.data]);
  const sample = roster.data?.sample ?? true;
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
  const [openPlace, setOpenPlace] = useState<BuildingPlace | null>(null);

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

  const [fullscreenError, setFullscreenError] = useState(false);
  const switchMode = useCallback((next: "agents" | "world") => {
    if (next === "world") setWorldVisited(true);
    setMode(next);
    setFullscreenError(false);
    if (inDesktopShell()) void setMapFullscreen(next === "world").catch(() => setFullscreenError(true));
  }, []);

  // The plus opens the "new agent" dialog (name, runtime, companion); the new
  // agent's chat opens after it. Closing the dialog is not an error.
  const createAgent = useCallback(() => {
    if (creating) return;
    setCreating(true);
    setCreateError("");
    void quickCreate()
      .then((agent) => {
        selectAgent(agent.agentId);
        switchMode("agents");
      })
      .catch((error) => {
        if (!isCreateCancelled(error)) setCreateError(error instanceof Error ? error.message : String(error));
      })
      .finally(() => setCreating(false));
  }, [creating, quickCreate, selectAgent, switchMode]);

  useEffect(() => {
    // A reload starts in Agents; restore a native window left fullscreen by it.
    if (inDesktopShell()) void setMapFullscreen(false).catch(() => setFullscreenError(true));
    return () => {
      void setMapFullscreen(false).catch((error) => console.warn("Fullscreen exit failed", error));
    };
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented && !isProtectedMarsInteraction(event.target) && mode === "world" && !openPlace) switchMode("agents");
    };
    const onFullscreen = () => {
      if (!document.fullscreenElement && !inDesktopShell() && !isProtectedMarsInteraction(document.activeElement)) setMode("agents");
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("fullscreenchange", onFullscreen);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("fullscreenchange", onFullscreen);
    };
  }, [mode, switchMode, openPlace]);

  // "Needs you": tell the notifier which agent is on screen, and honour a
  // request to open an agent at one of its cards (agentNavigation.openAgent).
  const onScreenId = mode === "agents" && !openGroup ? openAgent?.agentId ?? null : null;
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
    switchMode("agents");
    selectAgent(taken.agentId);
    // The lead's card is the front-page chat, which holds many sessions.
    if (target.tier === "lead" && taken.sessionId && !taken.sessionId.startsWith("society:")) {
      const chat = useAgentChatStore.getState();
      if (chat.activeSessionId !== taken.sessionId) chat.openSession(taken.sessionId);
    }
    void revealCard({ cardRef: taken.cardRef, kind: taken.kind });
  }, [navigation, agents, roster.isLoading, selectAgent, switchMode]);

  const onIslandSelect = useCallback((agentId: string | null) => {
    if (agentId) {
      selectAgent(agentId);
      switchMode("agents");
    }
  }, [selectAgent, switchMode]);

  // A building clicked on the island opens its own card: the building
  // rendered as it stands on the map, and beside it what it does.
  const onIslandPlace = useCallback((place: PlaceId) => {
    if (isBuildingPlace(place)) setOpenPlace(place);
  }, []);

  // Labelled, in the caption look the Agentic IDE's switch uses: a word
  // names each face, so the switch reads without hovering.
  const modeSwitch = (
    <div role="tablist" aria-label={t("society.world.mode_label")} className={CAPTION_TRACK}>
      {MODES.map(({ value, labelKey, titleKey, Icon }) => {
        const on = mode === value;
        return <button key={value} type="button" role="tab" aria-selected={on}
          title={t(titleKey)} data-testid={`society-mode-${value}`}
          onClick={() => switchMode(value)}
          onPointerEnter={value === "world" ? preloadWorld : undefined}
          onFocus={value === "world" ? preloadWorld : undefined}
          className={cn(MODE_SEGMENT, on ? cn(CAPTION_SEGMENT_ON, MODE_SEGMENT_ON) : cn(CAPTION_SEGMENT_OFF, "border-transparent"))}>
          <Icon aria-hidden className="h-3.5 w-3.5" strokeWidth={CAPTION_ICON_STROKE} />
          <span>{t(labelKey)}</span>
        </button>;
      })}
    </div>
  );

  return (
    <div className={mode === "world" ? "fixed inset-x-0 bottom-0 top-8 z-30 flex flex-col bg-background" : "relative flex h-full min-h-0 w-full flex-col"} data-testid="society-view" data-tour="agents-page">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        {/* Map mode takes the native window fullscreen, so the switch cannot
            live inside the map HUD: it would shrink into the corner and strand
            the user on the island. It rides in the window caption in BOTH
            modes — one switch, always centered, always a way back. */}
        {createPortal(
          <div className="pointer-events-none fixed inset-x-0 top-0 z-[140] flex h-8 items-center justify-center" data-testid="mode-switch">
            <div className="pointer-events-auto flex items-center gap-2">{modeSwitch}<BrowserProfilesButton iconOnly /><AttentionBell /></div>
          </div>,
          document.body,
        )}
        {fullscreenError && <p role="alert" className="bg-card px-4 py-2 text-sm text-destructive">{t("society.world.fullscreen_failed")}</p>}
        {groupError && <p role="alert" className="bg-card px-4 py-2 text-sm text-destructive">{groupError}</p>}
        {createError && <p role="alert" className="bg-card px-4 py-2 text-sm text-destructive">{createError}</p>}
        {worldVisited ? (
        <div className={mode === "world" ? "relative flex min-h-0 flex-1" : "hidden"} data-testid="society-world-surface" aria-hidden={mode !== "world"}>
          <div className="min-w-0 flex-1">
            <CanvasActivity.Provider value={mode === "world" && !openPlace}>
              <Suspense fallback={<div className="relative h-full"><VerseLoadingScreen /></div>}>
                <JarvisAgentsBoard onSelectAgent={onIslandSelect} onSelectPlace={onIslandPlace} onOpenAgents={() => switchMode("agents")}
                  active={mode === "world"}
                  onCreateAgent={createAgent} onOpenGroup={(groupId) => { selectGroup(groupId); switchMode("agents"); }} />
              </Suspense>
            </CanvasActivity.Provider>
          </div>

        </div>
        ) : null}
        <div className={mode === "agents" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
        {openGroup ? (
          <ChatGroupPanel group={openGroup} groups={groups} roster={agents} onOpenAgent={selectAgent} onOpenGroup={selectGroup}
            onCreateAgent={createAgent} onDeleted={() => setOpenGroupId(null)}
            onGroupAgents={groupAgents} onAddAgentToGroup={addAgentToGroup} />
        ) : openAgent ? (
          <AgentCardOverlay embedded active={mode === "agents"} agent={openAgent} roster={agents} rosterLoading={roster.isLoading} teamsPending={teamsPending}
            groups={groups} onSelectGroup={selectGroup}
            onGroupAgents={sample ? undefined : groupAgents} onAddAgentToGroup={sample ? undefined : addAgentToGroup}
            sample={sample} onSelectAgent={selectAgent} onCreate={createAgent}
            onClose={() => setOpenAgentId(null)} />
        ) : (
          <RosterRail agents={agents} loading={roster.isLoading} teamsPending={teamsPending} sample={sample}
            groups={groups} onOpenGroup={selectGroup}
            onGroupAgents={sample ? undefined : groupAgents} onAddAgentToGroup={sample ? undefined : addAgentToGroup}
            activeAgentId={null} onOpen={selectAgent} onCreate={createAgent} side="left"
            activity={standaloneActivity} keyboard={mode === "agents"}
            className="w-full border-0" />
        )}
        </div>
      </div>
      {openPlace && <DeferredSocietyDialog
        load={loadBuildingDialog}
        title={t(`society.world.${BUILDING_CARDS[openPlace].nameKey}`)}
        onClose={() => setOpenPlace(null)}
        dialogProps={{
          place: openPlace,
          onClose: () => setOpenPlace(null),
          onCreateAgent: () => {
            setOpenPlace(null);
            createAgent();
          },
        }}
      />}
    </div>
  );
}

export default SocietyView;
