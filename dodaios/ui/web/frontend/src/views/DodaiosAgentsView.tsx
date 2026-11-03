/**
 * Lazy map surface; the parent keeps the existing Agents workspace mounted.
 * SocietyView loads this module on demand, so the Verse's WebGL chunk stays
 * out of the main bundle.
 */
import { useLocaleChunk } from "@/i18n";
import type { PlaceId } from "@/components/society/world/islandLayout";
import { VerseStage } from "@/components/society/verse/VerseStage";
import { VerseLoadingScreen } from "@/components/society/verse/VerseLoadingScreen";
import { VerseHostMount } from "@/components/verseHost/VerseHostMount";

export interface DodaiosAgentsViewProps {
  onSelectAgent?: (agentId: string | null) => void;
  onSelectPlace?: (place: PlaceId) => void;
  onOpenAgents: () => void;
  onCreateAgent?: () => void;
  onOpenGroup?: (groupId: string) => void;
  active?: boolean;
}

export function DodaiosAgentsView({ onSelectAgent, onOpenAgents, onCreateAgent, onOpenGroup, active = true }: DodaiosAgentsViewProps) {
  const ready = useLocaleChunk("society");
  if (!ready) return <div className="relative h-full"><VerseLoadingScreen /></div>;
  return (
    <div className="relative h-full min-h-0">
      <VerseStage active={active} onOpenLedger={onOpenAgents} onSelectAgent={onSelectAgent} onCreateAgent={onCreateAgent} onOpenGroup={onOpenGroup} />
      {/* The Unreal Verse launcher, behind verse.unreal_preview until the deletion PR. */}
      <VerseHostMount />
    </div>
  );
}
