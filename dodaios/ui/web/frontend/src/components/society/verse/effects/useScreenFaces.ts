/**
 * What every screen on the deck shows, from the feeds that already exist:
 * a bridge console shows the tail of its officer's chat (useDeskChats), an
 * engineering terminal its pane's terminal, cell for cell (the IDE's own
 * xterm buffer, or the server replay for a pane the IDE has not mounted),
 * the engineering master station's big screens every coding pane in a grid,
 * a briefing-room wall screen the running round's transcript, any other
 * screen a standby page. Consoles belong to their officer whether or not the
 * officer sits there right now; an empty console says so.
 */
import { useMemo, useSyncExternalStore } from "react";
import type { Deck, Socket } from "../content/deck";
import { liveTerminal, liveTerminalsGeneration, subscribeLiveTerminals } from "@/lib/liveTerminals";
import { useDeskChats } from "../../crewFeeds/useDeskChats";
import { MAX_SCREEN_TARGETS, usePaneScreens, type PaneScreenTarget } from "../../crewFeeds/usePaneScreens";
import { useTeamwork } from "../../crewFeeds/teamwork";
import type { ChatLine } from "../../crewFeeds/deskChat";
import type { CrewLife } from "../life/useCrewLife";
import type { DutyStatus } from "../ranks";
import type { ScreenTone } from "./screenPainter";
import type { ScreenView } from "./ScreensLayer";
import type { TerminalTileFace } from "./terminalCanvas";

const TONE: Readonly<Record<DutyStatus, ScreenTone>> = { working: "live", waiting: "attention", error: "fault", idle: "standby", paused: "standby" };
/** The station whose screens show every coding pane. */
const MASTER_STATION = "master";
/** Its consoles show one pane each, in order: `master__1` the first. */
const MASTER_CONSOLE = /^master__(\d+)$/;

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

/** Sockets on `deck` that show coding-pane terminals: the engineering desks and the master station. Pure. */
export function terminalSocketIds(deck: Deck | null): ReadonlySet<string> {
  const out = new Set<string>();
  if (deck?.id !== "engineering") return out;
  const seats = new Set(deck.sockets.filter((s) => s.kind === "seat").map((s) => s.id));
  for (const s of deck.sockets) {
    if (s.kind === "screen" && (seats.has(s.id) || s.station === MASTER_STATION)) out.add(s.id);
  }
  return out;
}

/** Which panes a master-station screen shows: one for a numbered console, all of them otherwise. Pure. */
export function masterScreenPanes<T>(socket: Pick<Socket, "id">, panes: readonly T[]): T[] {
  const m = MASTER_CONSOLE.exec(socket.id);
  if (!m) return [...panes];
  const pane = panes[Number(m[1]) - 1];
  return pane === undefined ? [] : [pane];
}

export function useScreenFaces(deck: Deck | null, life: CrewLife, awake: boolean, t: (key: string) => string): ReadonlyMap<string, ScreenView> {
  // Seat id (= screen id) → its member.
  const homes = useMemo(() => new Map([...life.homes].map(([member, seat]) => [seat, member])), [life.homes]);
  const engineering = deck?.id === "engineering";

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

  // Panes the IDE has mounted are read straight from their terminal; only the rest are polled.
  const liveGeneration = useSyncExternalStore(subscribeLiveTerminals, liveTerminalsGeneration);
  const targets = useMemo(() => {
    const list: PaneScreenTarget[] = [];
    if (engineering) {
      for (const [member, occupant] of life.panes) {
        const pane = occupant.pane;
        if (liveTerminal(pane.workspace_id, [pane.name, pane.key])) continue;
        list.push({ agentId: member, workspaceId: pane.workspace_id, key: pane.key });
      }
    }
    return chunk(list, MAX_SCREEN_TARGETS, 2);
    // liveGeneration: a pane mounting or unmounting in the IDE changes who needs polling.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineering, life.panes, liveGeneration]);
  const terminalsA = usePaneScreens(targets[0], awake, false);
  const terminalsB = usePaneScreens(targets[1], awake, false);

  const rounds = useTeamwork((s) => s.rounds);

  return useMemo(() => {
    const faces = new Map<string, ScreenView>();
    if (!deck) return faces;
    const running = Object.values(rounds).find((r) => r.running && r.lines.length > 0);
    const statusWord = (status: DutyStatus) => (status === "waiting" ? t("verse.screen.waiting") : status === "error" ? t("verse.screen.fault")
      : status === "working" ? t("verse.state.working") : t("verse.screen.standby"));

    const tileFor = (member: string): TerminalTileFace | null => {
      const occupant = life.panes.get(member);
      if (!occupant) return null;
      const crew = life.crew.get(member);
      const status = crew?.status ?? "idle";
      const screen = terminalsA.get(member) ?? terminalsB.get(member);
      return {
        header: { title: crew?.name ?? occupant.pane.name, status: statusWord(status), tone: TONE[status] },
        workspaceId: occupant.pane.workspace_id,
        names: [occupant.pane.name, occupant.pane.key],
        fallback: screen ? { cols: screen.cols, lines: screen.lines, cursor: screen.cursor, at: screen.at } : undefined,
      };
    };
    const allTiles = engineering ? [...life.panes.keys()].map(tileFor).filter((x): x is TerminalTileFace => x !== null) : [];

    for (const socket of deck.sockets) {
      if (socket.kind !== "screen") continue;
      const member = homes.get(socket.id);
      const isConsole = deck.sockets.some((s) => s.kind === "seat" && s.id === socket.id);
      if (engineering && socket.station === MASTER_STATION) {
        const tiles = masterScreenPanes(socket, allTiles);
        faces.set(socket.id, tiles.length > 0
          ? { kind: "terminals", tiles }
          : { tone: "standby", title: deck.name, status: t("verse.screen.standby"), lines: [], cursor: false });
        continue;
      }
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
      if (crew.role !== "officer") {
        const tile = tileFor(crew.id);
        if (tile) { faces.set(socket.id, { kind: "terminals", tiles: [tile] }); continue; }
      }
      const tone = TONE[crew.status];
      const lines = crew.role === "officer" ? (chats.get(crew.id)?.lines ?? []).map(chatText) : [];
      faces.set(socket.id, { tone, title: crew.name, status: statusWord(crew.status), lines: tone === "standby" ? lines.slice(-3) : lines, cursor: tone === "live" || tone === "attention" });
    }
    return faces;
  }, [deck, engineering, homes, life.crew, life.agents, life.panes, chats, terminalsA, terminalsB, rounds, t]);
}
