import { createContext, useContext } from "react";

/**
 * Set when another surface beside the chat carries a brain picker of its own
 * (the details pane's Details tab). The composer keeps its own picker in its
 * "+" menu either way, and holds Send while the other picker saves a new
 * model, exactly as it does while its own picker saves.
 */
export interface HeaderModelSlot {
  saving: boolean;
}

export const HeaderModelSlotContext = createContext<HeaderModelSlot | null>(null);

export function useHeaderModelSlot(): HeaderModelSlot | null {
  return useContext(HeaderModelSlotContext);
}
