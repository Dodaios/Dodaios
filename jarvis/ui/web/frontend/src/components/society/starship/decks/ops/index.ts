/** The operations deck: the Jarvis agents' divisions, the mess, the transporter and the quartermaster. */
import { buildOpsDeck } from "../../plan/opsDeck";
import { registerDeck } from "../registry";
import { QuartermasterPanel } from "./QuartermasterPanel";

registerDeck({
  id: "ops",
  population: "agents",
  build: (input) => buildOpsDeck({ crew: input.crew, teams: input.teams }),
  useStation: (station, _plan, actions) => {
    if (station.kind !== "quartermaster") return false;
    actions.openPanel(station.id);
    return true;
  },
  Panel: QuartermasterPanel,
});
