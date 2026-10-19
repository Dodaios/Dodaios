/**
 * Agents > Dodaios Verse: the starship. The captain (the person) walks the
 * decks; the agents are the crew, androids at their consoles who live their
 * day by their real run state. Stations turn the ship's places into the
 * app's actions: the transporter beams in a new agent, a division's
 * holo-table opens its team, the turbolift rides to another deck.
 */
import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Canvas, useFrame, type ThreeEvent } from "@react-three/fiber";
import { useQueryClient } from "@tanstack/react-query";
import { useReducedMotion } from "framer-motion";
import { ArrowUpDown, Crosshair, Map as MapIcon, CircleHelp } from "lucide-react";
import { CanvasActivity, useCanvasAwake } from "@/hooks/useCanvasAwake";
import { useWebglSurface } from "@/hooks/useWebglSurface";
import { useWebglSupported } from "@/lib/graphDimension";
import { useLocaleChunk, useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { chatGroupsKnown, useSocietyChatGroups } from "@/lib/societyChatGroups";
import { useQuickCreateAgent, useSocietyRoster, type SocietyAgent } from "../data";
import { isCreateCancelled } from "../create/createAgentStore";
import { resolveCompanion } from "../companion/appearance";
import { useSyncCompanionPet } from "../companion/companionPetStore";
import { AgentSwatch } from "../AgentSwatch";
import { creatureFromShape } from "../companion/creature";
import { growsCreature, useCreatureDefault } from "../companion/creatureDefault";
import { useDeskChats } from "../crewFeeds/useDeskChats";
import { useTeamRounds } from "../crewFeeds/useTeamRounds";
import { useTeamwork } from "../crewFeeds/teamwork";
import { useProgression } from "../progression/progressionStore";
import { useProgressionSync } from "../progression/useProgressionSync";
import { suitFor } from "../progression/cosmetics";
import { ServiceRecord } from "./levels/ServiceRecord";
import { PromotionLayer } from "./levels/PromotionCeremony";
import { reportWorldAction } from "../progression/progressionApi";
import type { WorldAction } from "../progression/levelCatalog";
import { useCodingFloorOccupants } from "../crewFeeds/codingFloor";
import { openPaneSession } from "../crewFeeds/codingNavigate";
import { deckModule, type ShipActions } from "./decks/registry";
import "./decks";
import { buildNavGrid, nearestFree } from "./nav/shipNav";
import type { CrewInput, DeckId, DeckPlan, Prop, Station, TeamInput } from "./plan/types";
import { DECKS, deckNumber } from "./plan/types";
import { captain, useShip } from "./shipStore";
import { CameraRig, CAMERA_FOV, orbit } from "./render/CameraRig";
import { DeckLights, PostFx, RendererSetup, type Quality } from "./render/ShipRenderer";
import { ConsoleScreens, HoloTables, RoomSigns, SlidingDoors, StaticDeck, StationHalo, StationTargets, TransporterBeam } from "./render/deck/DeckScene";
import type { ScreenContent } from "./render/deck/screens";
import { SpaceBackdrop } from "./space/SpaceBackdrop";
import { destinationById } from "./space/destinations";
import { CrewLayer, crewPoses, type CrewView } from "./life/CrewLayer";
import { CaptainFigure, typesText, walkCaptainTo } from "./life/Captain";
import { ShipPet } from "./life/ShipPet";
import type { RoundView } from "./life/crewLife";
import { FaceAtlas, type FaceLook } from "./crew/faceAtlas";
import { faceMaterial } from "./crew/figure";
import { PlateDriver, PlateLayer } from "./hud/Plates";
import { rankFor } from "./levels/ranks";
import "./hud/ship.css";

export interface ShipStageProps {
  onOpenLedger?: () => void;
  onSelectAgent?: (id: string | null) => void;
  onCreateAgent?: () => void;
  onOpenGroup?: (groupId: string) => void;
  /** The deck to show on mount (the IDE tab opens on engineering). */
  initialDeck?: DeckId;
  compact?: boolean;
  /** A visited map keeps its renderer while its host shows something else. */
  active?: boolean;
}

class RenderBoundary extends Component<{ children: ReactNode; fallback: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.warn("Ship renderer unavailable", error); }
  render() { return this.state.failed ? <div className="ship-fallback" role="status">{this.props.fallback}</div> : this.props.children; }
}

