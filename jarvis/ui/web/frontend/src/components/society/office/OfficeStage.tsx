/**
 * Agents > Map: the office. The person walks their own character through the
 * floor (or zooms out and clicks), agents live their day according to their
 * real run state, and checkpoints turn rooms into actions: create, manage,
 * team up, dress up, talk to the lead, call a coffee break. One elevator ride
 * up is the coding floor: a figure per IDE coding session, its terminal live
 * on the monitor, and Gigi flying along with the person. The top floor is the
 * arcade: a hall of retro cabinets, every one of them playable.
 */
import { Component, lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSyncCompanionPet } from "../companion/companionPetStore";
import { useActivePet } from "@/hooks/usePets";
import { advance, Canvas } from "@react-three/fiber";
import { useReducedMotion } from "framer-motion";
import { CanvasActivity, useCanvasAwake } from "@/hooks/useCanvasAwake";
import { useWebglSurface } from "@/hooks/useWebglSurface";
import { useWebglSupported } from "@/lib/graphDimension";
import { useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useQuickCreateAgent, useSocietyRoster, type SocietyAgent } from "../data";
import { isCreateCancelled } from "../create/createAgentStore";
import { OfficeScene } from "./OfficeScene";
import { allDesks, buildOfficeLayout, countStates, seatedCount, type OfficeTeamInput } from "./officeLayout";
import { buildHallLayout } from "./hallFloorLayout";
import { useSocietyChatGroups } from "@/lib/societyChatGroups";
import { buildNavGrid } from "./officeNav";
import { SpotBook } from "./officeBehavior";
import { CAMERA_FOV } from "./officeCamera";
import { ZOOM_SECONDS } from "./OfficeCameraRig";
import { useDeskChats } from "./useDeskChats";
import type { Point } from "./officeLayout";
import { player, sameSelection, switchFloor, useOfficeStore, type OfficeFloor, type Selection } from "./officeStore";
import { agentPositions, seatedAtDesk } from "./walkerRegistry";
import { useCodingFloorOccupants, type PaneOccupant } from "./codingFloor";
import { openPaneSession } from "./codingNavigate";
import { useDprBudget } from "./useDprBudget";
import { knownOnFloor, noteArrivals } from "./officeFloors";
import { atElevator } from "./elevatorCall";
import { loadProfile, playerLook, saveProfile, type PlayerProfile } from "./playerProfile";
import { AgentPanel, StationSurface, stationSurface, type OfficeActions } from "./OfficePanels";
import { MeetingStatus } from "./TeamRoomPanel";
import { ControlHints, OfficeTools, StationPrompt, stationAction, stationLabel, type PromptLine } from "./OfficeHud";
import { CALL_MS, isReception, loungeCentre, selectionKey, spawnScreenDive, stationOf, stationsFor } from "./stations";
import { PaneCommandPanel } from "./PaneCommandPanel";
import type { WalkerContext } from "./OfficeAgents";
import { ownsKeyboard } from "./OfficePlayer";
import { ArcadeCabinet } from "./ArcadeCabinet";
import { ElevatorPanel } from "./ElevatorPanel";
import { ElevatorDoors, type DoorsPhase } from "./ElevatorDoors";
import { buildArcadeLayout } from "../arcade/arcadeFloorLayout";
import { ARCADE_GAMES, gameForCabinet, type RetroGameId } from "../arcade/arcadeGames";
import { useOfficeSettings, useReceptionTab } from "./officeSettings";
import "./office.css";
import "./officeHud.css";
import "./officeMinimap.css";
import "./officeFloors.css";
import { OfficeMinimap } from "./OfficeMinimap";
import { OfficeFullMap } from "./OfficeFullMap";
import { OfficeFrameDriver } from "./OfficeFrameDriver";
import { useProgressionSync } from "../progression/useProgressionSync";
import { useProgression } from "../progression/progressionStore";
import { LevelHud, LevelToasts } from "../progression/LevelHud";
import { LevelUpBanner } from "../progression/LevelUpBanner";
import { LevelHallScreen } from "../progression/hall/LevelHallScreen";
import "../progression/progression.css";

// Only loaded when a host without its own create dialog (the IDE's side panel) spawns an agent.
// Only loaded when someone plays a retro cabinet on the arcade floor.
const RetroArcadeOverlay = lazy(() => import("../arcade/RetroArcadeOverlay").then((m) => ({ default: m.RetroArcadeOverlay })));

// Dev-only handles for runtime checks of walking and panels.
if (import.meta.env.DEV && typeof window !== "undefined") Object.assign(window, { __officeStore: useOfficeStore, __officePlayer: player, __officeAgents: agentPositions, __officeSeated: seatedAtDesk,
  // Steps the scene without requestAnimationFrame (hidden test tabs): __officeStep(frames, dtMs).
  __officeStep: (frames = 60, dtMs = 16) => { let t = performance.now(); for (let i = 0; i < frames; i += 1) { t += dtMs; advance(t); } } });

