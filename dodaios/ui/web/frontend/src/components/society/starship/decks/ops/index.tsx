/** The operations deck: the Jarvis agents' divisions, the mess, the transporter and the quartermaster. */
import { buildOpsDeck } from "../../plan/opsDeck";
import { registerDeck, type DeckPanelProps } from "../registry";
import { DivisionPanel } from "./DivisionPanel";
import { QuartermasterPanel } from "./QuartermasterPanel";

function OpsPanel(props: DeckPanelProps) {
  return props.station.kind === "division" ? <DivisionPanel {...props} /> : <QuartermasterPanel {...props} />;
}

registerDeck({
  id: "ops",
  population: "agents",
  build: (input) => buildOpsDeck({ crew: input.crew, teams: input.teams }),
  // The holo-table and the quartermaster open their panels; the rest is the stage's.
  useStation: (station, _plan, actions) => {
    if (station.kind !== "quartermaster" && station.kind !== "division") return false;
    actions.openPanel(station.id);
    return true;
  },
  Panel: OpsPanel,
});
