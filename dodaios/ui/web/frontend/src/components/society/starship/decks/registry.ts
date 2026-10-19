/**
 * The decks of the ship and how each one is built. A deck module registers
 * its plan builder and, when it needs them, a scene of its own (things that
 * move or change beyond the shared kit), its own station behaviour and a DOM
 * panel its stations open. The stage never needs editing for a new deck.
 */
import type { ComponentType } from "react";
import type { SocietyAgent } from "../../data";
import type { PaneOccupant } from "../../crewFeeds/codingFloor";
import type { CrewInput, DeckId, DeckPlan, Station, TeamInput } from "../plan/types";

export interface DeckInput {
  crew: readonly CrewInput[];
  teams: readonly TeamInput[];
  /** Engineering: every coding pane of the IDE (its `agent` is the pane projected into a crew member). */
  panes: readonly PaneOccupant[];
}

/** What a deck's stations and panels may do; the stage implements it. */
export interface ShipActions {
  t: (key: string) => string;
  /** One short line in the HUD. */
  say: (text: string) => void;
  /** Open a Jarvis agent's chat (or a pane's command panel on engineering). */
  openAgent: (agentId: string) => void;
  openLedger: () => void;
  createAgent: () => void;
  openGroup: (groupId: string) => void;
  /** Navigate the app to a section ("agentic-ide", "agents", …). */
  openSection: (section: string) => void;
  /** Ride the turbolift to another deck (with the doors). */
  ride: (deck: DeckId) => void;
  /** Seat the captain (the captain's chair); null stands up. */
  sit: (seat: { x: number; z: number; yaw: number; seatY: number } | null) => void;
  /** Open this deck's panel for a station (rendered by the module's `Panel`). */
  openPanel: (stationId: string) => void;
  closePanel: () => void;
  /** Report a small action to the level system (metered on the server). */
  reportAction: (action: string, ref?: string) => void;
}

export interface DeckSceneProps {
  plan: DeckPlan;
  reduced: boolean;
  quality: "high" | "low";
  awake: boolean;
  /** The deck's crew (agents, or panes on engineering) by id. */
  agents: ReadonlyMap<string, SocietyAgent>;
  panes: readonly PaneOccupant[];
  actions: ShipActions;
}

export interface DeckPanelProps {
  plan: DeckPlan;
  /** The station whose panel is open. */
  station: Station;
  actions: ShipActions;
  agents: ReadonlyMap<string, SocietyAgent>;
  panes: readonly PaneOccupant[];
}

export interface DeckModule {
  id: DeckId;
  /** Who lives here: the Jarvis agents, the coding panes, or nobody (the captain and the pet only). */
  population: "agents" | "panes" | "none";
  build: (input: DeckInput) => DeckPlan;
  Scene?: ComponentType<DeckSceneProps>;
  /**
   * Handle a station of this deck. Return true when handled; the stage's
   * shared behaviour (transporter, turbolift, divisions, mess) covers the rest.
   */
  useStation?: (station: Station, plan: DeckPlan, actions: ShipActions, far: boolean) => boolean;
  Panel?: ComponentType<DeckPanelProps>;
  /** The prompt's name for a station of this deck; undefined = the shared name. */
  stationName?: (station: Station, t: (key: string) => string) => string | undefined;
}

const modules = new Map<DeckId, DeckModule>();

export function registerDeck(module: DeckModule): void {
  modules.set(module.id, module);
}

export function deckModule(id: DeckId): DeckModule | undefined {
  return modules.get(id);
}

export function availableDecks(): DeckId[] {
  return [...modules.keys()];
}