// Dev-only handles for runtime checks: the captain, the store, the camera orbit and the crew's poses.
if (import.meta.env.DEV && typeof window !== "undefined") Object.assign(window, { __ship: { captain, useShip, orbit, crewPoses } });

const REFRESH_MS = 5000;

function useRosterRefresh(awake: boolean) {
  const client = useQueryClient();
  useEffect(() => {
    if (!awake) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => { void client.invalidateQueries({ queryKey: ["society", "roster"] }); schedule(); }, REFRESH_MS + Math.random() * 1500);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [awake, client]);
}

export function faceLookOf(agent: Pick<SocietyAgent, "agentId" | "figure">, creaturesByDefault: boolean): FaceLook {
  const look = resolveCompanion(agent.agentId, agent.figure?.companion);
  const creature = look.creature ?? (growsCreature(look, creaturesByDefault) ? creatureFromShape(look) : undefined);
  return creature ? { kind: "creature", creature } : { kind: "shape", shape: look.shape, color: look.color };
}

/** How long a newcomer counts as one (it walks from the transporter, the pad glows). */
const NEWCOMER_MS = 12_000;

/**
 * Crew that joined while the ship was open, per deck: they beam in at the
 * transporter and walk to their place. The first crew a deck shows is simply
 * aboard, so riding to a deck never makes its whole crew arrive.
 */
function useNewcomers(deck: DeckId, ids: readonly string[], ready: boolean): ReadonlySet<string> {
  const known = useRef(new Map<DeckId, Set<string>>());
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [fresh, setFresh] = useState<{ deck: DeckId; ids: ReadonlySet<string> }>({ deck, ids: new Set() });
  useEffect(() => {
    if (!ready) return;
    const seen = known.current.get(deck);
    if (!seen) { known.current.set(deck, new Set(ids)); return; }
    const added = ids.filter((id) => !seen.has(id));
    for (const id of ids) seen.add(id);
    if (added.length === 0) return;
    setFresh((prev) => ({ deck, ids: new Set([...(prev.deck === deck ? prev.ids : []), ...added]) }));
    // Not cleared by the next change of `ids` (the roster refreshes every few seconds): only by unmounting.
    timers.current.push(setTimeout(() => setFresh((prev) => (prev.deck === deck ? { deck, ids: new Set([...prev.ids].filter((id) => !added.includes(id))) } : prev)), NEWCOMER_MS));
  }, [deck, ids, ready]);
  useEffect(() => () => { for (const t of timers.current) clearTimeout(t); }, []);
  return fresh.deck === deck ? fresh.ids : EMPTY_SET;
}
const EMPTY_SET: ReadonlySet<string> = new Set();

