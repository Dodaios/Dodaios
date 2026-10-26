/**
 * Agents > Dodaios Verse: the interior of the capital ship, seen from above.
 *
 * Each deck is a photograph rendered offline (the plate); the stage puts the
 * live crew, their screens and the ship's small lights into it with a camera
 * that matches the photograph exactly (BRIEF §3). Decks exported as eye-level
 * scenes (docs/verse/realtime.md) are walked on the full-size stage in third
 * person (over the commander's shoulder) or first person (through their
 * eyes), both with shooter mouse look; the plate stays the bird's-eye view
 * and the IDE panel's view. V cycles the three views, 1/2/3 pick one, and
 * the wheel hands third person over to first. The person is the commanding
 * officer, steered in third or first person (the keys walk them, the camera
 * follows) or sent by clicks from a bird's-eye view; the agents are officers
 * at the bridge consoles; coding panes are technicians at engineering's
 * terminals; stations turn places of the ship into the app's actions.
 */
import { Component, useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
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
import { RealtimeBackdrop } from "./engine/realtime/RealtimeBackdrop";
import { attachOrbitInput } from "./engine/realtime/orbitInput";
import { hasMouseLook, releaseMouseLook, requestMouseLook } from "./engine/realtime/mouseLook";
import { controlModeOf, cycleView, isShooterView, resolveView, viewForKey, type Person, type VerseView } from "./engine/realtime/viewMode";
import { eyePick } from "./engine/realtime/eyePick";
import { useViewSettings } from "./engine/realtime/viewSettings";
import { eyeCapable as canWalkAtEyeLevel } from "./engine/stageView";
import { pickBody, pickStation } from "./engine/picking";
import { worldToPlate } from "./engine/plateMath";
import { screenToPlate } from "./engine/view";
import type { PanKey } from "./engine/viewController";
import { ActorsLayer } from "./actors/ActorsLayer";
import { useCharacterLibrary } from "./actors/useCharacterLibrary";
import type { Look } from "./actors/look";
import { buildCast, COMMANDER_ID, type CommanderState } from "./life/cast";
import { commanderTarget, type CommanderOrders } from "./life/commander";
import { stationWithin } from "./life/control";
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
import { ViewSettingsPanel } from "./hud/ViewSettingsPanel";
import { StageRuntime } from "./runtime";
import { REACTOR_ARENA } from "./combat/arenaReactor";
import { DuelController, type DuelDifficulty } from "./duel/duelController";
import { attachDuelInput } from "./duel/duelInput";
import { DuelLayer } from "./duel/DuelLayer";
import { DuelHud } from "./hud/DuelHud";
import { DuelPanel } from "./hud/DuelPanel";
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
/** The help text is long: it stays up long enough to read. */
const HELP_MS = 15_000;
const DOORS_MS = 460;
const DOORS_GIVE_UP_MS = 5000;

type Hover = { kind: "crew"; id: string } | { kind: "station"; id: string } | null;
type Panel = "lift" | "launcher" | "games" | "settings" | "duel" | null;

/** The deck the duel arena overlays (Reactor Engineering). */
const ARENA_DECK = REACTOR_ARENA.deck as DeckId;

/**
 * Testing switch: `localStorage["verse.duel.anyDeck"] = "1"` starts a duel on whatever deck is loaded (the arena's
 * coordinates are engineering's), for checking the duel on a deck whose eye-level export is not there yet.
 */
function duelAnyDeck(): boolean {
  try {
    return window.localStorage.getItem("verse.duel.anyDeck") === "1";
  } catch {
    return false;
  }
}

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
  // The duel (docs/verse/combat.md): one controller per stage; its phase drives the HUD and the input.
  const duel = useMemo(() => new DuelController(), []);
  useEffect(() => () => duel.dispose(), [duel]);
  const duelPhase = useSyncExternalStore(duel.subscribe, duel.getPhase);
  /** Stage actions the duel input calls back into (filled once the stage's callbacks exist). */
  const duelActions = useRef({ lockAim: () => undefined as void });
  const dueling = duelPhase !== "off";
  runtime.duelActive = dueling;

  const [deckId, setDeckId] = useState<DeckId>(initialDeck ?? "bridge");
  const deckState = useDeck(deckId);
  const deck = deckState.deck;
  /** The deck whose plate is on screen. */
  const [shownDeck, setShownDeck] = useState<Deck | null>(null);
  /** The deck whose eye-level scene is loaded, and the decks whose eye-level scene failed here (they fall back to the plate). */
  const [eyeDeck, setEyeDeck] = useState<Deck | null>(null);
  const [eyeFailed, setEyeFailed] = useState<ReadonlySet<string>>(() => new Set());
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
    // The frame numbers are read by QA runs against built bundles too; the handle with the stage itself stays development-only.
    Object.assign(window, { __verseStats: runtime.stats });
    if (!import.meta.env.DEV) return;
    const handle = {
      runtime,
      camera: runtime.view,
      actors: runtime.poses,
      setDuty: useDevDuty.getState().setDuty,
      get life() { return lifeRef.current; },
    };
    Object.assign(window, { __verse: handle });
  }, [runtime]);

  // The IDE tab always opens on its deck; another host keeps where the person last was.
  useEffect(() => { if (awake && initialDeck) setDeckId(initialDeck); }, [awake, initialDeck]);

  // A new deck: frame where the commander comes aboard (out of the lift after a ride); third person closes in on them once they stand there.
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
    runtime.control.reframe = true;
  }, [deck, runtime]);

  // The view (viewMode.ts): bird's-eye (the keys pan over the whole deck), third or first person (the keys walk the
  // commander, the camera follows). The person's last choice is kept in this browser.
  const chosenView = useViewSettings((s) => s.view);
  // The full-size stage walks an exported deck at eye level; the plate stays the bird's-eye view and the compact view.
  const eyeCapable = !!deck && canWalkAtEyeLevel({ compact, realtime: !!deck.realtime, failed: eyeFailed.has(deck.id) });
  const view = resolveView(chosenView, eyeCapable);
  const mode = controlModeOf(view);
  const eyeOn = eyeCapable && mode === "follow";
  /** Shooter mouse look (pointer lock, a centre crosshair): third and first person at eye level. */
  const shooter = isShooterView(view, eyeCapable);
  const plateReady = !!deck && (eyeOn ? eyeDeck === deck : shownDeck === deck);
  const viewRef = useRef(view);
  viewRef.current = view;
  // The view on screen steers the commander (or the map) and picks the eye-level camera's person.
  useEffect(() => {
    const control = runtime.control;
    const next = controlModeOf(view);
    if (control.mode !== next) {
      control.mode = next;
      control.clearKeys();
      runtime.view.clearKeys();
      if (next === "overview") runtime.view.overview();
      else control.reframe = true;
    }
    if (view !== "overview") runtime.shoulder.setPerson(view);
  }, [view, runtime]);
  const chooseView = useCallback((next: VerseView) => useViewSettings.getState().set({ view: next }), []);

  // The person's mouse settings turn the eye-level camera; the quality goes to its renderer.
  const sensitivity = useViewSettings((s) => s.sensitivity);
  const invertY = useViewSettings((s) => s.invertY);
  const quality = useViewSettings((s) => s.quality);
  const fovThird = useViewSettings((s) => s.fovThird);
  const fovFirst = useViewSettings((s) => s.fovFirst);
  useEffect(() => {
    runtime.shoulder.sensitivity = sensitivity;
    runtime.shoulder.invertY = invertY;
    runtime.shoulder.fovThird = fovThird;
    runtime.shoulder.fovFirst = fovFirst;
    duel.camera.sensitivity = sensitivity;
    duel.camera.invertY = invertY;
  }, [runtime, duel, sensitivity, invertY, fovThird, fovFirst]);

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
  const say = useCallback((text: string, ms: number = NOTICE_MS) => {
    setNotice(text);
    later(() => setNotice((n) => (n === text ? null : n)), ms);
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

  // Choosing a view (the switch, V, 1/2/3) is a click or a key press: third and first person take the mouse for
  // shooter look at once, the bird's-eye view gives it back.
  const showView = useCallback((wanted: VerseView) => {
    const next = resolveView(wanted, eyeCapable);
    if (next !== viewRef.current) {
      chooseView(next);
      say(t(next === "overview" ? "verse.notice.view_overview" : !eyeCapable ? "verse.notice.view_follow" : next === "first" ? "verse.notice.view_first" : "verse.notice.view_follow_eye"));
    }
    const el = surfaceRef.current;
    if (!el || runtime.duelActive) return;
    if (isShooterView(next, eyeCapable)) requestMouseLook(el);
    else releaseMouseLook(el);
  }, [eyeCapable, chooseView, say, t, runtime]);
  const cycle = useCallback(() => showView(cycleView(viewRef.current, eyeCapable)), [showView, eyeCapable]);
  // The wheel pushed third person into first (or pulled first back out): the switch follows, the mouse stays as it is.
  const zoomEye = useCallback((factor: number) => {
    const changed: Person | null = runtime.shoulder.zoom(factor);
    if (changed) chooseView(changed);
  }, [runtime, chooseView]);

  // The station within the commander's reach, the one in front preferred: where the eye-level camera looks, else where
  // the commander faces.
  // The duel terminals: the four consoles on the reactor's control ring (engineering only, or anywhere for testing).
  const duelTerminals = useMemo<Station[]>(() => {
    if (!deck || (deck.id !== ARENA_DECK && !duelAnyDeck())) return [];
    const floor = deck.rooms.find((r) => r.id === REACTOR_ARENA.room)?.floorY ?? 0;
    return REACTOR_ARENA.terminals.map((tm) => ({ id: `duel:${tm.id}`, kind: "games" as const, room: REACTOR_ARENA.room, x: tm.x, y: floor, z: tm.z, sockets: {} }));
  }, [deck]);
  const stationAtHand = useCallback((): Station | null => {
    const d = runtime.deck;
    const pose = runtime.poses.get(COMMANDER_ID);
    if (!d || !pose) return null;
    const facing = runtime.eye ? runtime.shoulder.forward() : { x: Math.sin(pose.yaw), z: Math.cos(pose.yaw) };
    return stationWithin(duelTerminals.length ? [...d.stations, ...duelTerminals] : d.stations, pose.x, pose.z, undefined, facing);
  }, [runtime, duelTerminals]);

  // The use key works the station at hand.
  const workNearStation = useCallback(() => {
    const station = stationAtHand();
    if (station?.id.startsWith("duel:")) { setPanel("duel"); return; }
    if (station) activateStation(station);
  }, [stationAtHand, activateStation]);

  // Third person: which station is within the commander's reach (checked a few times a second), offered with its key.
  const [nearStation, setNearStation] = useState<string | null>(null);
  useEffect(() => {
    if (!awake) return;
    let last = 0;
    const check = () => {
      const now = performance.now();
      if (now - last < 200) return;
      last = now;
      const id = runtime.control.mode === "follow" && !runtime.duelActive ? stationAtHand()?.id ?? null : null;
      setNearStation((prev) => (prev === id ? prev : id));
    };
    runtime.afterFrame.add(check);
    return () => { runtime.afterFrame.delete(check); };
  }, [awake, runtime, stationAtHand]);

  // Pointer: hover labels, taps on crew, stations and the floor.
  const eyeHit = useCallback((sx: number, sy: number) => {
    const d = runtime.deck;
    const ray = runtime.ray(sx, sy);
    if (!d || !ray || !runtime.eye) return null;
    return eyePick(ray.ray, d.stations, runtime.poses.values(), (id) => life.crew.has(id), runtime.eye.collider);
  }, [runtime, life.crew]);
  const hit = useCallback((sx: number, sy: number): Hover => {
    const d = runtime.deck;
    if (!d) return null;
    if (runtime.eye) {
      const h = eyeHit(sx, sy);
      return h && h.kind !== "floor" ? h : null;
    }
    const p = screenToPlate(runtime.view.current, runtime.view.vp, sx, sy);
    const body = pickBody(d.camera, runtime.poses.values(), p, (id) => life.crew.has(id));
    if (body) return { kind: "crew", id: body };
    const station = pickStation(d, p);
    return station ? { kind: "station", id: station.id } : null;
  }, [runtime, life.crew, eyeHit]);

  const handlers = useRef({
    hover: (_x: number, _y: number) => undefined as void,
    tap: (_x: number, _y: number) => undefined as void,
    aim: (_x: number, _y: number) => false as boolean,
  });
  handlers.current.hover = (sx, sy) => {
    const h = hit(sx, sy);
    setHover((prev) => (sameHover(prev, h) ? prev : h));
    if (surfaceRef.current) surfaceRef.current.dataset.cursor = h ? "pointer" : "";
  };
  // Shooter look: the left button (or E) works what the centre crosshair is on, a crew member or a station; never the
  // floor (that would send the commander off with every press of the button). Returns whether something was there.
  handlers.current.aim = (sx, sy) => {
    const d = runtime.deck;
    if (!d) return false;
    const h = hit(sx, sy);
    if (h?.kind === "crew") {
      if (selected === h.id) openCrew(h.id);
      else setSelected(h.id);
      return true;
    }
    if (h?.kind === "station") {
      const station = d.stations.find((s) => s.id === h.id);
      if (station) activateStation(station);
      return !!station;
    }
    return false;
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
    if (runtime.eye) {
      const at = eyeHit(sx, sy);
      const floor = at?.kind === "floor" ? nearestWalkable(d.nav, { x: at.x, z: at.z }, 1.2) : null;
      if (floor) walkTo(floor.x, floor.z);
      return;
    }
    const p = screenToPlate(runtime.view.current, runtime.view.vp, sx, sy);
    const floor = pickFloor(d.camera, d.nav, p.u, p.v);
    if (floor) walkTo(floor.x, floor.z);
  };

  useEffect(() => {
    const el = surfaceRef.current;
    if (!el) return;
    // A duel: the mouse aims and fires, the keys fight (duel/duelInput.ts).
    if (dueling) {
      return attachDuelInput(el, duel.input, {
        look: (dx, dy) => duel.camera.look(dx, dy),
        escape: () => {
          if (document.pointerLockElement === el) document.exitPointerLock?.();
          duel.escape();
        },
        relock: () => duelActions.current.lockAim(),
        live: () => duel.live,
      });
    }
    // Third and first person: shooter mouse look (a click takes the mouse), the wheel zooms and hands over between them.
    if (eyeOn) {
      return attachOrbitInput(el, runtime.shoulder, {
        tap: (x, y) => handlers.current.tap(x, y),
        hover: (x, y) => handlers.current.hover(x, y),
        leave: () => setHover(null),
        moved: () => setHover(null),
        aim: (x, y) => { handlers.current.aim(x, y); },
        capture: () => {
          hostRef.current?.focus({ preventScroll: true });
          requestMouseLook(el);
        },
        zoom: (factor) => keyActions.current.zoomEye(factor),
      });
    }
    return attachPointerInput(el, runtime.view, {
      tap: (x, y) => handlers.current.tap(x, y),
      hover: (x, y) => handlers.current.hover(x, y),
      leave: () => setHover(null),
      moved: () => setHover(null),
      dragged: () => { runtime.control.looking = true; },
      // Third person zooms around the commander, so the wheel never loses them off screen.
      zoomAnchor: () => {
        if (runtime.control.mode !== "follow" || runtime.control.looking) return null;
        const pose = runtime.poses.get(COMMANDER_ID);
        return pose ? runtime.toScreen(pose.x, pose.y + pose.height * 0.5, pose.z) : null;
      },
    });
  }, [runtime, webgl, generation, eyeOn, dueling, duel]);

  // Opening the full-size stage hands it the keyboard, so the movement keys work at once (unless someone is typing;
  // the IDE's side panel never takes focus from the terminal beside it).
  useEffect(() => {
    if (!awake || compact) return;
    const focused = document.activeElement;
    if (typesText(focused) || hostRef.current?.contains(focused)) return;
    hostRef.current?.focus({ preventScroll: true });
  }, [awake, compact]);

  // Keyboard: WASD/arrows walk the commander (third person) or pan (bird's-eye), Shift hurries, V switches the view,
  // E works the station at hand, +/- zoom, Escape closes, F9 the alignment overlay (development).
  const lockPointer = useCallback(() => {
    const el = surfaceRef.current;
    if (!el || !runtime.eye) return;
    if (hasMouseLook(el)) { releaseMouseLook(el); return; }
    requestMouseLook(el);
    say(t("verse.notice.mouse_look"));
  }, [runtime, say, t]);
  // E: what the crosshair is on (at eye level), else the station within reach.
  const interact = useCallback(() => {
    const el = surfaceRef.current;
    if (runtime.eye && el && handlers.current.aim(el.clientWidth / 2, el.clientHeight / 2)) return;
    workNearStation();
  }, [runtime, workNearStation]);
  // The bird's-eye view (or a deck without an eye-level scene) gives the mouse back; so does leaving the stage.
  useEffect(() => { if (!eyeOn && !dueling) releaseMouseLook(surfaceRef.current); }, [eyeOn, dueling]);
  useEffect(() => {
    const surface = surfaceRef.current;
    return () => releaseMouseLook(surface);
  }, []);
  // Mouse look is on while the surface holds the pointer lock: a reticle marks what a click works.
  const [locked, setLocked] = useState(false);
  useEffect(() => {
    const changed = () => {
      const now = !!surfaceRef.current && document.pointerLockElement === surfaceRef.current;
      setLocked(now);
      // The browser released the mouse (Escape): the duel pauses rather than playing on without aim.
      if (now) duel.hadLock = true;
      else if (duel.phase === "running" && duel.hadLock) duel.pause();
    };
    document.addEventListener("pointerlockchange", changed);
    return () => document.removeEventListener("pointerlockchange", changed);
  }, [duel]);
  // A dialog needs the pointer: opening one ends mouse look.
  useEffect(() => {
    if (panel && surfaceRef.current && document.pointerLockElement === surfaceRef.current) document.exitPointerLock();
  }, [panel]);
  const keyActions = useRef({ cycle, showView, interact, lockPointer, zoomEye });
  keyActions.current = { cycle, showView, interact, lockPointer, zoomEye };
  /** What Escape closes first: a selected crew member or an open panel. */
  const closable = useRef(false);
  closable.current = selected !== null || panel !== null;
  useEffect(() => {
    if (!awake) return;
    const owns = (e: KeyboardEvent) => {
      if (typesText(e.target) || e.ctrlKey || e.metaKey || e.altKey) return false;
      const focused = document.activeElement;
      return !focused || focused === document.body || !!hostRef.current?.contains(focused);
    };
    // Escape ends mouse look, or closes the crew card or a panel, and nothing else: claimed before the Agents view sees
    // it (it would leave the ship). With nothing open it goes through and leaves as before.
    const escape = (e: KeyboardEvent) => {
      if (e.code !== "Escape" || runtime.duelActive) return;
      const surface = surfaceRef.current;
      const looking = !!surface && document.pointerLockElement === surface;
      if (!(looking || closable.current) || !owns(e)) return;
      e.preventDefault();
      if (looking) { document.exitPointerLock?.(); return; }
      setPanel(null);
      setSelected(null);
    };
    const down = (e: KeyboardEvent) => {
      if (runtime.duelActive) return;
      if (e.key === "Shift") runtime.control.run = true;
      if (!owns(e)) return;
      const key = PAN_KEYS[e.code];
      const v = runtime.view;
      if (key) {
        e.preventDefault();
        if (runtime.control.mode === "follow") runtime.control.setKey(key, true, e.shiftKey);
        else v.setKey(key, true, e.shiftKey);
        return;
      }
      const direct = e.repeat ? null : viewForKey(e.code);
      if (direct) { e.preventDefault(); keyActions.current.showView(direct); return; }
      if (e.code === "Equal" || e.code === "NumpadAdd") { if (runtime.eye) keyActions.current.zoomEye(0.85); else v.zoomAt(v.vp.width / 2, v.vp.height / 2, 1.25); }
      else if (e.code === "Minus" || e.code === "NumpadSubtract") { if (runtime.eye) keyActions.current.zoomEye(1.18); else v.zoomAt(v.vp.width / 2, v.vp.height / 2, 0.8); }
      else if (e.code === "KeyV" && !e.repeat) keyActions.current.cycle();
      else if (e.code === "KeyE" && !e.repeat) keyActions.current.interact();
      else if (e.code === "KeyL" && !e.repeat) keyActions.current.lockPointer();
      else if (e.code === "F9" && import.meta.env.DEV) setDebug((d) => !d);
    };
    const up = (e: KeyboardEvent) => {
      if (e.key === "Shift") runtime.control.run = false;
      const key = PAN_KEYS[e.code];
      if (!key) return;
      runtime.view.setKey(key, false, e.shiftKey);
      runtime.control.setKey(key, false, e.shiftKey);
    };
    const blur = () => { runtime.view.clearKeys(); runtime.control.clearKeys(); };
    window.addEventListener("keydown", escape, true);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", escape, true);
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
      blur();
    };
  }, [awake, runtime]);

  // The duel: start it (riding down to engineering first when the commander is elsewhere), lock the mouse for aiming,
  // pause when the stage goes out of sight, and give the commander back to the deck where the duel ended.
  const [duelChoice, setDuelChoice] = useState<DuelDifficulty>("hard");
  const [pendingDuel, setPendingDuel] = useState<DuelDifficulty | null>(null);
  // The duel aims with the same mouse look as third and first person.
  duelActions.current.lockAim = () => {
    const el = surfaceRef.current;
    if (el) requestMouseLook(el);
  };
  const beginDuel = useCallback((difficulty: DuelDifficulty) => {
    const d = runtime.deck;
    if (!d) return;
    // The duel is fought over the shoulder (its own camera); from the bird's-eye view the stage goes to third person.
    if (viewRef.current === "overview") chooseView("third");
    runtime.control.mode = "follow";
    runtime.control.clearKeys();
    duel.floorY = d.rooms.find((r) => r.id === REACTOR_ARENA.room)?.floorY ?? 0;
    runtime.duelArea = REACTOR_ARENA.bounds;
    setSelected(null);
    setHover(null);
    duel.start(difficulty);
  }, [runtime, duel, chooseView]);
  const startDuel = useCallback((difficulty: DuelDifficulty) => {
    setPanel(null);
    setDuelChoice(difficulty);
    if (deckId !== ARENA_DECK && !duelAnyDeck()) {
      // Down to Reactor Engineering first; the match starts once its eye-level scene is on screen.
      setPendingDuel(difficulty);
      rideTo(ARENA_DECK);
      return;
    }
    if (!eyeCapable) { say(t("verse.duel.notice.needs_eye")); return; }
    beginDuel(difficulty);
    duelActions.current.lockAim();
  }, [deckId, eyeCapable, rideTo, beginDuel, say, t]);
  useEffect(() => {
    if (!pendingDuel || doors || !deck || deck.id !== ARENA_DECK) return;
    if (!eyeCapable) { setPendingDuel(null); say(t("verse.duel.notice.needs_eye")); return; }
    if (eyeDeck !== deck) return;
    setPendingDuel(null);
    beginDuel(pendingDuel);
  }, [pendingDuel, doors, deck, eyeCapable, eyeDeck, beginDuel, say, t]);
  useEffect(() => {
    duel.onExit = (at) => {
      if (surfaceRef.current && document.pointerLockElement === surfaceRef.current) document.exitPointerLock?.();
      if (at) runtime.placeCommander = { x: at.x, z: at.z, yaw: at.yaw };
      runtime.duelArea = null;
      runtime.control.clearKeys();
      runtime.control.reframe = true;
    };
    return () => { duel.onExit = null; };
  }, [duel, runtime]);
  // The pause and result screens need the pointer; a hidden stage pauses the match.
  useEffect(() => {
    if (duelPhase !== "paused" && duelPhase !== "result") return;
    if (surfaceRef.current && document.pointerLockElement === surfaceRef.current) document.exitPointerLock?.();
  }, [duelPhase]);
  useEffect(() => { if (!awake && duel.phase === "running") duel.pause(); }, [awake, duel]);
  const leaveDuel = useCallback(() => {
    const midMatch = duel.phase === "running" || duel.phase === "paused";
    duel.leave();
    if (midMatch) say(t("verse.duel.notice.left"));
  }, [duel, say, t]);
  // QA hook (built bundles too, like __verseStats): start a duel on the deck on screen and drive it without a mouse.
  const beginRef = useRef(beginDuel);
  beginRef.current = beginDuel;
  useEffect(() => {
    const hook = {
      start: (difficulty: DuelDifficulty = "hard") => beginRef.current(difficulty),
      leave: () => duel.leave(),
      /** Put the commander somewhere on the deck (a ring console, to check the start prompt). */
      place: (x: number, z: number, yaw = 0) => { runtime.placeCommander = { x, z, yaw }; runtime.control.reframe = true; },
      look: (dx: number, dy: number) => duel.camera.look(dx, dy),
      hold: (c: Parameters<DuelController["hold"]>[0]) => duel.hold(c),
      press: (name: "dodge" | "vent") => duel.press(name),
      state: () => ({ phase: duel.phase, hud: duel.hud(), view: duel.view, result: duel.result, aim: duel.aimTarget, pose: duel.pose }),
    };
    Object.assign(window, { __verseDuel: hook });
    return () => { if ((window as unknown as { __verseDuel?: unknown }).__verseDuel === hook) delete (window as unknown as { __verseDuel?: unknown }).__verseDuel; };
  }, [duel, runtime]);

  // QA hook (built bundles too): switch views, look and zoom without a mouse (headless browsers cannot lock the pointer).
  const viewActions = useRef({ showView, zoomEye });
  viewActions.current = { showView, zoomEye };
  useEffect(() => {
    const hook = {
      set: (v: VerseView) => viewActions.current.showView(v),
      look: (dx: number, dy: number) => runtime.shoulder.look(dx, dy, true),
      zoom: (factor: number) => viewActions.current.zoomEye(factor),
      state: () => ({
        view: viewRef.current, person: runtime.shoulder.person, distance: runtime.shoulder.distance, actual: runtime.shoulder.actual,
        firstShare: runtime.shoulder.firstShare, hfov: runtime.shoulder.hfov(), yaw: runtime.shoulder.yaw, pitch: runtime.shoulder.pitch,
        commanderHidden: runtime.commanderHidden, locked: hasMouseLook(surfaceRef.current),
      }),
    };
    Object.assign(window, { __verseView: hook });
    return () => { if ((window as unknown as { __verseView?: unknown }).__verseView === hook) delete (window as unknown as { __verseView?: unknown }).__verseView; };
  }, [runtime]);

  const focusOn = useCallback((id: string) => {
    const pose = runtime.poses.get(id);
    const d = runtime.deck;
    if (!pose || !d) return;
    const me = runtime.poses.get(COMMANDER_ID);
    if (runtime.eye && me) {
      runtime.shoulder.faceToward(me.x, me.z, pose.x, pose.z);
      return;
    }
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
  // The station under the pointer, else (third person) the one within the commander's reach, with the key that works it.
  const labelledStation = useMemo(() => {
    if (!deck) return null;
    const pointed = hover?.kind === "station";
    const id = pointed ? hover.id : nearStation;
    const terminal = id ? duelTerminals.find((s) => s.id === id) : undefined;
    if (terminal) return { station: terminal, name: t("verse.duel.terminal"), action: t("verse.duel.start"), key: "E" };
    const station = id ? deck.stations.find((s) => s.id === id) : undefined;
    return station ? { station, name: t(`verse.station.${station.kind}.name`), action: t(`verse.station.${station.kind}.action`), key: pointed ? null : "E" } : null;
  }, [hover, nearStation, deck, t, duelTerminals]);
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
  const onEyeReady = useCallback((shown: Deck) => setEyeDeck(shown), []);
  // A deck whose eye-level scene cannot load is still walked on its plate.
  const onEyeFailure = useCallback((error: Error) => {
    console.error("Verse eye-level view failed; showing the plate", error);
    const failed = runtime.deck?.id;
    if (failed) setEyeFailed((prev) => (prev.has(failed) ? prev : new Set(prev).add(failed)));
  }, [runtime]);
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
                {deck && !problem && eyeCapable && (
                  <RealtimeBackdrop runtime={runtime} deck={deck} active={eyeOn} commanderId={COMMANDER_ID} quality={quality} onReady={onEyeReady} onError={onEyeFailure} />
                )}
                {deck && !problem && eyeCapable && dueling && (
                  <DuelLayer runtime={runtime} controller={duel} deck={deck} library={library} commanderId={COMMANDER_ID} commanderLook={commanderLook} />
                )}
                {deck && !problem && (
                  <DeckBackdrop runtime={runtime} deck={deck} debug={debug} awake={awake} active={!eyeOn} onReady={onPlateReady} onError={onFailure}>
                    <DeckEnvironment url={deck.envUrl} />
                    {library && <ActorsLayer runtime={runtime} deck={deck} library={library} cast={cast} commanderId={COMMANDER_ID} reduced={reduced} saluteAt={saluteAt} />}
                    <ScreensLayer deck={deck} faces={faces} />
                    <HoloLayer sockets={holos} lit={litHolos} reduced={reduced} />
                    <LightsLayer deck={deck} alarm={alarm} reduced={reduced} runtime={runtime} />
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
          {!dueling && <FloatingLabels runtime={runtime} plates={plates} station={labelledStation} deck={deck} />}
          {!dueling && <DeckTitle deck={deckId} t={t} counts={counts} rankCard={<RankCard compact={compact} />} />}
          {!dueling && <Toolbar
            t={t}
            view={view}
            firstAvailable={eyeCapable}
            onView={showView}
            onLift={() => setPanel("lift")}
            onCommander={() => { if (runtime.control.mode === "follow") runtime.control.reframe = true; else focusOn(COMMANDER_ID); }}
            onSettings={eyeCapable ? () => setPanel("settings") : undefined}
            onDuel={compact ? undefined : () => setPanel("duel")}
            onHelp={() => say(t(eyeOn ? "verse.stage.help_eye" : "verse.stage.help"), HELP_MS)}
          />}
          {shooter && !dueling && <div className="verse-reticle" data-locked={locked} data-on={hover ? "" : undefined} aria-hidden />}
          {shooter && !dueling && !locked && !panel && plateReady && (
            <div className="verse-look-hint" aria-hidden>{t("verse.tools.click_to_look")}</div>
          )}
          {dueling && (
            <DuelHud runtime={runtime} controller={duel} phase={duelPhase} locked={locked} t={t}
              onResume={() => { duel.resume(); duelActions.current.lockAim(); }}
              onLeave={leaveDuel}
              onRematch={() => { duel.rematch(); duelActions.current.lockAim(); }} />
          )}
          {(!plateReady || problem) && (
            <div className="verse-status" role="status" data-tone={problem ? "error" : "quiet"}>
              {problem ? t("verse.stage.deck_missing") : t("verse.stage.loading")}
            </div>
          )}
          {card && !dueling && (
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
          {panel === "duel" && !dueling && (
            <DuelPanel t={t} ride={deckId !== ARENA_DECK && !duelAnyDeck()} last={duelChoice} onStart={startDuel} onClose={() => setPanel(null)} />
          )}
          {panel === "settings" && <ViewSettingsPanel t={t} tier={eyeOn ? runtime.stats.tier : ""} onClose={() => setPanel(null)} />}
          <RanksOverlay active={awake} crew={officers} companionName={lead?.name} />
          {import.meta.env.DEV && <StatsReadout runtime={runtime} />}
          <div className="verse-doors" data-shut={doors !== null} aria-hidden><i /><i /></div>
        </div>
      )}
    </div>
  );
}
