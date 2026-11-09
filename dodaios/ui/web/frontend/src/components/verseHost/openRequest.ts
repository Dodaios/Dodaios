/**
 * `VerseOpenRequested` (bridge contract 11 and 14): the Unreal Verse asked the
 * app to open one of its views. Each target runs the code the web Verse runs
 * for the same click, so both Verses open the same thing.
 *
 * | target      | opens                                                     |
 * |-------------|-----------------------------------------------------------|
 * | `pane`      | the IDE on that pane, maximised (`open: "changes"`: its changes view) |
 * | `agent`     | the agent's card in the Agents section                    |
 * | `agents`    | the Agents section                                        |
 * | `group`     | the Agents section; `dodaios:verse-open-group` names the group |
 * | `simulator` | the Agents section; `dodaios:verse-open-simulator` names the programme |
 * | `ide`       | the IDE section without a pane                            |
 */
import { useEventStore } from "@/store/events";
import { openPaneSession } from "@/components/agentic/openPaneSession";
import { openAgent } from "@/views/society/agentNavigation";

export interface VerseOpenPayload {
  target?: string;
  workspace_id?: string;
  name?: string;
  focus?: boolean;
  open?: string;
  agent_id?: string;
  group_id?: string;
  programme?: string;
}

/** The socket forwarded a `VerseStatusChanged`; the launcher card re-reads its status. */
export const VERSE_STATUS_EVENT = "dodaios:verse-status";
export const VERSE_OPEN_GROUP_EVENT = "dodaios:verse-open-group";
export const VERSE_OPEN_SIMULATOR_EVENT = "dodaios:verse-open-simulator";

function section(id: "agentic-ide" | "agents"): void {
  const events = useEventStore.getState();
  if (events.activeSection !== id) events.setActiveSection(id);
}

/** Returns false for a payload this app does not know how to open. */
export function handleVerseOpen(payload: VerseOpenPayload, solo = useEventStore.getState().solo): boolean {
  // A detached window is pinned to its own section; the main window opens it.
  if (solo) return false;
  switch (payload.target) {
    case "pane": {
      if (!payload.workspace_id || !payload.name) return false;
      openPaneSession({ workspace_id: payload.workspace_id, name: payload.name },
        { ...(payload.open === "changes" ? { open: "changes" as const } : {}), ...(payload.focus ? { focus: true } : {}) });
      return true;
    }
    case "ide":
      section("agentic-ide");
      return true;
    case "agent":
      if (!payload.agent_id) return false;
      openAgent(payload.agent_id);
      return true;
    case "agents":
      section("agents");
      return true;
    case "group":
      if (!payload.group_id) return false;
      section("agents");
      window.dispatchEvent(new CustomEvent(VERSE_OPEN_GROUP_EVENT, { detail: { groupId: payload.group_id } }));
      return true;
    case "simulator":
      if (!payload.programme) return false;
      section("agents");
      window.dispatchEvent(new CustomEvent(VERSE_OPEN_SIMULATOR_EVENT, { detail: { programme: payload.programme } }));
      return true;
    default:
      return false;
  }
}
