/**
 * How much of a name plate shows. From across the floor an agent is one small
 * state dot, so the overview is a calm field of dots and not of labels; the
 * whole plate (name, rank, activity) appears when the camera or the person
 * comes near, when the pointer or keyboard focus rests on the agent, or when
 * it is selected. Pure and tested.
 */

export type PlateDetail = "dot" | "full";

/**
 * Distances in metres, each as a pair: the plate opens inside the first and
 * closes again only beyond the second. The gap keeps a plate from flickering
 * while someone stands or strolls right at the threshold.
 */
export const PLATE_RANGE = {
  /** Camera to agent. The follow view keeps the camera 15 m from the person, so this is a deliberate zoom in. */
  camera: { open: 10.5, close: 12.5 },
  /** The person's character to agent: the people round you introduce themselves. */
  person: { open: 4.6, close: 6 },
} as const;

export interface PlateInput {
  /** Camera to the plate. */
  cameraDistance: number;
  /** The person's character to the agent, on the floor. */
  personDistance: number;
  /** The pointer or keyboard focus rests on the agent or its plate. */
  pointed: boolean;
  selected: boolean;
}

export function plateDetail(previous: PlateDetail, input: PlateInput): PlateDetail {
  if (input.selected || input.pointed) return "full";
  const edge = previous === "full" ? "close" : "open";
  const near = input.cameraDistance <= PLATE_RANGE.camera[edge] || input.personDistance <= PLATE_RANGE.person[edge];
  return near ? "full" : "dot";
}
