import { createContext } from "react";

/**
 * Whether the view that holds the side panel is on screen right now.
 *
 * The Agentic IDE stays mounted while another section is shown, so its tabs
 * keep running. A tab that drives something outside the page (the Browser
 * tab's native window) reads this to react in the same commit that hides the
 * IDE, instead of waiting to measure a hidden box on a later frame.
 */
export const SidePanelOnScreen = createContext(true);
