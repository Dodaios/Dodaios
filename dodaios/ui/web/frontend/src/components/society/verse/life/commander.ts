/**
 * Where the commander goes on the deck on screen. Pure.
 *
 * A walk order belongs to the deck it was given on: riding the lift (or the
 * IDE panel switching to its deck) never sends the commander toward a point
 * of the deck they just left. After a ride they step out of the lift; on a
 * first visit they stand at their spawn.
 */
import type { Deck } from "../content/deck";
import type { DeckId } from "../decks";
import { nearestWalkable } from "../nav/pathfind";

export interface DeckPoint { deck: DeckId; x: number; z: number }

export interface CommanderOrders {
  /** The last walk order, on the deck it was given on; null = none yet. */
  target: DeckPoint | null;
  /** Changes with every order, so a click on the same spot walks again. */
  order: number;
  /** The commander came to this deck by lift. */
  fromLift: boolean;
}

/** Where the commander stands when a deck opens: their own spawn, else the lift, else the middle of the floor. */
export function commanderStart(deck: Pick<Deck, "sockets" | "nav" | "camera">): { x: number; z: number } {
  const own = deck.sockets.find((s) => s.kind === "spawn" && s.id.startsWith("commander"))
    ?? deck.sockets.find((s) => s.kind === "lift")
    ?? deck.sockets.find((s) => s.kind === "spawn");
  const c = deck.camera.center;
  const at = own ? { x: own.x, z: own.z } : { x: c[0], z: c[2] };
  return nearestWalkable(deck.nav, at, 6) ?? at;
}

/** A step out of the lift doors, where a ride ends. */
export function outOfLift(deck: Pick<Deck, "sockets" | "nav">): { x: number; z: number } | null {
  const lift = deck.sockets.find((s) => s.kind === "lift");
  if (!lift) return null;
  return nearestWalkable(deck.nav, { x: lift.x + Math.sin(lift.yaw) * 1.6, z: lift.z + Math.cos(lift.yaw) * 1.6 }, 4);
}

/** Where the commander heads on `deck` under `orders`. */
export function commanderTarget(deck: Pick<Deck, "id" | "sockets" | "nav" | "camera">, orders: CommanderOrders): { x: number; z: number } {
  if (orders.target && orders.target.deck === deck.id) return { x: orders.target.x, z: orders.target.z };
  return (orders.fromLift ? outOfLift(deck) : null) ?? commanderStart(deck);
}
