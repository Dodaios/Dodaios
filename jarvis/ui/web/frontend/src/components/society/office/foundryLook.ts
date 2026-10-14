/**
 * Is this the coding floor's Foundry deck? Pieces every floor shares (the
 * reception counter, the elevator, the team room) read it and swap their wood,
 * white and stone for the deck's steel, slate and gold there. Provided by the
 * floor dressing; false everywhere else.
 */
import { createContext, useContext } from "react";

export const FoundryLook = createContext(false);

export function useFoundryLook(): boolean {
  return useContext(FoundryLook);
}