export function ShipStage({ onOpenLedger, onSelectAgent, onCreateAgent, onOpenGroup, initialDeck, compact = false, active: onScreen = true }: ShipStageProps) {
  const t = useT();
  const chunkReady = useLocaleChunk("ship");
  const hostRef = useRef<HTMLDivElement>(null);
  const visible = useCanvasAwake(hostRef);
  const awake = onScreen && visible;
  const reduced = useReducedMotion() ?? false;
  const { generation } = useWebglSurface(hostRef);
  const webgl = useWebglSupported();
  const [quality] = useState<Quality>(() => (typeof navigator !== "undefined" && (navigator.hardwareConcurrency ?? 8) < 4 ? "low" : "high"));

  // The deck store is shared by every mounted stage (the Agents view and the IDE tab): each host remembers
  // its own deck and takes it back when it comes on screen; the IDE tab always opens on engineering.
  const hostDeck = useRef<DeckId | null>(initialDeck ?? null);
  useEffect(() => {
    if (!awake) return;
    const want = initialDeck ?? hostDeck.current;
    if (want && useShip.getState().deck !== want) useShip.getState().setDeck(want);
    // On waking only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [awake]);
  const deck = useShip((s) => s.deck);
  useEffect(() => { if (awake && !initialDeck) hostDeck.current = deck; }, [awake, deck, initialDeck]);
  const module = deckModule(deck) ?? deckModule("ops");
  const population = module?.population ?? "agents";

  const roster = useSocietyRoster(awake);
  // The captain's companion is the pet chosen in My Pets.
  useSyncCompanionPet();
  const coding = useCodingFloorOccupants(awake && population === "panes");
  const panes = coding.occupants;
  useRosterRefresh(awake && population === "agents");
  const groups = useSocietyChatGroups(awake && population === "agents");
  const teamsKnown = chatGroupsKnown(groups);
  const jarvisAgents = useMemo(() => (roster.data?.agents ?? []).filter((a) => a.lifecycle !== "archived"), [roster.data]);
  // Engineering's crew are the coding panes, each projected into a crew member.
  const agents = useMemo(() => (population === "panes" ? panes.map((o) => o.agent) : jarvisAgents), [population, panes, jarvisAgents]);
  const byId = useMemo(() => new Map(agents.map((a) => [a.agentId, a])), [agents]);
  const teams = useMemo<TeamInput[]>(() => (groups.data ?? []).map((g) => ({
    id: g.group_id, name: g.name, members: g.members, createdMs: g.created_ms, leadId: g.lead_agent_id ?? null,
  })), [groups.data]);
  const crewInputs = useMemo<CrewInput[]>(() => (population === "panes" || (population === "agents" && teamsKnown) ? agents : []).map((a) => ({
    agentId: a.agentId, name: a.name, tier: a.tier, state: a.state, createdMs: a.createdMs,
  })), [agents, population, teamsKnown]);
  const ready = population === "none" || (population === "panes" ? coding.loaded : !!roster.data && teamsKnown);

  // The plan depends on who belongs where, never on run state.
  const teamsKey = teams.map((tm) => `${tm.id}|${tm.name}|${tm.createdMs}|${tm.leadId ?? ""}|${tm.members.join("+")}`).join(",");
  const paneKey = population === "panes" ? panes.map((o) => `${o.agent.agentId}|${o.pane.workspace_id}`).join(",") : "";
  const seatingKey = `${paneKey}${deck}:${crewInputs.map((c) => `${c.agentId}|${c.tier}|${c.createdMs}`).join(",")}#${teamsKey}`;
  const plan = useMemo<DeckPlan | null>(() => {
    if (!module) return null;
    try { return module.build({ crew: crewInputs, teams, panes }); }
    catch (error) { console.warn("Deck plan failed", error); return null; }
  },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [seatingKey]);
  const grid = useMemo(() => (plan ? buildNavGrid(plan) : null), [plan]);

  // Levels.
  useProgressionSync(awake, deck);
  const record = useProgression((s) => s.record);
  const suitChoice = useProgression((s) => s.suit);
  const rewards = useProgression((s) => s.snapshot?.rewards);
  const subjects = useProgression((s) => s.subjects);
  const levelOf = useCallback((agentId: string) => subjects[`agent:${agentId}`]?.level ?? 1, [subjects]);
  const captainLevel = subjects.person?.level ?? 1;

  // Faces.
  const creaturesByDefault = useCreatureDefault((s) => s.enabled);
  const atlas = useMemo(() => new FaceAtlas(), []);
  const faceMat = useMemo(() => faceMaterial(atlas.texture), [atlas]);
  useEffect(() => () => { faceMat.dispose(); atlas.texture.dispose(); }, [atlas, faceMat]);

  const divisionOf = useMemo(() => {
    const m = new Map<string, DeckPlan["divisions"][number]>();
    for (const d of plan?.divisions ?? []) for (const id of d.members) m.set(id, d);
    return m;
  }, [plan]);
  const crew = useMemo<CrewView[]>(() => crewInputs.filter((c) => plan?.seatOf.has(c.agentId) || plan?.unseated.includes(c.agentId)).map((c) => {
    const agent = byId.get(c.agentId);
    const d = divisionOf.get(c.agentId);
    const rank = rankFor(levelOf(c.agentId));
    return {
      agentId: c.agentId, name: c.name, state: c.state, division: d?.room ?? null,
      face: agent ? faceLookOf(agent, creaturesByDefault) : { kind: "shape", shape: "circle", color: "#5fd4ff" },
      accent: d?.colour ?? "#8aa4c8", pips: rank.pips, gold: rank.gold, lead: !!d && d.leadId === c.agentId,
      ribbons: (rewards ?? []).filter((r) => r.slot === "decoration" && r.levels.agent !== null && levelOf(c.agentId) >= (r.levels.agent ?? 99)).length,
    };
  }), [crewInputs, plan, byId, divisionOf, levelOf, creaturesByDefault, rewards]);
  const newcomers = useNewcomers(deck, useMemo(() => crew.map((c) => c.agentId), [crew]), ready && population !== "none" && !!plan);

  // Team rounds feed the holo-tables and the gatherings.
  const watchTeams = useMemo(() => (plan?.divisions ?? []).map((d) => ({ teamId: d.teamId, members: d.members })) as never, [plan]);
  useTeamRounds(watchTeams, byId, awake && population === "agents");
  const rawRounds = useTeamwork((s) => s.rounds);
  const rounds = useMemo(() => {
    const m = new Map<string, RoundView>();
    for (const d of plan?.divisions ?? []) {
      const r = d.teamId ? rawRounds[d.teamId] : undefined;
      if (r?.running) m.set(d.room, { running: true, speakerId: r.speakerId });
    }
    return m;
  }, [plan, rawRounds]);

  // Console screens: the tail of each agent's chat.
  const sessions = useMemo(() => new Map(agents.filter((a) => a.chatSessionId).map((a) => [a.agentId, a.chatSessionId as string])), [agents]);
  const chats = useDeskChats(sessions, awake && population === "agents");

  const gathering = useShip((s) => s.gathering);
  const called = useMemo(() => (gathering && gathering.untilMs > Date.now() ? { place: gathering.place, agentIds: gathering.agentIds } : null), [gathering]);
  useEffect(() => {
    if (!gathering) return;
    const timer = setTimeout(() => useShip.getState().gather(null), Math.max(0, gathering.untilMs - Date.now()));
    return () => clearTimeout(timer);
  }, [gathering]);

  const chosenLook = useShip((st) => st.captainLook);
  // The cut of the suit is the level system's: the finest open one, or the one the captain chose.
  const look = useMemo(() => ({ ...chosenLook, cut: suitFor(rewards ?? [], captainLevel, suitChoice)?.replace(/^suit_/, "") ?? null }),
    [chosenLook, rewards, captainLevel, suitChoice]);
  const destinationId = useShip((s) => s.destination);
  const destination = useMemo(() => destinationById(destinationId), [destinationId]);

  // Interaction.
  const selection = useShip((s) => s.selection);
  const following = useShip((s) => s.follow);
  const nearby = useShip((s) => s.nearby);
  const hovered = useShip((s) => s.hovered);
  const [lift, setLift] = useState(false);
  const [doors, setDoors] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => () => { for (const timer of timers.current) clearTimeout(timer); }, []);
  const later = useCallback((fn: () => void, ms: number) => { timers.current.push(setTimeout(fn, ms)); }, []);
  const say = useCallback((text: string) => {
    setNotice(text);
    later(() => setNotice((n) => (n === text ? null : n)), 4200);
  }, [later]);
  const quickCreate = useQuickCreateAgent();
  const creating = useRef(false);
  const createAgent = useCallback(() => {
    if (onCreateAgent) { onCreateAgent(); return; }
    if (creating.current) return;
    creating.current = true;
    void quickCreate().catch((e) => { if (!isCreateCancelled(e)) console.warn("Agent creation failed", e); }).finally(() => { creating.current = false; });
  }, [onCreateAgent, quickCreate]);
  const openAgent = useCallback((id: string) => {
    const pane = panes.find((o) => o.agent.agentId === id);
    if (pane) { openPaneSession(pane.pane); return; }
    if (onSelectAgent) onSelectAgent(id);
    else useEventStore.getState().setActiveSection("agents");
  }, [onSelectAgent, panes]);

  const [panel, setPanel] = useState<string | null>(null);
  useEffect(() => setPanel(null), [deck]);
  const rideRef = useRef<(to: DeckId) => void>(() => undefined);
  const actions = useMemo<ShipActions>(() => ({
    t, say, openAgent, createAgent,
    openLedger: () => { if (onOpenLedger) onOpenLedger(); else useEventStore.getState().setActiveSection("agents"); },
    openGroup: (id) => { if (onOpenGroup) onOpenGroup(id); else useEventStore.getState().setActiveSection("agents"); },
    openSection: (section) => useEventStore.getState().setActiveSection(section as never),
    ride: (to) => rideRef.current(to),
    sit: (seat) => { captain.seated = seat; if (seat) captain.path = []; },
    openPanel: (id) => setPanel(id),
    closePanel: () => setPanel(null),
    reportAction: (action, ref = "") => { void reportWorldAction(action as WorldAction, ref); },
  }), [t, say, openAgent, createAgent, onOpenLedger, onOpenGroup]);

  const activateStation = useCallback((station: Station) => {
    if (!plan) return;
    const far = Math.hypot(captain.x - station.x, captain.z - station.z) > station.radius + 0.6;
    if (module?.useStation?.(station, plan, actions, far)) return;
    switch (station.kind) {
      case "transporter": createAgent(); return;
      case "lift":
        if (far) { useShip.getState().requestWalk({ x: station.x, z: station.z }); return; }
        setLift(true); return;
      case "division": {
        const division = plan.divisions.find((d) => `division:${d.room}` === station.id);
        if (division?.teamId && onOpenGroup) onOpenGroup(division.teamId);
        else if (onOpenLedger) onOpenLedger();
        return;
      }
      case "newDivision": if (onOpenLedger) onOpenLedger(); else useEventStore.getState().setActiveSection("agents"); return;
      case "mess": {
        const free = crew.filter((c) => c.state === "idle").map((c) => c.agentId);
        const store = useShip.getState();
        if (store.gathering?.place === "mess") { store.gather(null); say(t("ship.station.mess.ended")); return; }
        if (free.length === 0) { say(t("ship.station.mess.nobody")); return; }
        store.gather({ place: "mess", agentIds: free, untilMs: Date.now() + 90_000 });
        say(t("ship.station.mess.called").replace("{count}", String(free.length)));
        return;
      }
      case "rankWall": useProgression.getState().openRecord("ranks"); return;
      case "honorCase": useProgression.getState().openRecord("rewards"); return;
      default: return;
    }
  }, [plan, module, actions, createAgent, onOpenGroup, onOpenLedger, crew, say, t]);

  // E uses the station the captain stands at; O overview, F follow, Escape closes.
  useEffect(() => {
    if (!awake) return;
    const key = (e: KeyboardEvent) => {
      if (typesText(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      const host = hostRef.current;
      const activeEl = document.activeElement;
      if (activeEl && activeEl !== document.body && !host?.contains(activeEl)) return;
      if (e.code === "KeyE" && plan) {
        const s = plan.stations.find((st) => st.id === useShip.getState().nearby);
        if (s) { e.preventDefault(); activateStation(s); }
      } else if (e.code === "KeyO") useShip.getState().overview();
      else if (e.code === "KeyF") useShip.getState().setFollow(true);
      else if (e.code === "Escape") { setLift(false); setPanel(null); useShip.getState().select(null); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [awake, plan, activateStation]);

  const rideTo = useCallback((to: DeckId) => {
    setLift(false);
    if (to === deck) return;
    if (reduced) { useShip.getState().setDeck(to); return; }
    setDoors(true);
    later(() => {
      useShip.getState().setDeck(to);
      later(() => setDoors(false), 650);
    }, 600);
  }, [deck, reduced, later]);
  rideRef.current = rideTo;

  const counts = useMemo(() => {
    const c = { working: 0, waiting: 0, idle: 0, paused: 0 };
    for (const m of crew) c[m.state] += 1;
    return c;
  }, [crew]);

  const stationText = useCallback((s: Station) => ({
    action: t(`ship.station.${s.kind}.action`),
    name: module?.stationName?.(s, t)
      ?? (s.kind === "division" ? (plan?.divisions.find((d) => `division:${d.room}` === s.id)?.name || t("ship.division.pool")) : t(`ship.station.${s.kind}.name`)),
  }), [t, plan, module]);
  const promptStation = plan?.stations.find((s) => s.id === (hovered?.kind === "station" ? hovered.id : nearby));
  const selectedAgent = selection?.kind === "agent" ? crew.find((c) => c.agentId === selection.id) : undefined;

  const screenContent = useCallback((p: Prop): ScreenContent => {
    const owner = p.ref ? byId.get(p.ref) : undefined;
    if (!owner) return { title: t("ship.screen.vacant"), state: "vacant", accent: p.accent ?? "#5fd4ff", stateLabel: t("ship.screen.vacant"), standby: t("ship.screen.vacant") };
    const lines = chats.get(owner.agentId)?.lines;
    return {
      title: owner.name, state: owner.state, accent: p.accent ?? "#5fd4ff", lines: owner.state === "idle" && !lines?.length ? undefined : lines,
      stateLabel: t(`ship.state.${owner.state}`), standby: t("ship.screen.standby"),
    };
  }, [byId, chats, t]);
  const divisionLabel = useCallback((d: DeckPlan["divisions"][number]) => (d.teamId ? d.name : t("ship.division.pool")), [t]);
  const roomText = useCallback((room: DeckPlan["rooms"][number]) => !room.sign ? null : "text" in room.sign ? room.sign.text : t(room.sign.key), [t]);
  const memberState = useCallback((id: string) => byId.get(id)?.state ?? "idle", [byId]);
  const bodies = useCallback(function* () {
    yield { x: captain.x, z: captain.z };
    for (const p of crewPoses.values()) if (p.moving) yield p;
  }, []);

  const floorClick = useCallback((e: ThreeEvent<MouseEvent>) => {
    if (!grid || e.button !== 0) return;
    e.stopPropagation();
    useShip.getState().select(null);
    walkCaptainTo(grid, { x: e.point.x, z: e.point.z });
  }, [grid]);

  const plates = useMemo(() => crew.map((c) => ({
    agentId: c.agentId, name: c.name, state: c.state,
    rank: t(`ship.rank.${rankFor(levelOf(c.agentId)).id}`),
  })), [crew, t, levelOf]);

  const captainRank = rankFor(captainLevel);
  const person = subjects.person;
  const xpShare = person && person.xpForNext > 0 ? Math.min(1, person.xpIntoLevel / person.xpForNext) : 0;

  const fallback = t("ship.fallback");
  return (
    <div ref={hostRef} className="ship-stage" data-compact={compact} tabIndex={-1} aria-label={t("ship.title")}>
      {!webgl ? <div className="ship-fallback">{fallback}</div> : (
        <RenderBoundary fallback={fallback}>
          <CanvasActivity.Provider value={awake}>
            <Canvas key={generation} frameloop={awake ? "always" : "never"} shadows dpr={[1, 1.75]}
              gl={{ antialias: false, powerPreference: "high-performance", stencil: false }}
              camera={{ fov: CAMERA_FOV, near: 0.1, far: 9000, position: [0, 20, 20] }}
              onPointerMissed={() => useShip.getState().select(null)}>
              <RendererSetup quality={quality} />
              <SpaceBackdrop destination={destination} reduced={reduced} />
              {plan && grid && (
                <>
                  <DeckLights plan={plan} quality={quality} sunDirection={destination.sun.direction} />
                  <StaticDeck plan={plan} />
                  <mesh rotation={[-Math.PI / 2, 0, 0]} position={[(plan.bounds.x0 + plan.bounds.x1) / 2, 0.02, (plan.bounds.z0 + plan.bounds.z1) / 2]} onClick={floorClick}>
                    <planeGeometry args={[plan.bounds.x1 - plan.bounds.x0, plan.bounds.z1 - plan.bounds.z0]} />
                    <meshBasicMaterial visible={false} />
                  </mesh>
                  {population === "agents" && <ConsoleScreens plan={plan} content={screenContent} onScreen={(p) => p.ref && openAgent(p.ref)} />}
                  <HoloTables plan={plan} label={divisionLabel} memberState={memberState} reduced={reduced} />
                  <RoomSigns plan={plan} text={roomText} />
                  <SlidingDoors plan={plan} bodies={bodies} />
                  {plan.props.some((p) => p.kind === "transporter") && <TransporterBeam at={plan.arrival} active={newcomers.size > 0} reduced={reduced} />}
                  <StationTargets plan={plan} onStation={activateStation} onHover={(s) => useShip.getState().hover(s ? { kind: "station", id: s.id } : null)} />
                  <StationHalo plan={plan} id={promptStation?.id ?? null} />
                  {module?.Scene && <module.Scene plan={plan} reduced={reduced} quality={quality} awake={awake} agents={byId} panes={panes} actions={actions} />}
                  <CrewLayer plan={plan} grid={grid} crew={crew} rounds={rounds} called={called} atlas={atlas} faceMaterial={faceMat}
                    reduced={reduced} newcomers={newcomers}
                    onPick={(id) => useShip.getState().select({ kind: "agent", id })}
                    onHover={(id) => useShip.getState().hover(id ? { kind: "agent", id } : null)} />
                  <CaptainFigure plan={plan} grid={grid} look={look} pips={captainRank.pips} awake={awake} reduced={reduced} keyHost={hostRef} />
                  <ShipPet grid={grid} reduced={reduced} onWalked={() => actions.reportAction("walk_together")} />
                  <StationProximity plan={plan} />
                  <CameraRig plan={plan} compact={compact} />
                  <PlateDriver />
                </>
              )}
              <PostFx quality={quality} />
            </Canvas>
          </CanvasActivity.Provider>
        </RenderBoundary>
      )}
      {chunkReady && plan && (
        <>
          <PlateLayer plates={plates} onPick={(id) => useShip.getState().select({ kind: "agent", id })} />
          <div className="ship-hud">
            <section className="ship-panel ship-deck" aria-live="polite">
              <div className="ship-deck-number">{deckNumber(deck)}</div>
              <div className="ship-eyebrow">{t("ship.deck.label").replace("{n}", String(deckNumber(deck)))}</div>
              <div className="ship-deck-name">{t(`ship.deck.${deck}`)}</div>
              {population !== "none" && (
                <div className="ship-crewline">
                  <span><i className="ship-dot" data-state="working" />{t("ship.crew.working").replace("{count}", String(counts.working))}</span>
                  <span><i className="ship-dot" data-state="waiting" />{t("ship.crew.waiting").replace("{count}", String(counts.waiting))}</span>
                  <span><i className="ship-dot" data-state="idle" />{t("ship.crew.idle").replace("{count}", String(counts.idle + counts.paused))}</span>
                </div>
              )}
            </section>
            {!compact && (
              <button type="button" className="ship-panel ship-rank" onClick={() => useProgression.getState().openRecord("record")}>
                <RankBadge pips={captainRank.pips} gold={captainRank.gold} />
                <span>
                  <span className="ship-rank-title">{t(`ship.rank.${captainRank.id}`)}</span>
                  <span className="ship-rank-sub"> · {t("ship.level").replace("{n}", String(captainLevel))}</span>
                </span>
                <span className="ship-xp"><i style={{ width: `${Math.round(xpShare * 100)}%` }} /></span>
              </button>
            )}
            <nav className="ship-panel ship-tools" aria-label={t("ship.tools.label")}>
              <button type="button" className="ship-tool" aria-pressed={following} title={t("ship.tools.follow")} aria-label={t("ship.tools.follow")} onClick={() => useShip.getState().setFollow(true)}><Crosshair size={17} /></button>
              <button type="button" className="ship-tool" title={t("ship.tools.overview")} aria-label={t("ship.tools.overview")} onClick={() => useShip.getState().overview()}><MapIcon size={17} /></button>
              <button type="button" className="ship-tool" title={t("ship.tools.lift")} aria-label={t("ship.tools.lift")} onClick={() => setLift(true)}><ArrowUpDown size={17} /></button>
              <button type="button" className="ship-tool" title={t("ship.tools.help")} aria-label={t("ship.tools.help")} onClick={() => say(t("ship.help"))}><CircleHelp size={17} /></button>
            </nav>
            {promptStation && !lift && !panel && (
              <button type="button" className="ship-panel ship-prompt" onClick={() => activateStation(promptStation)}>
                <span className="ship-key">{hovered?.kind === "station" && hovered.id === promptStation.id && nearby !== promptStation.id ? t("ship.click") : "E"}</span>
                <span>{stationText(promptStation).action}</span>
                <small>{stationText(promptStation).name}</small>
              </button>
            )}
            {notice && <div className="ship-panel ship-notice" role="status">{notice}</div>}
            {selectedAgent && (
              <section className="ship-panel ship-agent" aria-label={selectedAgent.name}>
                <button type="button" className="ship-tool ship-close" aria-label={t("ship.close")} onClick={() => useShip.getState().select(null)}>✕</button>
                <div className="ship-agent-head">
                  <span className="ship-agent-face" style={{ borderColor: selectedAgent.accent }}>
                    {byId.get(selectedAgent.agentId) && <AgentSwatch agent={{ ...(byId.get(selectedAgent.agentId) as SocietyAgent), state: undefined }} size={38} />}
                  </span>
                  <div>
                    <div className="ship-agent-name">{selectedAgent.name}</div>
                    <div className="ship-agent-meta">
                      <i className="ship-dot" data-state={selectedAgent.state} />
                      {t(`ship.state.${selectedAgent.state}`)}
                      <span>·</span>
                      {t(`ship.rank.${rankFor(levelOf(selectedAgent.agentId)).id}`)}
                    </div>
                    <div className="ship-agent-meta">{plan.divisions.find((d) => d.room === selectedAgent.division)?.name || t("ship.division.pool")}</div>
                  </div>
                </div>
                <div className="ship-agent-actions">
                  <button type="button" className="ship-btn" data-primary="true" onClick={() => openAgent(selectedAgent.agentId)}>{t("ship.agent.open_chat")}</button>
                  <button type="button" className="ship-btn" onClick={() => {
                    const p = crewPoses.get(selectedAgent.agentId);
                    if (p && grid) { const at = nearestFree(grid, { x: p.x + 0.9, z: p.z + 0.4 }); if (at) useShip.getState().requestWalk(at); }
                  }}>{t("ship.agent.walk_there")}</button>
                  <button type="button" className="ship-btn" onClick={() => {
                    const p = crewPoses.get(selectedAgent.agentId);
                    if (p) useShip.getState().focusOn({ x: p.x, z: p.z });
                  }}>{t("ship.agent.show")}</button>
                </div>
              </section>
            )}
          </div>
          {lift && (
            <div className="ship-scrim" onClick={() => setLift(false)}>
              <section className="ship-panel ship-lift" role="dialog" aria-modal="true" aria-label={t("ship.lift.title")} onClick={(e) => e.stopPropagation()}>
                <h2>{t("ship.lift.title")}</h2>
                <div className="ship-lift-list">
                  {DECKS.filter((d) => deckModule(d)).map((d) => (
                    <button key={d} type="button" className="ship-lift-row" aria-current={d === deck} autoFocus={d === deck} onClick={() => rideTo(d)}>
                      <b>{deckNumber(d)}</b>
                      <span>{t(`ship.deck.${d}`)}<small>{t(`ship.deck.${d}_about`)}</small></span>
                      {d === deck && <small className="ship-eyebrow">{t("ship.lift.here")}</small>}
                    </button>
                  ))}
                </div>
              </section>
            </div>
          )}
          {panel && module?.Panel && plan.stations.some((s) => s.id === panel) && (
            <module.Panel plan={plan} station={plan.stations.find((s) => s.id === panel) as Station} actions={actions} agents={byId} panes={panes} />
          )}
          {awake && record && <ServiceRecord initialTab={record} onClose={() => useProgression.getState().openRecord(null)} />}
          {awake && <PromotionLayer />}
          <div className="ship-doors" data-shut={doors}><i /><i /></div>
        </>
      )}
    </div>
  );
}

/** Collar pips as a small badge: silver for enlisted ranks, gold for officers. */
export function RankBadge({ pips, gold }: { pips: number; gold: boolean }) {
  const metal = gold ? "#e1b04f" : "#c9cdd3";
  return (
    <svg width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
      <rect x="1" y="1" width="32" height="32" rx="8" fill="rgba(217,164,65,0.08)" stroke="rgba(217,164,65,0.45)" />
      <rect x="6" y="14" width="22" height="6" rx="2" fill="#1a1f27" stroke="rgba(255,255,255,0.12)" />
      {Array.from({ length: pips }, (_, i) => <circle key={i} cx={9.5 + i * 5} cy={17} r={1.9} fill={metal} />)}
    </svg>
  );
}

/** Which station the captain stands at. */
function StationProximity({ plan }: { plan: DeckPlan }) {
  useFrame(() => {
    let best: string | null = null, bd = Infinity;
    for (const s of plan.stations) {
      const d = Math.hypot(captain.x - s.x, captain.z - s.z);
      if (d < s.radius && d < bd) { bd = d; best = s.id; }
    }
    useShip.getState().setNearby(best);
  });
  return null;
}
