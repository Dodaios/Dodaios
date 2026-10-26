import { createContext, useContext } from "react";

/**
 * Set when the chat header carries the agent's brain picker. The composer
 * then leaves its own copy out and holds Send while the header saves a new
 * model, exactly as it did while its own picker saved. Where no header
 * provides it (team panes, older mounts) the composer keeps its picker.
 */
export interface HeaderModelSlot {
  saving: boolean;
}

export const HeaderModelSlotContext = createContext<HeaderModelSlot | null>(null);

export function useHeaderModelSlot(): HeaderModelSlot | null {
  return useContext(HeaderModelSlotContext);
}