/** Status refresh while the office is on screen; jittered so windows never poll in lockstep (AP-33). */
const REFRESH_MS = 5000;
const REFRESH_JITTER_MS = 1500;

const EMPTY_OCCUPANTS: ReadonlyMap<string, PaneOccupant> = new Map();

/** How long a station's short answer stays on screen. */
const NOTICE_MS = 4200;

/** Is this key press text going into a field? */
function typesText(target: EventTarget | null): boolean {
  return target instanceof HTMLElement && (target.isContentEditable || target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT");
}

/** The elevator doors: they slide in DOORS_MS and stay shut between DOORS_HOLD_MIN_MS and DOORS_HOLD_MAX_MS while the floor changes. */
const DOORS_MS = 640;
const DOORS_HOLD_MIN_MS = 450;
const DOORS_HOLD_MAX_MS = 1600;

class RenderBoundary extends Component<{ children: ReactNode; fallbackText: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.warn("Office renderer unavailable", error); }
  render() {
    return this.state.failed ? <div className="office-fallback" role="status">{this.props.fallbackText}</div> : this.props.children;
  }
}

export interface OfficeStageProps {
  /** The agents list (the IDE tab passes its own sessions list). */
  onOpenLedger?: () => void;
  onSelectAgent?: (id: string | null) => void;
  onCreateAgent?: () => void;
  onOpenGroup?: (groupId: string) => void;
  /** The floor to show on mount; without it the office opens on the floor it was left on. */
  initialFloor?: OfficeFloor;
  /** A narrow host (the IDE side panel): smaller HUD, no minimap or compass. */
  compact?: boolean;
  /** A visited map keeps its renderer while its host shows chat. */
  active?: boolean;
}

/** Visit-only subscriptions and sounds end when the retained world is hidden. */
function OfficeVisit({ floor }: { floor: OfficeFloor }) {
  useProgressionSync(true, floor);
  return null;
}

function useRosterRefresh(awake: boolean) {
  const client = useQueryClient();
  useEffect(() => {
    if (!awake) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        void client.invalidateQueries({ queryKey: ["society", "roster"] });
        schedule();
      }, REFRESH_MS + Math.random() * REFRESH_JITTER_MS);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [awake, client]);
}

/**
 * Agents created while the office is open appear on the spawn pad in the
 * middle of the floor and walk to their desk; everyone else is simply there.
 * Each floor keeps its own memory, so riding up or down never makes a whole
 * floor "arrive".
 */
function useNewcomers(active: SocietyAgent[], floor: OfficeFloor): ReadonlySet<string> {
  const [newcomers, setNewcomers] = useState<{ floor: OfficeFloor; ids: ReadonlySet<string> }>({ floor, ids: new Set() });
  useEffect(() => {
    const fresh = noteArrivals(knownOnFloor(floor), active.map((a) => a.agentId));
    if (fresh.length === 0) return;
    setNewcomers((prev) => ({ floor, ids: new Set([...(prev.floor === floor ? prev.ids : []), ...fresh]) }));
  }, [active, floor]);
  return newcomers.floor === floor ? newcomers.ids : EMPTY_IDS;
}
const EMPTY_IDS: ReadonlySet<string> = new Set();

