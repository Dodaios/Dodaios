/**
 * What the person's selection opens in the office: an agent's walkie-talkie
 * (an IDE session on the coding floor has its own PaneCommandPanel), or the
 * surface of a station. Every action here uses an existing app path — the
 * create dialog, agent card and chat, chat groups — the office adds no new
 * backend contract.
 *
 * Not every station has a surface here: the spawn terminal opens the app's
 * create dialog, the lead's desk selects the lead, the coffee bar calls a
 * break, the elevator and the Level Hall open their own screens. OfficeStage
 * turns those selections into their action.
 */
import { useT } from "@/i18n";
import type { SocietyAgent } from "../data";
import type { OfficeLayout } from "./officeLayout";
import type { NavGrid } from "./officeNav";
import { type OfficeFloor, type Selection } from "./officeStore";
import { AgentTalkPanel } from "./AgentTalkPanel";
import type { PlayerProfile } from "./playerProfile";
import { WardrobePanel } from "./WardrobePanel";
import { ReceptionPanel } from "./ReceptionPanel";
import { TeamRoomPanel } from "./TeamRoomPanel";
import { MissionControlPanel } from "./MissionControlPanel";
import { LaunchPanel } from "./SpawnPanel";
import { StationSheet, StationSidePanel } from "./StationSheet";
import { isReception, isTeamStand } from "./stations";

export interface OfficeActions {
  onOpenAgent: (id: string) => void;
  onOpenLedger: () => void;
  onCreateAgent?: () => void;
  onOpenGroup?: (groupId: string) => void;
}

/** How a station's surface is shown: a dialog over the map, or a panel docked beside it. */
export type StationSurfaceKind = "sheet" | "side";

/** The stations that open a surface of their own, and how. Everything else is an action (see OfficeStage). */
export function stationSurface(selection: Selection | null): StationSurfaceKind | null {
  if (!selection) return null;
  if (selection.kind === "team") return "sheet";
  if (selection.kind !== "checkpoint") return null;
  if (selection.id === "wardrobe") return "side";
  if (isReception(selection) || selection.id === "team" || selection.id === "launch" || selection.id === "mission") return "sheet";
  return null;
}

/** The agent panel is a walkie-talkie to that agent (AgentTalkPanel). */
export function AgentPanel({ agent, actions, onClose }: { agent: SocietyAgent; actions: OfficeActions; onClose: () => void }) {
  return <AgentTalkPanel agent={agent} actions={actions} onClose={onClose} />;
}

export function StationSurface({ selection, floor = "agents", agents, layout, grid, sample, profile, onProfile, actions, onClose, returnFocus }: {
  selection: Selection; floor?: OfficeFloor; agents: SocietyAgent[]; layout: OfficeLayout; sample: boolean;
  /** The floor's nav grid: a team opened from its studio board meets at that board, on places the grid allows. */
  grid?: NavGrid;
  profile: PlayerProfile; onProfile: (next: PlayerProfile) => void; actions: OfficeActions; onClose: () => void;
  /** Hands focus back to the map once a dialog has closed. */
  returnFocus?: () => void;
}) {
  const t = useT();
  if (selection.kind === "team") {
    const studio = (layout.studios ?? []).find((s) => s.board?.id === selection.id);
    if (!studio) {
      // The free plot's stand: no team stands here yet, so the sheet opens on the form that starts one.
      if (!isTeamStand(layout, selection)) return null;
      return (
        <StationSheet title={t("society.office.cp_found")} description={t("society.office.plot_free")} onClose={onClose} returnFocus={returnFocus}>
          <TeamRoomPanel agents={agents} layout={layout} sample={sample} actions={actions} onMeet={onClose} compose />
        </StationSheet>
      );
    }
    return (
      <StationSheet title={studio.teamId ? studio.name : t("society.office.team_pool")} description={t("society.office.cp_board_hint")} onClose={onClose} returnFocus={returnFocus}>
        <TeamRoomPanel agents={agents} layout={layout} sample={sample} actions={actions} onMeet={onClose}
          focus={{ teamId: studio.teamId, members: studio.members, studio, grid }} />
      </StationSheet>
    );
  }
  if (selection.kind !== "checkpoint") return null;
  const id = selection.id;
  if (id === "wardrobe") {
    return (
      <StationSidePanel title={t("society.office.cp_wardrobe")} description={t("society.office.wardrobe_body")} onClose={onClose}>
        <WardrobePanel profile={profile} onProfile={onProfile} agents={agents} sample={sample} />
      </StationSidePanel>
    );
  }
  if (isReception(selection)) {
    return (
      <StationSheet title={t("society.office.cp_manage")} description={t("society.office.cp_manage_hint")} onClose={onClose} returnFocus={returnFocus}>
        <ReceptionPanel floor={floor} layout={layout} agents={agents} actions={actions} />
      </StationSheet>
    );
  }
  if (id === "team") {
    return (
      <StationSheet title={t("society.office.cp_team")} description={t("society.office.cp_team_hint")} onClose={onClose} returnFocus={returnFocus}>
        <TeamRoomPanel agents={agents} layout={layout} sample={sample} actions={actions} onMeet={onClose} />
      </StationSheet>
    );
  }
  if (id === "launch") {
    return (
      <StationSheet size="md" title={t("society.office.cp_launch")} description={t("society.office.launch_body")} onClose={onClose} returnFocus={returnFocus}>
        <LaunchPanel />
      </StationSheet>
    );
  }
  if (id === "mission") {
    return (
      <StationSheet size="md" title={t("society.office.cp_mission")} description={t("society.office.cp_mission_hint")} onClose={onClose} returnFocus={returnFocus}>
        <MissionControlPanel />
      </StationSheet>
    );
  }
  return null;
}
