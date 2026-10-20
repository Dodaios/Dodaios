/**
 * Everything of the rank system that floats over the stage: the service
 * record (open when the store says so) and the promotion notice with the
 * crew's toasts. The stage mounts it once; the rank card sits in the HUD.
 */
import { PromotionNotice } from "./PromotionNotice";
import type { CrewMember } from "./rankModel";
import { ServiceRecord } from "./ServiceRecord";

export interface RanksOverlayProps {
  /** False while the Verse is hidden: nothing is drawn (the store keeps its queue). Default true. */
  active?: boolean;
  /** The officers aboard (the roster without the lead), for names and the crew page. */
  crew?: readonly CrewMember[];
  /** What the companion drone is called (the lead's name); the generic word without one. */
  companionName?: string;
}

export function RanksOverlay({ active = true, crew, companionName }: RanksOverlayProps) {
  if (!active) return null;
  return (
    <>
      <ServiceRecord crew={crew} companionName={companionName} />
      <PromotionNotice crew={crew} companionName={companionName} />
    </>
  );
}
