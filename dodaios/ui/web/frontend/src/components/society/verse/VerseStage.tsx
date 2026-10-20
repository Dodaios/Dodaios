/**
 * Agents > Dodaios Verse: the interior of the capital ship, seen from above.
 *
 * Each deck is a photograph rendered offline (the plate); the stage puts the
 * live crew, their screens and the ship's small lights into it with a camera
 * that matches the photograph exactly (BRIEF §3). The person is the
 * commanding officer; the agents are officers at the bridge consoles; coding
 * panes are technicians at engineering's terminals; stations turn places of
 * the ship into the app's actions.
 */
import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Canvas } from "@react-three/fiber";
import { useReducedMotion } from "framer-motion";
import { CanvasActivity, useCanvasAwake } from "@/hooks/useCanvasAwake";
import { useWebglSurface } from "@/hooks/useWebglSurface";
import { useWebglSupported } from "@/lib/graphDimension";
import { fill, useLocaleChunk, useT } from "@/i18n";
import { useEventStore } from "@/store/events";
import { useQuickCreateAgent } from "../data";
import { isCreateCancelled } from "../create/createAgentStore";
import { useSyncCompanionPet } from "../companion/companionPetStore";
import { openPaneSession } from "../crewFeeds/codingNavigate";
import { useProgressionSync } from "../progression/useProgressionSync";
import { useProgression } from "../progression/progressionStore";
import { RankCard, RanksOverlay, rankForLevel, useCommanderRank, useCommanderUniform } from "./ranks";
import type { DeckId } from "./decks";
import type { Deck, Station } from "./content/deck";
import { useDeck } from "./content/useDeck";
import { CAMERA_FAR } from "./engine/plateCamera";
import { DeckBackdrop } from "./engine/DeckBackdrop";
import { DeckEnvironment } from "./engine/DeckEnvironment";
import { DebugOverlay } from "./engine/DebugOverlay";
import { attachPointerInput } from "./engine/pointerInput";
import { pickBody, pickStation } from "./engine/picking";
import { worldToPlate } from "./engine/plateMath";
import { screenToPlate } from "./engine/view";
import type { PanKey } from "./engine/viewController";
import { ActorsLayer } from "./actors/ActorsLayer";
import { useCharacterLibrary } from "./actors/useCharacterLibrary";
import type { Look } from "./actors/look";
import { buildCast, COMMANDER_ID, type CommanderState } from "./life/cast";
import { commanderTarget, type CommanderOrders } from "./life/commander";
import { useCrewLife } from "./life/useCrewLife";
import { useWorldActions } from "./life/useWorldActions";
import { useDevDuty } from "./life/devOverrides";
import { pickFloor } from "./nav/floorPick";
import { nearestWalkable } from "./nav/pathfind";
import { ScreensLayer } from "./effects/ScreensLayer";
import { useScreenFaces } from "./effects/useScreenFaces";
import { HoloLayer } from "./effects/HoloLayer";
import { BeaconsLayer } from "./effects/BeaconsLayer";
import { LightsLayer } from "./effects/LightsLayer";
import { FloatingLabels, type PlateInfo } from "./hud/FloatingLabels";
import { CrewCard, type CrewCardInfo } from "./hud/CrewCard";
import { LiftPanel } from "./hud/LiftPanel";
import { DeckTitle, StatsReadout, Toolbar } from "./hud/DeckBar";
import { LauncherPanel } from "./hud/LauncherPanel";
import { SimulatorPanel } from "./hud/SimulatorPanel";
import { StageRuntime } from "./runtime";
import "./verse.css";

export interface VerseStageProps {
  onOpenLedger?: () => void;
  onSelectAgent?: (id: string | null) => void;
  onCreateAgent?: () => void;
  onOpenGroup?: (groupId: string) => void;
  /** The deck to show on mount (the IDE side panel opens on engineering). */
  initialDeck?: DeckId;
  compact?: boolean;
  /** A visited stage keeps its renderer while its host shows something else. */
  active?: boolean;
}

class RenderBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(error: Error) { console.error("Verse renderer failed", error); }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

