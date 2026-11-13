import { useContext } from "react";
import { QueryClientContext, useQuery } from "@tanstack/react-query";

import { GigiAvatar } from "./GigiAvatar";
import { PetSprite } from "@/components/pets/PetSprite";
import { petKeys, pickActivePet } from "@/hooks/usePets";
import { fetchPets } from "@/lib/petsApi";
import { cn } from "@/lib/utils";

import { resolveCompanion } from "./companion/appearance";
import { creatureColor } from "./companion/creature";
import { CompanionMark } from "./companion/CompanionMark";
import { WorkingBadge } from "./companion/WorkingBadge";
import type { SocietyAgent } from "./data";

type SwatchAgent = Pick<SocietyAgent, "figure" | "palette" | "name"> &
  Partial<Pick<SocietyAgent, "agentId" | "tier" | "state">>;

/** The gold of the lead's mark (GigiAvatar's lens rim). */
export const LEAD_COLOR = "#ffcd61";

/**
 * The one colour a person knows an agent by: the lead's gold, or the
 * companion colour its symbol wears everywhere else.
 */
export function agentColor(agent: SwatchAgent): string {
  if (isLead(agent)) return LEAD_COLOR;
  const look = resolveCompanion(agent.agentId || agent.name, agent.figure?.companion);
  // A creature is known by its colour world; the shape colour underneath stays for the way back.
  return look.creature && !look.pet ? creatureColor(look.creature) : look.color;
}

function isLead(agent: SwatchAgent): boolean {
  // Older internal-message participants carry the figure but not the tier.
  return agent.tier === "lead" || (
    !agent.tier && agent.figure?.archetype === "spirit" && agent.figure.base === "gigi"
  );
}

/** Lightweight vector identity shared by roster, profile and message surfaces. */
export function AgentSwatch({
  agent,
  size = 36,
  className,
  expressive = false,
}: {
  agent: SwatchAgent;
  size?: number;
  className?: string;
  /** Eyes a stage can animate between expressions (look, squint, wink, smile). */
  expressive?: boolean;
}) {
  const isJarvis = isLead(agent);
  // Real roster identities survive renames. Name-only historical participants
  // still get a deterministic symbol without fetching a roster or a 3D model.
  const appearance = resolveCompanion(agent.agentId || agent.name, agent.figure?.companion);
  const thinking = agent.state === "working";

  return (
    <span
      aria-hidden
      className={cn("relative inline-flex shrink-0 items-center justify-center select-none", className)}
      data-thinking={isJarvis && thinking ? "true" : undefined}
      style={{ width: size, height: size }}
    >
      {isJarvis ? (
        <>
        <LeadFace size={size} thinking={thinking} />
        {thinking && <WorkingBadge size={size} />}
        </>
      ) : (
        <CompanionMark appearance={appearance} size={size} thinking={thinking} expressive={expressive} run={agent.state} />
      )}
    </span>
  );
}

/**
 * The lead is the assistant, and the assistant's face is the pet the person
 * chose in My Pets (the caption switch, the greeting and the panel draw the
 * same one). The gold companion stays only where no pets answer can come: an
 * isolated render without a query client, a failed request, a machine with
 * no pets. While the answer loads the box stays empty, so no other face
 * flashes first.
 */
function LeadFace({ size, thinking }: { size: number; thinking: boolean }) {
  const client = useContext(QueryClientContext);
  if (!client) return <GigiAvatar size={size} />;
  return <LeadPet size={size} thinking={thinking} />;
}

function LeadPet({ size, thinking }: { size: number; thinking: boolean }) {
  const { data, isError } = useQuery({ queryKey: petKeys.all, queryFn: fetchPets, staleTime: Infinity });
  const pet = pickActivePet(data);
  if (pet) return <span data-agent-mascot="pet" data-pet={pet.id} className="inline-flex"><PetSprite pet={pet} state={thinking ? "working" : "idle"} px={size} /></span>;
  if (isError || data) return <GigiAvatar size={size} />;
  return <span style={{ width: size, height: size }} />;
}
