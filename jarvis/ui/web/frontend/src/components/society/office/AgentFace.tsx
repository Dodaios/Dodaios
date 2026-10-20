/**
 * An agent's face in a list of the office (the directory, team rows, member
 * lists, the member picker): its symbol on a neutral tile.
 *
 * Two things a bare symbol gets wrong in a list. Its colour is the agent's
 * own, and a white or very pale one vanishes on a light dialog (a black one
 * on a dark dialog): the tile and a hairline round the symbol's own outline,
 * both from theme tokens, keep every colour readable in both themes. And a
 * working agent's symbol turns into three "thinking" dots, which in a row of
 * faces reads as a picture that is still loading: the run state is left out
 * here, the state dot beside the face says it.
 */
import { AgentSwatch } from "../AgentSwatch";
import type { SocietyAgent } from "../data";
import "./agentFace.css";

/** The tile is this much wider than the symbol on it. */
const TILE_MARGIN_PX = 8;

export function AgentFace({ agent, size = 24 }: { agent: SocietyAgent; size?: number }) {
  const tile = size + TILE_MARGIN_PX;
  return (
    <span className="office-face" style={{ width: tile, height: tile }}>
      <AgentSwatch agent={{ ...agent, state: undefined }} size={size} />
    </span>
  );
}
