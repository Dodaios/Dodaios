/**
 * What every screen on the deck shows, from the feeds that already exist:
 * a bridge console shows the tail of its officer's chat (useDeskChats), an
 * engineering terminal its pane's terminal (usePaneScreens), a briefing-room
 * wall screen the running round's transcript, any other screen a standby
 * page. Consoles belong to their officer whether or not the officer sits
 * there right now; an empty console says so.
 */
import { useMemo } from "react";
import type { Deck } from "../content/deck";
import { useDeskChats } from "../../crewFeeds/useDeskChats";
import { MAX_SCREEN_TARGETS, usePaneScreens, type PaneScreenTarget } from "../../crewFeeds/usePaneScreens";
import { visibleRows } from "../../crewFeeds/terminalScreen";
import { useTeamwork } from "../../crewFeeds/teamwork";
import type { ChatLine } from "../../crewFeeds/deskChat";
import type { CrewLife } from "../life/useCrewLife";
import type { DutyStatus } from "../ranks";
import type { ScreenFace, ScreenTone } from "./screenPainter";

const TONE: Readonly<Record<DutyStatus, ScreenTone>> = { working: "live", waiting: "attention", error: "fault", idle: "standby", paused: "standby" };
const TERMINAL_ROWS = 14;

function chatText(line: ChatLine): string {
  switch (line.kind) {
    case "user": return `> ${line.text}`;
    case "tool": return `  ${line.text}`;
    case "error": return `! ${line.text}`;
    case "notice": return `- ${line.text}`;
    default: return line.text;
  }
}

/** Slice targets into the fixed number of pollers the feed allows. */
function chunk<T>(list: readonly T[], size: number, count: number): T[][] {
  return Array.from({ length: count }, (_, k) => list.slice(k * size, (k + 1) * size));
}

export function useScreenFaces(deck: Deck | null, life: CrewLife, awake: boolean, t: (key: string) => string): ReadonlyMap<string, ScreenFace> {
  // Seat id (= screen id) → its member.
  const homes = useMemo(() => new Map([...life.homes].map(([member, seat]) => [seat, member])), [life.homes]);

  const sessions = useMemo(() => {
    const m = new Map<string, string>();
    if (deck?.id !== "bridge") return m;
    for (const member of homes.values()) {
      const session = life.agents.get(member)?.chatSessionId;
      if (session) m.set(member, session);
    }
    return m;
  }, [deck, homes, life.agents]);
  const chats = useDeskChats(sessions, awake && deck?.id === "bridge");

  const targets = useMemo(() => {
    const list: PaneScreenTarget[] = [];
    if (deck?.id !== "engineering") return chunk(list, MAX_SCREEN_TARGETS, 2);
    for (const member of homes.values()) {
      const pane = life.panes.get(member)?.pane;
      if (pane) list.push({ agentId: member, workspaceId: pane.workspace_id, key: pane.key });
    }
    return chunk(list, MAX_SCREEN_TARGETS, 2);
  }, [deck, homes, life.panes]);
  const terminalsA = usePaneScreens(targets[0], awake);
  const terminalsB = usePaneScreens(targets[1], awake);

  const rounds = useTeamwork((s) => s.rounds);

  return useMemo(() => {
    const faces = new Map<string, ScreenFace>();
    if (!deck) return faces;
    const running = Object.values(rounds).find((r) => r.running && r.lines.length > 0);
    for (const socket of deck.sockets) {
      if (socket.kind !== "screen") continue;
      const member = homes.get(socket.id);
      const isConsole = deck.sockets.some((s) => s.kind === "seat" && s.id === socket.id);
      if (!isConsole) {
        // Wall screens: a running round's transcript in the briefing room, a quiet page elsewhere.
        const station = socket.station ? deck.stations.find((s) => s.id === socket.station) : undefined;
        if (running && (station?.kind === "team" || socket.group.startsWith("brief"))) {
          faces.set(socket.id, {
            tone: "live", title: t("verse.station.team.name"), status: t("verse.state.working"),
            lines: running.lines.map((l) => `${life.agents.get(l.speaker)?.name ?? l.speaker}: ${l.text}`), cursor: true,
          });
        } else {
          faces.set(socket.id, { tone: "standby", title: deck.name, status: t("verse.screen.standby"), lines: [], cursor: false });
        }
        continue;
      }
      const crew = member ? life.crew.get(member) : undefined;
      if (!crew) {
        faces.set(socket.id, { tone: "standby", title: t("verse.screen.vacant"), status: t("verse.screen.vacant"), lines: [], cursor: false });
        continue;
      }
      const tone = TONE[crew.status];
      const status = crew.status === "waiting" ? t("verse.screen.waiting") : crew.status === "error" ? t("verse.screen.fault")
        : crew.status === "working" ? t("verse.state.working") : t("verse.screen.standby");
      let lines: string[] = [];
      if (crew.role === "officer") lines = (chats.get(crew.id)?.lines ?? []).map(chatText);
      else {
        const screen = terminalsA.get(crew.id) ?? terminalsB.get(crew.id);
        if (screen) lines = visibleRows(screen.lines, TERMINAL_ROWS, screen.cursor).rows;
        else if (life.panes.get(crew.id)?.pane.last_prompt) lines = [`> ${life.panes.get(crew.id)?.pane.last_prompt}`];
      }
      faces.set(socket.id, { tone, title: crew.name, status, lines: tone === "standby" ? lines.slice(-3) : lines, cursor: tone === "live" || tone === "attention" });
    }
    return faces;
  }, [deck, homes, life.crew, life.agents, life.panes, chats, terminalsA, terminalsB, rounds, t]);
}