const PAN_KEYS: Record<string, PanKey> = {
  KeyA: "left", ArrowLeft: "left", KeyD: "right", ArrowRight: "right", KeyW: "up", ArrowUp: "up", KeyS: "down", ArrowDown: "down",
};
/** How long the off-duty crew stays in the mess when called. */
const MESS_CALL_MS = 90_000;
const NOTICE_MS = 4200;
const DOORS_MS = 460;
const DOORS_GIVE_UP_MS = 5000;

type Hover = { kind: "crew"; id: string } | { kind: "station"; id: string } | null;
type Panel = "lift" | "launcher" | "games" | null;

function typesText(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  return !!el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));
}

const sameHover = (a: Hover, b: Hover) => a === b || (!!a && !!b && a.kind === b.kind && a.id === b.id);

export function VerseStage({ onOpenLedger, onSelectAgent, onCreateAgent, onOpenGroup, initialDeck, compact = false, active = true }: VerseStageProps) {
  const t = useT();
  const chunkReady = useLocaleChunk("ship");
  const hostRef = useRef<HTMLDivElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  const visible = useCanvasAwake(hostRef);
  const awake = active && visible;
  const reduced = useReducedMotion() ?? false;
  const { generation } = useWebglSurface(hostRef);
  const webgl = useWebglSupported();
  const runtime = useMemo(() => new StageRuntime(), []);
  runtime.view.reduced = reduced;

  const [deckId, setDeckId] = useState<DeckId>(initialDeck ?? "bridge");
  const deckState = useDeck(deckId);
  const deck = deckState.deck;
  /** The deck whose plate is on screen. */
  const [shownDeck, setShownDeck] = useState<Deck | null>(null);
  const plateReady = !!deck && shownDeck === deck;
  const [failure, setFailure] = useState<Error | null>(null);
  const [debug, setDebug] = useState(false);
  const [hover, setHover] = useState<Hover>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [notice, setNotice] = useState<string | null>(null);
  /** The deck the lift is riding to while its doors are shut; null when they are open. */
  const [doors, setDoors] = useState<DeckId | null>(null);
  const [messUntil, setMessUntil] = useState(0);
  const [orders, setOrders] = useState<CommanderOrders>({ target: null, order: 0, fromLift: false });

  useSyncCompanionPet();
  useProgressionSync(awake, deckId);
  const library = useCharacterLibrary(awake);
  const life = useCrewLife(deck, deckId, awake, messUntil > Date.now());
  const faces = useScreenFaces(deck, life, awake, t);
  const runningTeams = useMemo(() => new Set(life.rounds.keys()), [life.rounds]);
  useWorldActions(runtime, deck, deckId, awake, runningTeams);
  // The crew salute when the commander is promoted.
  const saluteAt = useProgression((s) => s.cheerUntil);
  const commanderRank = useCommanderRank();
  const uniform = useCommanderUniform();

  // Development handles for runtime checks: the stage's state, its camera, where everyone stands, the frame numbers.
  // `life` is read through a getter, so the handle always shows the crew as the stage sees it now.
  const lifeRef = useRef(life);
  lifeRef.current = life;
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    const handle = {
      runtime,
      camera: runtime.view,
      actors: runtime.poses,
      setDuty: useDevDuty.getState().setDuty,
      get life() { return lifeRef.current; },
    };
    Object.assign(window, { __verse: handle, __verseStats: runtime.stats });
  }, [runtime]);

  // The IDE tab always opens on its deck; another host keeps where the person last was.
  useEffect(() => { if (awake && initialDeck) setDeckId(initialDeck); }, [awake, initialDeck]);

  // A new deck: frame where the commander comes aboard (out of the lift after a ride).
  const ordersRef = useRef(orders);
  ordersRef.current = orders;
  useEffect(() => {
    setShownDeck(null);
    setFailure(null);
    setHover(null);
    runtime.deck = deck;
    if (!deck) return;
    const start = commanderTarget(deck, ordersRef.current);
    runtime.view.setPlate(deck.camera, worldToPlate(deck.camera, start.x, 0, start.z));
  }, [deck, runtime]);

  // The doors open once the car has arrived and the new deck is on screen (or after a moment, whatever happens).
  useEffect(() => {
    if (!doors) return;
    const arrived = doors === deckId && (plateReady || !!failure || !!deckState.error);
    const timer = setTimeout(() => setDoors(null), arrived ? 150 : DOORS_GIVE_UP_MS);
    return () => clearTimeout(timer);
  }, [doors, deckId, plateReady, failure, deckState.error]);

  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  useEffect(() => () => { for (const timer of timers.current) clearTimeout(timer); }, []);
  const later = useCallback((fn: () => void, ms: number) => { timers.current.push(setTimeout(fn, ms)); }, []);
  const say = useCallback((text: string) => {
    setNotice(text);
    later(() => setNotice((n) => (n === text ? null : n)), NOTICE_MS);
  }, [later]);

  const quickCreate = useQuickCreateAgent();
  const creating = useRef(false);
  const createAgent = useCallback(() => {
    if (onCreateAgent) { onCreateAgent(); return; }
    if (creating.current) return;
    creating.current = true;
    void quickCreate().catch((e) => { if (!isCreateCancelled(e)) console.warn("Agent creation failed", e); }).finally(() => { creating.current = false; });
  }, [onCreateAgent, quickCreate]);

  const openCrew = useCallback((id: string) => {
    const pane = life.panes.get(id);
    if (pane) { openPaneSession(pane.pane); return; }
    if (onSelectAgent) onSelectAgent(id);
    else useEventStore.getState().setActiveSection("agents");
  }, [life.panes, onSelectAgent]);

  // A walk order belongs to the deck on screen; another deck ignores it.
  const walkTo = useCallback((x: number, z: number) => {
    const on = runtime.deck?.id;
    if (!on) return;
    setOrders((o) => ({ target: { deck: on, x, z }, order: o.order + 1, fromLift: o.fromLift }));
  }, [runtime]);

  const rideTo = useCallback((to: DeckId) => {
    setPanel(null);
    setSelected(null);
    if (to === deckId) return;
    const go = () => {
      setDeckId(to);
      setOrders((o) => ({ target: null, order: o.order + 1, fromLift: true }));
    };
    if (reduced) { go(); return; }
    setDoors(to);
    later(go, DOORS_MS);
  }, [deckId, reduced, later]);

  const teamAtTable = useCallback(() => {
    // The team in session if there is one, else the first team aboard.
    for (const team of life.teams) if (life.rounds.has(team.id)) return team;
    return life.teams[0] ?? null;
  }, [life.teams, life.rounds]);

  const activateStation = useCallback((station: Station) => {
    if (station.kind !== "lift") walkTo(station.x, station.z);
    switch (station.kind) {
      case "agents_list":
        if (onOpenLedger) onOpenLedger(); else useEventStore.getState().setActiveSection("agents");
        return;
      case "team": {
        const team = teamAtTable();
        if (!team) { say(t("verse.notice.no_team")); return; }
        if (onOpenGroup) onOpenGroup(team.id); else useEventStore.getState().setActiveSection("agents");
        return;
      }
      // The records hall opens the rank ladder; any other service-record station (the ready room's desk) the record itself.
      case "service_record": useProgression.getState().openRecord(station.room?.includes("records") ? "ladder" : "record"); return;
      case "quartermaster": useProgression.getState().openRecord("rewards"); return;
      case "mess_call": {
        if (messUntil > Date.now()) { setMessUntil(0); say(t("verse.notice.mess_ended")); return; }
        const free = [...life.crew.values()].filter((m) => m.role === "officer" && m.status === "idle").length;
        if (free === 0) { say(t("verse.notice.mess_nobody")); return; }
        setMessUntil(Date.now() + MESS_CALL_MS);
        later(() => setMessUntil((until) => (until <= Date.now() ? 0 : until)), MESS_CALL_MS + 50);
        say(fill(t("verse.notice.mess_called"), { count: free }));
        return;
      }
      case "games": setPanel("games"); return;
      case "coding_launcher": setPanel("launcher"); return;
      case "create_agent": createAgent(); return;
      case "lift": walkTo(station.x, station.z); setPanel("lift"); return;
    }
  }, [walkTo, onOpenLedger, onOpenGroup, teamAtTable, say, t, messUntil, life.crew, later, createAgent]);

  // Pointer: hover labels, taps on crew, stations and the floor.
  const hit = useCallback((sx: number, sy: number): Hover => {
    const d = runtime.deck;
    if (!d) return null;
    const p = screenToPlate(runtime.view.current, runtime.view.vp, sx, sy);
    const body = pickBody(d.camera, runtime.poses.values(), p, (id) => life.crew.has(id));
    if (body) return { kind: "crew", id: body };
    const station = pickStation(d, p);
    return station ? { kind: "station", id: station.id } : null;
  }, [runtime, life.crew]);

  const handlers = useRef({ hover: (_x: number, _y: number) => undefined as void, tap: (_x: number, _y: number) => undefined as void });
  handlers.current.hover = (sx, sy) => {
    const h = hit(sx, sy);
    setHover((prev) => (sameHover(prev, h) ? prev : h));
    if (surfaceRef.current) surfaceRef.current.dataset.cursor = h ? "pointer" : "";
  };
  handlers.current.tap = (sx, sy) => {
    const d = runtime.deck;
    if (!d) return;
    hostRef.current?.focus({ preventScroll: true });
    const h = hit(sx, sy);
    if (h?.kind === "crew") {
      if (selected === h.id) { openCrew(h.id); return; }
      setSelected(h.id);
      return;
    }
    if (h?.kind === "station") {
      const station = d.stations.find((s) => s.id === h.id);
      if (station) activateStation(station);
      return;
    }
    setSelected(null);
    const p = screenToPlate(runtime.view.current, runtime.view.vp, sx, sy);
    const floor = pickFloor(d.camera, d.nav, p.u, p.v);
    if (floor) walkTo(floor.x, floor.z);
  };

  useEffect(() => {
    const el = surfaceRef.current;
    if (!el) return;
    return attachPointerInput(el, runtime.view, {
      tap: (x, y) => handlers.current.tap(x, y),
      hover: (x, y) => handlers.current.hover(x, y),
      leave: () => setHover(null),
      moved: () => setHover(null),
    });
  }, [runtime, webgl, generation]);

  // Keyboard: pan with WASD/arrows, zoom with +/-, Escape closes, F9 the alignment overlay (development).
  useEffect(() => {
    if (!awake) return;
    const owns = (e: KeyboardEvent) => {
      if (typesText(e.target) || e.ctrlKey || e.metaKey || e.altKey) return false;
      const focused = document.activeElement;
      return !focused || focused === document.body || !!hostRef.current?.contains(focused);
    };
    const down = (e: KeyboardEvent) => {
      if (!owns(e)) return;
      const key = PAN_KEYS[e.code];
      const v = runtime.view;
      if (key) { e.preventDefault(); v.setKey(key, true, e.shiftKey); return; }
      if (e.code === "Equal" || e.code === "NumpadAdd") v.zoomAt(v.vp.width / 2, v.vp.height / 2, 1.25);
      else if (e.code === "Minus" || e.code === "NumpadSubtract") v.zoomAt(v.vp.width / 2, v.vp.height / 2, 0.8);
      else if (e.code === "Escape") { setPanel(null); setSelected(null); }
      else if (e.code === "F9" && import.meta.env.DEV) setDebug((d) => !d);
    };
    const up = (e: KeyboardEvent) => {
      const key = PAN_KEYS[e.code];
      if (key) runtime.view.setKey(key, false, e.shiftKey);
    };
    const blur = () => runtime.view.clearKeys();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      runtime.view.clearKeys();
    };
  }, [awake, runtime]);

  const focusOn = useCallback((id: string) => {
    const pose = runtime.poses.get(id);
    const d = runtime.deck;
    if (!pose || !d) return;
    const p = worldToPlate(d.camera, pose.x, pose.y, pose.z);
    runtime.view.focus(p.u, p.v);
  }, [runtime]);

  // The cast: crew placed by crew life, the commander, the companion, the ship's company.
  const commanderLook = useMemo<Look>(() => ({ tier: uniform, accent: null, plate: commanderRank.rank.plate }), [uniform, commanderRank.rank.plate]);
  const cast = useMemo(() => {
    if (!deck || !library || !life.ready) return [];
    const state: CommanderState = { look: commanderLook, orders };
    return buildCast({ deck, contract: library.contract, crew: life.crew, placements: life.placements, looks: life.looks, aboard: life.aboard, arriving: life.arriving, commander: state });
  }, [deck, library, life.ready, life.crew, life.placements, life.looks, life.aboard, life.arriving, commanderLook, orders]);

  const deckStatuses = useMemo(() => {
    const m = new Map<string, NonNullable<ReturnType<typeof life.statuses.get>>>();
    for (const id of life.placements.keys()) {
      const s = life.statuses.get(id);
      if (s) m.set(id, s);
    }
    return m;
  }, [life.placements, life.statuses]);
  const alarm = useMemo(() => [...deckStatuses.values()].includes("error"), [deckStatuses]);
  const holos = useMemo(() => deck?.sockets.filter((s) => s.kind === "holo") ?? [], [deck]);
  const litHolos = useMemo(() => {
    const lit = new Set<string>();
    if (!deck) return lit;
    for (const h of holos) {
      const station = h.station ? deck.stations.find((s) => s.id === h.station) : undefined;
      // A team table lights for a round in session; every other emitter is a standing display.
      if (station?.kind !== "team" || life.rounds.size > 0) lit.add(h.id);
    }
    return lit;
  }, [deck, holos, life.rounds]);

  // HUD data.
  const rankName = useCallback((id: string) => t(`verse.ranks.rank.${rankForLevel(life.levels.get(id) ?? 1).id}`), [t, life.levels]);
  const plates = useMemo<PlateInfo[]>(() => {
    const ids = new Set<string>();
    if (hover?.kind === "crew") ids.add(hover.id);
    if (selected) ids.add(selected);
    return [...ids].flatMap((id) => {
      const m = life.crew.get(id);
      if (!m) return [];
      const accent = life.looks.get(id)?.accent ?? null;
      return [{ id, name: m.name, rank: m.role === "technician" ? t("verse.post.terminal") : rankName(id), status: t(`verse.state.${m.status}`), statusKey: m.status, accent }];
    });
  }, [hover, selected, life.crew, life.looks, rankName, t]);
  const hoveredStation = useMemo(() => {
    if (hover?.kind !== "station" || !deck) return null;
    const station = deck.stations.find((s) => s.id === hover.id);
    return station ? { station, name: t(`verse.station.${station.kind}.name`), action: t(`verse.station.${station.kind}.action`) } : null;
  }, [hover, deck, t]);
  const card = useMemo<CrewCardInfo | null>(() => {
    const m = selected ? life.crew.get(selected) : undefined;
    if (!m) return null;
    const rank = rankForLevel(life.levels.get(m.id) ?? 1);
    const placement = life.placements.get(m.id);
    return {
      id: m.id, name: m.name, rankId: rank.id, rank: t(`verse.ranks.rank.${rank.id}`), status: t(`verse.state.${m.status}`), statusKey: m.status,
      post: t(`verse.post.${placement?.venue ?? "elsewhere"}`), accent: life.looks.get(m.id)?.accent ?? null,
      technician: m.role === "technician", here: !!placement,
    };
  }, [selected, life.crew, life.levels, life.placements, life.looks, t]);
  const counts = useMemo(() => {
    let working = 0, waiting = 0;
    for (const s of deckStatuses.values()) { if (s === "working") working++; if (s === "waiting" || s === "error") waiting++; }
    return { aboard: life.placements.size, working, waiting };
  }, [deckStatuses, life.placements]);
  const lead = useMemo(() => [...life.agents.values()].find((a) => a.tier === "lead"), [life.agents]);
  const officers = useMemo(() => [...life.agents.values()].filter((a) => a.tier !== "lead").map((a) => ({ agentId: a.agentId, name: a.name })), [life.agents]);

  const onPlateReady = useCallback((shown: Deck) => setShownDeck(shown), []);
  const onFailure = useCallback((error: Error) => { console.error("Verse deck failed", error); setFailure(error); }, []);
  const problem = failure ?? deckState.error;
  const fallback = <div className="verse-fallback" role="status">{chunkReady ? t("verse.stage.unavailable") : null}</div>;

  return (
    <div ref={hostRef} className="verse-stage" data-compact={compact} tabIndex={-1} aria-label={chunkReady ? t("verse.stage.title") : undefined}>
      {!webgl ? fallback : (
        <RenderBoundary key={generation} fallback={fallback}>
          <div ref={surfaceRef} className="verse-surface">
            <CanvasActivity.Provider value={awake}>
              <Canvas
                key={generation}
                orthographic
                camera={{ manual: true, near: 1, far: CAMERA_FAR }}
                frameloop={awake ? "always" : "never"}
                dpr={[0.25, 2]}
                gl={{ antialias: true, alpha: false, stencil: false, powerPreference: "high-performance" }}
                onCreated={({ gl }) => gl.setClearColor(0x050607, 1)}
              >
                {deck && !problem && (
                  <DeckBackdrop runtime={runtime} deck={deck} debug={debug} awake={awake} onReady={onPlateReady} onError={onFailure}>
                    <DeckEnvironment url={deck.envUrl} />
                    {library && <ActorsLayer runtime={runtime} deck={deck} library={library} cast={cast} commanderId={COMMANDER_ID} reduced={reduced} saluteAt={saluteAt} />}
                    <ScreensLayer deck={deck} faces={faces} />
                    <HoloLayer sockets={holos} lit={litHolos} reduced={reduced} />
                    <LightsLayer deck={deck} alarm={alarm} reduced={reduced} />
                    <BeaconsLayer runtime={runtime} statuses={deckStatuses} reduced={reduced} />
                    {import.meta.env.DEV && debug && <DebugOverlay deck={deck} />}
                  </DeckBackdrop>
                )}
              </Canvas>
            </CanvasActivity.Provider>
          </div>
        </RenderBoundary>
      )}
      {chunkReady && (
        <div className="verse-hud">
          <FloatingLabels runtime={runtime} plates={plates} station={hoveredStation} deck={deck} />
          <DeckTitle deck={deckId} t={t} counts={counts} rankCard={<RankCard compact={compact} />} />
          <Toolbar t={t} onLift={() => setPanel("lift")} onCommander={() => focusOn(COMMANDER_ID)} onHelp={() => say(t("verse.stage.help"))} />
          {(!plateReady || problem) && (
            <div className="verse-status" role="status" data-tone={problem ? "error" : "quiet"}>
              {problem ? t("verse.stage.deck_missing") : t("verse.stage.loading")}
            </div>
          )}
          {card && (
            <CrewCard info={card} t={t} onOpen={() => openCrew(card.id)} onShow={() => focusOn(card.id)} onClose={() => setSelected(null)}
              onWalk={() => {
                const pose = runtime.poses.get(card.id);
                if (pose && deck) { const at = nearestWalkable(deck.nav, { x: pose.x, z: pose.z + 0.9 }, 3); if (at) walkTo(at.x, at.z); }
              }} />
          )}
          {notice && <div className="verse-panel verse-notice" role="status">{notice}</div>}
          {panel === "lift" && <LiftPanel current={deckId} t={t} onRide={rideTo} onClose={() => setPanel(null)} />}
          {panel === "launcher" && (
            <LauncherPanel t={t} say={say} onClose={() => setPanel(null)} onOpenIde={() => { setPanel(null); useEventStore.getState().setActiveSection("agentic-ide"); }} />
          )}
          {panel === "games" && <SimulatorPanel t={t} onClose={() => setPanel(null)} />}
          <RanksOverlay active={awake} crew={officers} companionName={lead?.name} />
          {import.meta.env.DEV && <StatsReadout runtime={runtime} />}
          <div className="verse-doors" data-shut={doors !== null} aria-hidden><i /><i /></div>
        </div>
      )}
    </div>
  );
}
