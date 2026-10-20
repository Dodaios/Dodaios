/** A station in words: what it is called and what using it does. Shared by the prompt, the places menu and the directory. */
import type { Station } from "./stations";

type Translate = (key: string) => string;

/**
 * What a station is called. A team studio's board is called after its team;
 * the board of the studio for agents without a team says so, so no row of a
 * list is ever a bare "Team board".
 */
export function stationLabel(station: Pick<Station, "id" | "name">, t: Translate): string {
  if (station.name) return station.name;
  return t(station.id === "board" ? "society.office.team_pool" : `society.office.cp_${station.id}`);
}

/** The action a station offers, in words; the coffee bar's flips while a break is on. */
export function stationAction(station: Pick<Station, "id">, t: Translate, breakOn = false): string {
  return t(`society.office.use_${station.id === "break" && breakOn ? "break_end" : station.id}`);
}
