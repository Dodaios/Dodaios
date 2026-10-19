/**
 * Deck 3, engineering: the coding panes of the Agentic IDE at work round the
 * reactor. Its crew are the panes; the master systems display opens the
 * launcher for new coding agents.
 */
import { registerDeck } from "../registry";
import { buildEngineeringDeck } from "./engineeringDeck";
import { EngineeringPanel } from "./EngineeringPanel";
import { EngineeringScene } from "./EngineeringScene";
import "./props";

registerDeck({
  id: "engineering",
  population: "panes",
  build: (input) => buildEngineeringDeck({
    panes: input.panes.map((o) => ({ agentId: o.agent.agentId, workspaceId: o.pane.workspace_id, workspace: o.agent.providerLabel || o.pane.workspace_name })),
  }),
  Scene: EngineeringScene,
  useStation: (station, _plan, actions) => {
    if (station.kind !== "systems") return false;
    actions.openPanel(station.id);
    return true;
  },
  Panel: EngineeringPanel,
});
