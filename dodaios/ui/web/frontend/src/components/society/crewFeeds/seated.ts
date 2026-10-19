/**
 * Who sits at their console right now, by agent id. The ship's crew layer
 * keeps it current every frame; the screen and chat feeds read it, so only
 * consoles somebody sits at are polled.
 */
export const seatedCrew = new Set<string>();