export function OfficeStage({ onOpenLedger, onSelectAgent, onCreateAgent, onOpenGroup, initialFloor, compact = false, active: onScreen = true }: OfficeStageProps) {
  const t = useT();
  const hostRef = useRef<HTMLDivElement>(null);
  const visible = useCanvasAwake(hostRef);
  const awake = onScreen && visible;
  const onScreenRef = useRef(onScreen);
  onScreenRef.current = onScreen;
  const reduced = useReducedMotion() ?? false;
  const { generation } = useWebglSurface(hostRef);
  const webgl = useWebglSupported();
  // A mount that names a floor opens there (e.g. the IDE tab on the coding floor).
  // The switch writes to the store every host shares, so it happens in a layout effect, never while rendering
  // (another mounted office subscribed to `floor` would be updated in the middle of this render). Until it has
  // run, this stage already renders the floor it was asked for, so not a single frame shows the other one.
  const [opening, setOpening] = useState<OfficeFloor | null>(initialFloor ?? null);
  useLayoutEffect(() => {
    if (!opening) return;
    switchFloor(opening, false);
    setOpening(null);
    // Once per mount: a host that changes `initialFloor` later does not move a person who has ridden elsewhere.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const storeFloor = useOfficeStore((s) => s.floor);
  const floor = opening ?? storeFloor;
  const coding = floor === "coding";
  // The arcade floor has no agents: no roster, desks or chats, just the cabinets.
  const arcade = floor === "arcade";
  // Nobody works in the Level Hall either: it is the levels' own floor.
  const hall = floor === "hall";
  const roster = useSocietyRoster(awake);
  useRosterRefresh(awake && floor === "agents");
  // Jarvis keeps the person company as the pet chosen in My Pets.
  useSyncCompanionPet();
  const petName = useActivePet()?.name || "Gigi";
  // Levels: the person, their pet and every agent earn XP for real work; the Verse shows and celebrates it.
  const [overview, setOverview] = useState(0);
  const [mapOpen, setMapOpen] = useState(false);
  const [profile, setProfile] = useState<PlayerProfile>(loadProfile);
  const selection = useOfficeStore((s) => s.selection);
  const nearby = useOfficeStore((s) => s.nearby);
  const follow = useOfficeStore((s) => s.follow);
  const select = useOfficeStore((s) => s.select);

  // The call button tells how many are upstairs, so standing at the elevator wakes the coding roster too.
  const atLift = nearby?.kind === "checkpoint" && nearby.id === "elevator";
  const codingFloor = useCodingFloorOccupants(awake && (coding || atLift));
  const jarvisAgents = useMemo(() => (roster.data?.agents ?? []).filter((a) => a.lifecycle !== "archived"), [roster.data]);
  const codingAgents = useMemo(() => codingFloor.occupants.map((o) => o.agent), [codingFloor.occupants]);
  // The agents floor is built from the teams (society chat groups): every team has its studio. The roster waits
  // for the first answer about them, so nobody is seated in the pool and then sent across the floor.
  const chatGroups = useSocietyChatGroups(awake && floor === "agents");
  // A first failed read counts as an answer too: the floor opens without teams and rebuilds if a retry brings them.
  const teamsKnown = chatGroups.isSuccess || chatGroups.isError || chatGroups.failureCount > 0;
  const teams = useMemo<OfficeTeamInput[]>(() => (chatGroups.data ?? []).map((group) => ({
    id: group.group_id, name: group.name, members: group.members, createdMs: group.created_ms, leadId: group.lead_agent_id ?? null,
  })), [chatGroups.data]);
  const active = useMemo(() => (arcade || hall ? [] : coding ? codingAgents : teamsKnown ? jarvisAgents : []),
    [arcade, hall, coding, codingAgents, jarvisAgents, teamsKnown]);
  const ready = arcade || hall ? true : coding ? codingFloor.loaded : !!roster.data && teamsKnown;
  const occupants = useMemo(() => (coding ? codingFloor.byAgentId : EMPTY_OCCUPANTS), [coding, codingFloor.byAgentId]);
  const occupantsRef = useRef(occupants);
  occupantsRef.current = occupants;
  const agents = useMemo(() => new Map<string, SocietyAgent>(active.map((a) => [a.agentId, a])), [active]);
  const newcomers = useNewcomers(active, floor);
  // The floor plan depends on who works where, never on run state: a status
  // refresh changes monitors and behaviour without re-seating anyone.
  // The same holds for the teams: their 10 s refetch rebuilds the floor only when a team's name, members or lead changed.
  const teamsKey = floor === "agents"
    ? teams.map((team) => `${team.id}|${team.name}|${team.createdMs}|${team.leadId ?? ""}|${team.members.join("+")}`).join(",") : "";
  const seatingKey = floor + ":" + active.map((a) => `${a.agentId}|${a.tier}|${a.providerLabel}|${a.createdMs}`).join(",") + "#" + teamsKey;
  const layout = useMemo(() => (floor === "arcade" ? buildArcadeLayout() : floor === "hall" ? buildHallLayout()
    : buildOfficeLayout(active, { variant: floor, teams })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [seatingKey]);
  // Truthful overflow: how many of the floor's agents the plan could not seat.
  const seated = useMemo(() => seatedCount(layout), [layout]);
  const grid = useMemo(() => buildNavGrid(layout), [layout]);
  // One reservation book for the whole visit: a rebuilt floor plan (someone
  // joined or left) must not forget who already sits on which couch.
  const [book] = useState(() => new SpotBook());
  useEffect(() => { book.retain(new Set(layout.spots.map((spot) => spot.id))); }, [book, layout]);
  const agentsRef = useRef(agents);
  agentsRef.current = agents;
  const walkers = useMemo<WalkerContext>(() => {
    const desks = allDesks(layout);
    return {
      layout, grid, book, spawn: layout.arrival,
      colleagues: () => desks.filter((d) => d.agentId && agentsRef.current.get(d.agentId)?.state === "working")
        .map((d) => ({ agentId: d.agentId as string, desk: d })),
    };
  }, [layout, grid, book]);

  // Coding sessions have no desk chat; their monitors poll the terminal instead.
  const sessions = useMemo(() => new Map(active.filter((a) => a.chatSessionId).map((a) => [a.agentId, a.chatSessionId as string])), [active]);
  const chats = useDeskChats(sessions, awake && floor === "agents");
  // Opening someone: a coding agent opens its IDE pane; a Jarvis agent its chat
  // (a host without an agent view, like the IDE tab, goes to the Agents section).
  const openAgent = useCallback((agentId: string) => {
    const occupant = occupantsRef.current.get(agentId);
    if (occupant) { openPaneSession(occupant.pane); return; }
    if (onSelectAgent) onSelectAgent(agentId);
    else useEventStore.getState().setActiveSection("agents");
  }, [onSelectAgent]);
  // Clicking a chat monitor dives into it, then opens that agent's chat. A
  // coding agent's monitor opens its command panel instead: prompt it right
  // here, and "open" from there shows the pane maximized in the grid.
  const openTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(openTimer.current), []);
  const [diving, setDiving] = useState(false);
  const openScreen = useCallback((agentId: string, screen: Point & { y: number }, facing: number) => {
    select(null);
    clearTimeout(openTimer.current);
    if (occupantsRef.current.has(agentId)) { select({ kind: "agent", id: agentId }); return; }
    if (reduced) { openAgent(agentId); return; }
    useOfficeStore.getState().zoomInto([screen.x, screen.y, screen.z], facing);
    // The screen fills the view, then the real chat view fades in over it.
    setDiving(true);
    openTimer.current = setTimeout(() => { openAgent(agentId); setDiving(false); }, ZOOM_SECONDS * 1000 + 260);
  }, [openAgent, reduced, select]);
  // A Mission Control monitor was clicked: the camera dives into its glass,
  // then the section it shows opens. The Agents view hosting this map switches
  // to its list; any other host navigates to the Agents section.
  const sectionDive = useOfficeStore((s) => s.sectionDive);
  const lastSectionDive = useRef(sectionDive?.seq ?? 0);
  useEffect(() => {
    if (!sectionDive || sectionDive.seq === lastSectionDive.current) return;
    lastSectionDive.current = sectionDive.seq;
    if (!awake) return;
    const { section } = sectionDive;
    const go = () => {
      if (section === "agents" && !compact && onOpenLedger) onOpenLedger();
      else useEventStore.getState().setActiveSection(section);
    };
    clearTimeout(openTimer.current);
    if (reduced) { go(); return; }
    setDiving(true);
    openTimer.current = setTimeout(() => { go(); setDiving(false); }, ZOOM_SECONDS * 1000 + 260);
  }, [sectionDive, compact, onOpenLedger, reduced, awake]);

  // The elevator: pressing its call button, standing at the doors, opens the
  // button panel; pressing a floor there closes the elevator doors over the
  // stage, the floor switches behind them, and they open once the new floor
  // has loaded (capped). A press from afar (a click on the button, the floor
  // token or E anywhere) walks the character over instead; it never rides
  // from a distance. Reduced motion switches floors at once.
  const [picking, setPicking] = useState(false);
  const [ride, setRide] = useState<{ from: OfficeFloor; to: OfficeFloor; phase: DoorsPhase; closedMs: number } | null>(null);
  const rideTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(rideTimer.current), []);
  const pressCall = useCallback(() => {
    if (ride || picking) return;
    const lift = layout.checkpoints.find((cp) => cp.id === "elevator");
    if (!atElevator(player, lift)) {
      if (lift) useOfficeStore.getState().requestWalk({ x: lift.x, z: lift.z });
      return;
    }
    useOfficeStore.getState().select(null);
    setPicking(true);
  }, [ride, picking, layout]);
  const closePicker = useCallback(() => setPicking(false), []);
  const pickFloor = useCallback((to: OfficeFloor) => {
    setPicking(false);
    const from = useOfficeStore.getState().floor;
    if (ride || to === from) return;
    if (reduced) { switchFloor(to, true); return; }
    setRide({ from, to, phase: "closing", closedMs: 0 });
    clearTimeout(rideTimer.current);
    rideTimer.current = setTimeout(() => {
      switchFloor(to, true);
      setRide((r) => (r ? { ...r, phase: "closed", closedMs: performance.now() } : r));
      rideTimer.current = setTimeout(() => setRide((r) => (r?.phase === "closed" ? { ...r, phase: "opening" } : r)), DOORS_HOLD_MAX_MS);
    }, DOORS_MS);
  }, [ride, reduced]);
  // E at the elevator, or a click on its floor token, presses the call button instead of opening a panel.
  useEffect(() => {
    if (!awake || selection?.kind !== "checkpoint" || selection.id !== "elevator") return;
    select(null);
    pressCall();
  }, [selection, select, pressCall, awake]);
  useEffect(() => {
    if (ride?.phase === "closed" && floor === ride.to && ready) {
      // The doors stay shut a short beat at least, so the change reads as a ride and not a cut.
      const left = DOORS_HOLD_MIN_MS - (performance.now() - ride.closedMs);
      clearTimeout(rideTimer.current);
      rideTimer.current = setTimeout(() => setRide((r) => (r ? { ...r, phase: "opening" } : r)), Math.max(0, left));
    }
    if (ride?.phase === "opening") {
      clearTimeout(rideTimer.current);
      rideTimer.current = setTimeout(() => setRide(null), DOORS_MS);
    }
  }, [ride, floor, ready]);

  const counts = countStates(active);
  const updateProfile = useCallback((next: PlayerProfile) => { setProfile(next); saveProfile(next); }, []);
  // The coding floor's list is the IDE (or, in the IDE tab, its sessions list).
  const openList = useCallback(() => {
    if (coding && !compact) useEventStore.getState().setActiveSection("agentic-ide");
    else onOpenLedger?.();
  }, [coding, compact, onOpenLedger]);
  // Spawning a Jarvis agent (the spawn point, reception): the host's one-click create, or the office's
  // own where the host has none. The panel closes and the camera turns to the pad, where the agent appears.
  const quickCreate = useQuickCreateAgent();
  const creatingRef = useRef(false);
  const createAgent = useCallback((turnToPad = true) => {
    const store = useOfficeStore.getState();
    store.select(null);
    if (turnToPad && Math.hypot(player.x - layout.arrival.x, player.z - layout.arrival.z) > 4) store.focusOn(layout.arrival);
    if (onCreateAgent) { onCreateAgent(); return; }
    // A double click must not create two agents.
    if (creatingRef.current) return;
    creatingRef.current = true;
    void quickCreate()
      .catch((error) => {
        if (!isCreateCancelled(error)) console.warn("Agent creation failed", error);
      })
      .finally(() => { creatingRef.current = false; });
  }, [onCreateAgent, layout, quickCreate]);
  const actions = useMemo<OfficeActions>(() => ({
    onOpenAgent: openAgent,
    onOpenLedger: openList, onCreateAgent: () => createAgent(), onOpenGroup,
  }), [openAgent, openList, createAgent, onOpenGroup]);

  // A short line the HUD says once (a station answered without opening anything).
  const [notice, setNotice] = useState<string | null>(null);
  const noticeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(noticeTimer.current), []);
  const say = useCallback((text: string) => {
    setNotice(text);
    clearTimeout(noticeTimer.current);
    noticeTimer.current = setTimeout(() => setNotice(null), NOTICE_MS);
  }, []);
  // The coffee break in progress: who was called, until the call runs out on its own.
  const [coffeeBreak, setCoffeeBreak] = useState<{ ids: string[]; untilMs: number } | null>(null);
  useEffect(() => {
    if (!coffeeBreak) return;
    const timer = setTimeout(() => setCoffeeBreak(null), Math.max(0, coffeeBreak.untilMs - Date.now()));
    return () => clearTimeout(timer);
  }, [coffeeBreak]);
  // Stations that act instead of opening a surface: the spawn terminal opens the app's create dialog
  // (after a dive into its screen), the lead's desk selects the lead, the coffee bar calls or ends a break.
  useEffect(() => {
    if (!awake || selection?.kind !== "checkpoint") return;
    const store = useOfficeStore.getState();
    if (selection.id === "spawn") {
      store.select(null);
      clearTimeout(openTimer.current);
      // The dive leads into the dialog; a host that creates at once (no dialog) keeps the pad in view instead.
      const dive = onCreateAgent && !reduced ? spawnScreenDive(layout, player) : null;
      if (!dive) { createAgent(); return; }
      store.zoomInto(dive.target, dive.facing, dive.size);
      openTimer.current = setTimeout(() => createAgent(false), ZOOM_SECONDS * 1000 + 120);
    } else if (selection.id === "lead") {
      const lead = active.filter((a) => a.tier === "lead").sort((a, b) => a.createdMs - b.createdMs || a.agentId.localeCompare(b.agentId))[0];
      if (lead) { store.select({ kind: "agent", id: lead.agentId }); return; }
      store.select(null);
      say(t("society.office.lead_empty"));
    } else if (selection.id === "break") {
      store.select(null);
      if (coffeeBreak && coffeeBreak.untilMs > Date.now()) {
        store.release(coffeeBreak.ids);
        setCoffeeBreak(null);
        say(t("society.office.break_ended"));
        return;
      }
      const idle = active.filter((a) => a.state === "idle").map((a) => a.agentId);
      if (idle.length === 0) { say(t("society.office.break_none")); return; }
      store.summon(idle, loungeCentre(layout), CALL_MS);
      setCoffeeBreak({ ids: idle, untilMs: Date.now() + CALL_MS });
      say(t("society.office.break_called").replace("{0}", String(idle.length)));
    }
  }, [selection, awake, onCreateAgent, reduced, layout, createAgent, active, coffeeBreak, say, t]);
  // Something opened: whatever the pointer rested on in the world is behind it now (a dialog swallows the pointer-out).
  useEffect(() => {
    if (!selection) return;
    useOfficeStore.getState().setHover(null);
    document.body.style.cursor = "";
  }, [selection]);
  // The coding floor's spawn terminal: dive into its screen first, then its launcher opens (reduced motion: at once).
  const atLaunch = selection?.kind === "checkpoint" && selection.id === "launch";
  const [launcherOpen, setLauncherOpen] = useState(false);
  const layoutRef = useRef(layout);
  layoutRef.current = layout;
  useEffect(() => {
    if (!awake || !atLaunch) { setLauncherOpen(false); return; }
    const dive = reduced ? null : spawnScreenDive(layoutRef.current, player);
    if (!dive) { setLauncherOpen(true); return; }
    useOfficeStore.getState().zoomInto(dive.target, dive.facing, dive.size);
    const timer = setTimeout(() => setLauncherOpen(true), ZOOM_SECONDS * 1000 + 120);
    return () => clearTimeout(timer);
  }, [atLaunch, awake, reduced]);
  // A team studio that left the floor plan takes its open sheet with it.
  useEffect(() => {
    if (awake && selection?.kind === "team" && !stationOf(layout, selection)) select(null);
  }, [selection, layout, select, awake]);

  // Whatever closes (a dialog, a docked panel) hands the keyboard back to the map's canvas host, so the walking
  // keys answer at once and focus never strands on a button that is gone.
  const focusMap = useCallback(() => hostRef.current?.focus({ preventScroll: true }), []);
  const hadSelection = useRef(false);
  useEffect(() => {
    const had = hadSelection.current;
    hadSelection.current = !!selection;
    if (!awake || selection || !had) return;
    const focused = document.activeElement;
    if (!focused || focused === document.body) focusMap();
  }, [selection, awake, focusMap]);
  // Escape closes an open panel before it can leave the map.
  useEffect(() => {
    if (!awake) return;
    const onKey = (event: KeyboardEvent) => {
      // A field or a dialog (e.g. the create dialog opened from reception) owns its own Escape.
      if (event.key !== "Escape" || !useOfficeStore.getState().selection || ownsKeyboard(event.target)) return;
      event.preventDefault();
      event.stopPropagation();
      select(null);
      focusMap();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [select, awake]);

  // H (or the HUD button) opens reception on the controls guide from anywhere, and closes it again.
  const toggleGuide = useCallback(() => {
    if (isReception(useOfficeStore.getState().selection)) { select(null); return; }
    useReceptionTab.getState().setTab("controls");
    select({ kind: "checkpoint", id: "manage" });
  }, [select]);
  useEffect(() => {
    if (!awake) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.code !== "KeyH" || event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
      const current = useOfficeStore.getState().selection;
      // The open directory is a dialog of its own: H closes it again unless the person is typing in it.
      if (isReception(current) ? typesText(event.target) : ownsKeyboard(event.target)) return;
      if (current?.kind === "arcade") return;
      event.preventDefault();
      toggleGuide();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleGuide, awake]);

  // The Level Hall's two checkpoints open its screen: the stage on the studio, the guide on the overview.
  useEffect(() => {
    if (!awake || selection?.kind !== "checkpoint" || (selection.id !== "studio" && selection.id !== "levels")) return;
    useProgression.getState().openPanel(selection.id === "studio" ? "studio" : "overview");
    select(null);
  }, [selection, select, awake]);

  // L (or the level card) opens the Level Hall screen, and closes it again.
  useEffect(() => {
    if (!awake) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.code !== "KeyL" || event.repeat || event.ctrlKey || event.metaKey || event.altKey) return;
      const levels = useProgression.getState();
      if (ownsKeyboard(event.target) && !levels.panel) return;
      if (useOfficeStore.getState().selection?.kind === "arcade") return;
      event.preventDefault();
      levels.openPanel(levels.panel ? null : "overview");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [awake]);
  // The Level Hall screen closes with the map.
  useEffect(() => () => { if (onScreenRef.current) useProgression.getState().openPanel(null); }, []);

  // Leaving the map forgets panels and calls; the office opens fresh next time.
  useEffect(() => () => {
    if (!onScreenRef.current) return;
    const store = useOfficeStore.getState();
    store.select(null);
    store.setNearby(null);
    store.setHover(null);
    store.clearSummons();
  }, []);

  useEffect(() => {
    if (onScreen) return;
    // A mode change ends input and pending navigation without discarding GPU resources.
    clearTimeout(openTimer.current);
    clearTimeout(rideTimer.current);
    setDiving(false);
    setPicking(false);
    setRide(null);
    setMapOpen(false);
    useProgression.getState().openPanel(null);
    clearTimeout(noticeTimer.current);
    setNotice(null);
    setCoffeeBreak(null);
    const store = useOfficeStore.getState();
    store.select(null);
    store.setNearby(null);
    store.setHover(null);
    store.clearSummons();
  }, [onScreen]);

  // A panel for an agent that left the roster closes itself.
  useEffect(() => {
    if (awake && selection?.kind === "agent" && ready && !agents.has(selection.id)) select(null);
  }, [selection, agents, ready, select, awake]);

  const selectedAgent = selection?.kind === "agent" ? agents.get(selection.id) ?? null : null;
  const selectedPane = selectedAgent ? occupants.get(selectedAgent.agentId) ?? null : null;
  const nearbyGame = nearby?.kind === "arcade" ? gameForCabinet(nearby.id) : null;
  // The one prompt: what the pointer rests on from afar, else what the character stands at.
  const hover = useOfficeStore((s) => s.hover);
  const promptTarget: Selection | null = hover && !sameSelection(hover, nearby) ? hover : nearby;
  const breakOn = !!coffeeBreak;
  const promptLine = useMemo<PromptLine | null>(() => {
    if (!promptTarget) return null;
    const how = promptTarget === nearby ? "key" : "click";
    if (promptTarget.kind === "agent") {
      const name = agents.get(promptTarget.id)?.name;
      return name ? { how, action: t(coding ? "society.office.prompt_pane" : "society.office.prompt_agent").replace("{0}", name) } : null;
    }
    if (promptTarget.kind === "arcade") {
      const game = gameForCabinet(promptTarget.id);
      return { how, action: game ? t("society.arcade.play_prompt").replace("{0}", game.title) : t("society.office.arcade_prompt") };
    }
    const station = stationsFor(layout).find((s) => s.key === selectionKey(promptTarget));
    return station ? { how, action: stationAction(station, t, breakOn), object: stationLabel(station, t) } : null;
  }, [promptTarget, nearby, agents, coding, layout, breakOn, t]);
  // Standing at a retro cabinet fetches its overlay, so pressing E opens it at once instead of after a chunk load.
  const nearbyRetro = nearbyGame?.kind === "retro";
  useEffect(() => { if (nearbyRetro) void import("../arcade/RetroArcadeOverlay"); }, [nearbyRetro]);
  // The cabinet being played: the break room's (and the hall's Asteroid Run) open the 3D game, the others a retro game.
  const playing = selection?.kind === "arcade" ? gameForCabinet(selection.id) : null;
  const playsAsteroids = selection?.kind === "arcade" && (!playing || playing.kind === "asteroid3d");
  const titleKey = arcade ? "society.office.arcade_floor_title" : hall ? "society.office.hall_floor_title"
    : coding ? "society.office.coding_title" : "society.office.title";
  const playerName = profile.name.trim() || t("society.office.you");
  const playerToyLook = useMemo(() => playerLook(profile), [profile]);
  const agentNames = useMemo(() => new Map(jarvisAgents.map((a) => [a.agentId, a.name])), [jarvisAgents]);
  const hintsSeen = useOfficeSettings((s) => s.hintsSeen);
  const receptionOpen = isReception(selection);
  // A station's own surface: a dialog over the map, or a panel docked beside it (the wardrobe).
  // The coding floor's spawn terminal has a screen: its launcher opens once the camera has dived into it.
  const surface = atLaunch && !launcherOpen ? null : stationSurface(selection);
  const agentPanel = selection?.kind === "agent" && !!selectedAgent && !selectedPane;

  // A full-view office draws no more pixels than a side-panel one would afford.
  const dpr = useDprBudget(hostRef);

  return (
    <CanvasActivity.Provider value={awake}>
    <section className={compact ? "office-stage office-stage-compact" : "office-stage"} aria-label={t(titleKey)}
      data-office-agents={active.length} data-office-floor={floor} data-office-awake={awake}>
      <div ref={hostRef} className="office-viewport" tabIndex={0} role="application" aria-label={t("society.office.viewport")}>
        {webgl ? (
          <RenderBoundary key={generation} fallbackText={t("society.office.no_graphics")}>
            <Suspense fallback={<div className="office-fallback" role="status">{t("society.office.loading")}</div>}>
              <Canvas shadows="percentage" camera={{ fov: CAMERA_FOV, near: 0.2, far: 800, position: [30, 30, 30] }} dpr={dpr}
                gl={{ antialias: true, alpha: true, preserveDrawingBuffer: import.meta.env.DEV }}
                frameloop={!awake ? "never" : compact ? "demand" : "always"}
                onPointerMissed={() => select(null)}>
                <OfficeFrameDriver enabled={awake && compact} />
                <OfficeScene floor={floor} occupants={occupants} ready={ready} layout={layout} grid={grid} walkers={walkers} agents={agents} newcomers={newcomers}
                  awake={awake} reduced={reduced} overview={overview} player={{ look: playerToyLook, name: playerName }}
                  selection={selection} nearby={nearby} chats={chats} onOpenScreen={openScreen}
                  elevatorCall={{ lit: picking || !!ride, picking, onPress: pressCall }} />
              </Canvas>
            </Suspense>
          </RenderBoundary>
        ) : <div className="office-fallback" role="status">{t("society.office.no_graphics")}</div>}
      </div>

      {awake && <>
      <OfficeVisit floor={floor} />
      <div className="office-hud office-hud-left" data-office-ui>
        {/* One card: the floor's name, and under it who is doing what. */}
        <div className="office-card office-title">
          <strong>{t(titleKey)}</strong>
          {arcade
            ? <span>{t("society.office.arcade_floor_subtitle").replace("{0}", String(ARCADE_GAMES.length))}</span>
            : hall ? <span>{t("society.office.hall_floor_subtitle")}</span> : (
              <span className="office-states" role="status" aria-live="polite">
                <span data-tone="working"><i aria-hidden />{t("society.office.count_working").replace("{0}", String(counts.working))}</span>
                <span data-tone="waiting"><i aria-hidden />{t("society.office.count_waiting").replace("{0}", String(counts.waiting))}</span>
                <span data-tone="idle"><i aria-hidden />{t("society.office.count_idle").replace("{0}", String(counts.idle))}</span>
                {counts.paused > 0 && <span data-tone="paused"><i aria-hidden />{t("society.office.count_paused").replace("{0}", String(counts.paused))}</span>}
              </span>
            )}
        </div>
        <LevelHud playerName={playerName} petName={petName} compact={compact} />
        {/* A running team meeting, while its sheet is closed; this card also ends it when its time is up. */}
        {surface !== "sheet" && <MeetingStatus agents={active} layout={layout} actions={actions} compact />}
        {!coding && roster.data?.sample && <p className="office-card office-note">{t("society.office.sample")}</p>}
        {coding && codingFloor.loaded && active.length === 0 && <p className="office-card office-note">{t("society.office.coding_empty")}</p>}
        {active.length > seated && <p className="office-card office-note">{t("society.office.overflow").replace("{0}", String(seated))}</p>}
      </div>

      {/* The wardrobe and the Level Hall are places (the places menu, their own keys), not permanent buttons. */}
      <OfficeTools layout={layout} follow={follow} onFollow={() => useOfficeStore.getState().setFollow(true)}
        onOverview={() => setOverview((v) => v + 1)} helpOpen={receptionOpen} onHelp={toggleGuide}
        list={!arcade && !hall && (!coding || !compact || onOpenLedger) ? {
          label: t(coding ? (compact ? "society.office.ledger_coding" : "society.office.open_ide") : "society.office.ledger"),
          ide: coding && !compact, onOpen: openList,
        } : null} />

      {playsAsteroids && <ArcadeCabinet onClose={() => select(null)} />}
      {playing && playing.kind === "retro" && (
        <Suspense fallback={null}>
          <RetroArcadeOverlay gameId={playing.id as RetroGameId} onClose={() => select(null)} />
        </Suspense>
      )}

      {/* A coding session is a window of its own on the stage, not a panel in the corner slot. */}
      {selection?.kind === "agent" && selectedPane && (
        <PaneCommandPanel occupant={selectedPane} compact={compact} onOpen={() => openPaneSession(selectedPane.pane)} onClose={() => select(null)} />
      )}
      {/* An agent's walkie-talkie and the wardrobe sit beside the map; every other station's surface is a dialog over it. */}
      {(agentPanel || surface === "side") && selection && (
        <div className="office-panel-slot" data-tall={surface === "side" || undefined}>
          {agentPanel && selectedAgent
            ? <AgentPanel agent={selectedAgent} actions={actions} onClose={() => select(null)} />
            : <StationSurface selection={selection} floor={floor} agents={active} layout={layout} grid={grid} sample={!coding && (roster.data?.sample ?? false)}
                profile={profile} onProfile={updateProfile} actions={actions} onClose={() => select(null)} />}
        </div>
      )}
      {surface === "sheet" && selection && (
        <StationSurface selection={selection} floor={floor} agents={active} layout={layout} grid={grid} sample={!coding && (roster.data?.sample ?? false)}
          profile={profile} onProfile={updateProfile} actions={actions} onClose={() => select(null)} returnFocus={focusMap} />
      )}

      {/* Bottom centre: the one prompt, a station's short answer, and the controls for a first visit. */}
      <div className="office-hud office-hud-bottom">
        {promptLine && promptTarget && !selection && !picking && !ride && (
          <StationPrompt line={promptLine} compact={compact} onUse={() => select(promptTarget)} />
        )}
        <div role="status" aria-live="polite">{notice && <p className="office-card office-notice" data-office-ui>{notice}</p>}</div>
        {!compact && !hintsSeen && !selection && !picking && !ride && (
          <ControlHints onDismiss={() => useOfficeSettings.getState().set({ hintsSeen: true })} />
        )}
      </div>
      {diving && <div className="office-dive-fade" aria-hidden />}
      {picking && !ride && <ElevatorPanel floor={floor} onPick={pickFloor} onClose={closePicker} />}
      {ride && <ElevatorDoors from={ride.from} to={ride.to} phase={ride.phase} />}
      {!compact && <OfficeMinimap layout={layout} agents={agents} selectedId={selection?.kind === "agent" ? selection.id : null}
        onOpenMap={() => setMapOpen(true)} />}
      <OfficeFullMap open={mapOpen} onOpen={() => setMapOpen(true)} onClose={() => setMapOpen(false)}
        layout={layout} agents={agents} selectedId={selection?.kind === "agent" ? selection.id : null} />
      <LevelToasts names={agentNames} agents={jarvisAgents} />
      <LevelHallScreen agents={jarvisAgents} playerName={playerName} petName={petName} playerLook={playerToyLook} />
      <LevelUpBanner playerName={playerName} petName={petName} />
      </>}
    </section>
    </CanvasActivity.Provider>
  );
}

export default OfficeStage;
