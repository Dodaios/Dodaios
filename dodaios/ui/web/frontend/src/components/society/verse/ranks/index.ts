/**
 * The Verse's ranks and duty status: what the stage imports.
 *
 * - Data: `ranks.ts` (the ladder, plates, tiers, uniforms), `dutyStatus.ts`.
 * - Hooks: `useSubjectRank`, `useCommanderRank`, `useCommanderUniform`, `useDutyBoard`.
 * - UI: `RankPlate`, `RankCard` (HUD), `RanksOverlay` (service record + promotion notice).
 */
export * from "./ranks";
export * from "./dutyStatus";
export { RankPlate, PLATE_ASPECT, slotCentre } from "./RankPlate";
export { Ribbon } from "./Ribbon";
export { RankCard, type RankCardProps } from "./RankCard";
export { ServiceRecord } from "./ServiceRecord";
export { PromotionNotice, isNotice } from "./PromotionNotice";
export { RanksOverlay, type RanksOverlayProps } from "./RanksOverlay";
export { rankView, crewRows, type RankView, type CrewMember } from "./rankModel";
export { useSubjectRank, useCommanderRank, useCommanderUniform, useDutyBoard, applyDutyEvent, type DutyMember } from "./useRanks";
