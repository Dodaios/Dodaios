/**
 * What may be said about a team at a glance, and where each claim comes from.
 *
 * "Live" means one thing only: a round of the team is answering right now,
 * as the backend reports it (teamwork's `TeamRound.running`). "Called" is the
 * person's own gathering on the map (officeStore's `meeting`): members walk
 * to the table or to their board, nothing is posted to the team and no agent
 * starts work. The two are never mixed, so a board or a card can never show
 * a gathering as a running round. Pure and tested.
 */

export type TeamMark = "live" | "called" | null;

export function teamMark(
  groupId: string,
  rounds: Readonly<Record<string, { running: boolean } | undefined>>,
  gathering: { groupId: string; untilMs: number } | null,
  now: number,
): TeamMark {
  // A real round outranks the gathering: if the team answers while it stands at its board, that is the news.
  if (rounds[groupId]?.running) return "live";
  if (gathering && gathering.groupId === groupId && gathering.untilMs > now) return "called";
  return null;
}
