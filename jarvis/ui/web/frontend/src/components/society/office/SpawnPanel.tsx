/**
 * The coding floor's spawn terminal: Mission Control's launcher (CLI,
 * workspace, how many, an optional first task). Whoever it starts appears on
 * the spawn pad and walks to a free desk.
 *
 * The agents floor's terminal has no panel of its own: it opens the app's
 * create dialog (see OfficeStage).
 */
import { StartAgent } from "./MissionControlPanel";

export function LaunchPanel() {
  return <div className="office-mc"><StartAgent /></div>;
}
