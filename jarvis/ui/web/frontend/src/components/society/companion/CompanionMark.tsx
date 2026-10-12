import { useContext } from "react";
import { QueryClientContext } from "@tanstack/react-query";

import { PetSprite } from "@/components/pets/PetSprite";
import { PetStageContext } from "@/components/pets/petStage";
import { usePetById } from "@/hooks/usePets";
import type { PetState } from "@/lib/petStates";
import { AgentSymbol } from "../AgentSymbol";
import type { CompanionAppearance } from "./appearance";
import type { CreatureState } from "./creature";
import { useShownCreature } from "./creatureTrial";
import { PixelCreature } from "./PixelCreature";

type MarkProps = {
  appearance: CompanionAppearance;
  size: number;
  /** The agent is at work: the shape shows thinking dots, a pet plays its working row. */
  thinking?: boolean;
  /** Eyes a stage can animate (shapes only; a pet acts through its own rows). */
  expressive?: boolean;
  /** Fixes the pet's row; otherwise a surrounding stage or `thinking` decides. */
  state?: PetState;
  /** The agent's coarse run state: a creature asks while it waits and sleeps while paused. */
  run?: "idle" | "working" | "waiting" | "paused";
  /** Fixes what a creature acts out (the look editor's preview). */
  mood?: CreatureState;
};

/** A creature acts out the pet vocabulary every stage already speaks. */
const CREATURE_FOR_PET: Readonly<Record<PetState, CreatureState>> = {
  idle: "idle", listening: "listening", thinking: "thinking", talking: "talking", success: "success",
  error: "error", sleeping: "sleeping", working: "working", searching: "working", held: "listening",
};
const CREATURE_FOR_RUN = { idle: "idle", working: "working", waiting: "asking", paused: "sleeping" } as const;

/**
 * An agent's face in 2D: its shape symbol, the pixel creature it wears
 * instead (`companion.creature`), or its pet (`companion.pet`, chosen in the
 * look dialog from My Pets). Every surface
 * that draws an agent goes through here, so choosing a pet changes the
 * roster, the chats, the bot stage and the level hall at once.
 *
 * A pet face reads the shared pets answer. Until it arrives the box stays
 * empty at its final size, so no shape flashes before the pet; a pet that
 * does not exist here (deleted, or drawn on another machine) shows the shape.
 */
export function CompanionMark(props: MarkProps) {
  const { appearance, size, thinking = false, expressive = false, state, run, mood } = props;
  const creature = useShownCreature(appearance);
  const staged = useContext(PetStageContext);
  const pose = state ?? staged;
  const shape = creature
    ? <PixelCreature creature={creature} size={size} state={mood ?? (pose ? CREATURE_FOR_PET[pose] : thinking ? "working" : CREATURE_FOR_RUN[run ?? "idle"])} />
    : <AgentSymbol {...appearance} size={size} thinking={thinking} expressive={expressive} />;
  // Outside a query client (an isolated render, a bare preview) there is no catalog to read.
  const client = useContext(QueryClientContext);
  if (!appearance.pet || !client) return shape;
  return <PetFace {...props} petId={appearance.pet} fallback={shape} />;
}

function PetFace({ petId, size, thinking = false, state, fallback }: MarkProps & { petId: string; fallback: JSX.Element }) {
  const pet = usePetById(petId);
  const staged = useContext(PetStageContext);
  if (pet === undefined) return <span aria-hidden className="inline-block shrink-0" style={{ width: size, height: size }} />;
  if (pet === null) return fallback;
  return <span className="agent-pet-face inline-flex shrink-0" data-agent-pet={pet.id}>
    <PetSprite pet={pet} state={state ?? staged ?? (thinking ? "working" : "idle")} px={size} />
  </span>;
}
