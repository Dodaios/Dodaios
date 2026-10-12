/**
 * What a studio board shows: the team's name, its members with their real
 * run state, and the newest real lines of the team's chat — or an honest
 * empty state. The model is pure and tested; the drawing puts it on a canvas.
 */
import type { AgentRunState, SocietyAgent } from "../data";
import type { Studio } from "./officeLayout";
import { bubbleText } from "./officeTalk";
import type { TeamRound } from "./teamwork";

/** The live content lies this far in front of the board's own paper face (`studioBoardFace` in the layout). */
export const BOARD_LIFT_M = 0.012;
/** The canvas, in the face's proportion (2.16 m × 1.16 m). */
export const BOARD_CANVAS = { w: 1024, h: 550 } as const;

/** Boards within this camera distance are drawn; nearer than BOARD_LIVE_RANGE_M they are also kept current. */
export const BOARD_DRAW_RANGE_M = 60;
export const BOARD_LIVE_RANGE_M = 30;
/** At most this many boards are live at once: the nearest ones. */
export const MAX_LIVE_BOARDS = 3;

/**
 * Which boards to draw (their ids) and which teams to keep live (their team ids), from each board's distance to
 * the camera. A pool studio's board is drawn but never live: it has no team chat to read.
 */
export function pickBoards(boards: readonly { id: string; teamId: string | null; distance: number }[]): { drawn: Set<string>; live: Set<string> } {
  const drawn = new Set(boards.filter((b) => b.distance <= BOARD_DRAW_RANGE_M).map((b) => b.id));
  const live = new Set(boards.filter((b) => b.teamId !== null && b.distance <= BOARD_LIVE_RANGE_M)
    .sort((a, b) => a.distance - b.distance || a.id.localeCompare(b.id)).slice(0, MAX_LIVE_BOARDS).map((b) => b.teamId as string));
  return { drawn, live };
}

/** Rows that fit the member column, and chat lines the model keeps for the other one. */
export const MAX_BOARD_MEMBERS = 6;
export const MAX_BOARD_LINES = 5;

export interface BoardLabels {
  /** Title of a studio without a name of its own (the pool). */
  pool: string;
  /** "{0} members" */
  members: string;
  live: string;
  speaking: string;
  you: string;
  /** A team whose chat holds nothing yet. */
  empty: string;
  /** The pool studio: there is no team chat to show. */
  poolNote: string;
  /** The transcript has not been read yet. */
  loading: string;
  /** The transcript cannot be read right now. */
  unavailable: string;
  /** "+{0} more" */
  more: string;
  state: Record<AgentRunState, string>;
}

export interface BoardMember { id: string; name: string; state: AgentRunState; speaking: boolean }
export interface BoardLine { id: string; who: string; text: string; fromPerson: boolean }

export interface BoardModel {
  title: string;
  count: string;
  /** A round is answering right now. */
  live: boolean;
  members: BoardMember[];
  /** Members that did not fit the column. */
  hidden: number;
  lines: BoardLine[];
  /** Shown instead of chat lines when there are none. */
  note: string | null;
}

export function boardModel(
  studio: Pick<Studio, "name" | "teamId" | "members">, agents: ReadonlyMap<string, Pick<SocietyAgent, "name" | "state">>,
  round: TeamRound | undefined, labels: BoardLabels,
): BoardModel {
  // Everyone seated here, then team members who sit elsewhere (an agent can be in several teams).
  const ids = [...studio.members, ...(round?.members ?? []).filter((id) => !studio.members.includes(id))];
  const present = ids.flatMap((id) => {
    const agent = agents.get(id);
    return agent ? [{ id, name: agent.name, state: agent.state, speaking: !!round?.running && round.speakerId === id }] : [];
  });
  const lines: BoardLine[] = (round?.lines ?? []).slice(-MAX_BOARD_LINES).map((line) => ({
    id: line.id, fromPerson: line.speaker === "user",
    who: line.speaker === "user" ? labels.you : agents.get(line.speaker)?.name ?? "—",
    text: bubbleText(line.text, 170),
  }));
  let note: string | null = null;
  if (studio.teamId === null) note = labels.poolNote;
  else if (!round?.loaded && lines.length === 0) note = round?.unavailable ? labels.unavailable : labels.loading;
  else if (lines.length === 0) note = labels.empty;
  return {
    title: studio.name.trim() || labels.pool,
    count: labels.members.replace("{0}", String(present.length)),
    live: !!round?.running,
    members: present.slice(0, MAX_BOARD_MEMBERS),
    hidden: Math.max(0, present.length - MAX_BOARD_MEMBERS),
    lines: studio.teamId === null ? [] : lines,
    note,
  };
}

/** A cheap identity for "does the face need a redraw". */
export function boardSignature(model: BoardModel, labels: BoardLabels): string {
  return JSON.stringify([model.title, model.count, model.live, model.hidden, model.note,
    model.members.map((m) => [m.name, m.state, m.speaking]), model.lines.map((l) => [l.id, l.who, l.text]),
    labels.live, labels.speaking, labels.more, labels.state]);
}

/** Ink on the board's paper face: the same sheet the board shows at rest, now written on. */
const PAPER = { sheet: "#f6f3ec", dots: "rgba(60,56,50,0.16)", ink: "#1f2430", soft: "#5b6475", faint: "#8a8f98", rule: "#3b4250", live: "#2f9e5b", person: "#2f6fd0" } as const;
const STATE_COLOUR: Record<AgentRunState, string> = { working: "#2f9e5b", waiting: "#c98a12", idle: "#8a8f98", paused: "#b9bcc2" };
const FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif";

function clipped(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let cut = text;
  while (cut.length > 1 && ctx.measureText(`${cut}…`).width > maxWidth) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}…`;
}

function wrap(ctx: CanvasRenderingContext2D, text: string, width: number, maxRows: number): string[] {
  const rows: string[] = [];
  let row = "";
  for (const word of text.split(" ")) {
    const next = row ? `${row} ${word}` : word;
    if (ctx.measureText(next).width > width && row) { rows.push(row); row = word; } else row = next;
  }
  if (row) rows.push(row);
  if (rows.length <= maxRows) return rows;
  const kept = rows.slice(0, maxRows);
  kept[maxRows - 1] = clipped(ctx, `${kept[maxRows - 1]} …`, width);
  return kept;
}

export function drawStudioBoard(ctx: CanvasRenderingContext2D, model: BoardModel, labels: BoardLabels): void {
  const { w: W, h: H } = BOARD_CANVAS;
  ctx.fillStyle = PAPER.sheet;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = PAPER.dots;
  for (let y = 28; y < H; y += 47) for (let x = 28; x < W; x += 47) ctx.fillRect(x, y, 4, 4);
  // Header: the team's name, and whether a round is answering.
  ctx.fillStyle = PAPER.rule;
  ctx.fillRect(36, 90, W - 72, 4);
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.font = `600 28px ${FONT}`;
  const right = model.live ? labels.live : model.count;
  const rightW = ctx.measureText(right).width;
  if (model.live) {
    ctx.fillStyle = PAPER.live;
    ctx.beginPath();
    ctx.roundRect(W - 36 - rightW - 44, 24, rightW + 44, 44, 22);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.fillText(right, W - 36 - rightW - 22, 47);
  } else {
    ctx.fillStyle = PAPER.soft;
    ctx.fillText(right, W - 36 - rightW, 47);
  }
  ctx.fillStyle = PAPER.ink;
  ctx.font = `700 42px ${FONT}`;
  ctx.fillText(clipped(ctx, model.title, W - 72 - rightW - 80), 36, 48);

  // Left: the members and what each is really doing.
  const colW = 340, rowH = 68, top = 112;
  model.members.forEach((member, i) => {
    const y = top + i * rowH + rowH / 2;
    ctx.fillStyle = member.speaking ? PAPER.live : STATE_COLOUR[member.state];
    ctx.beginPath(); ctx.arc(50, y, 10, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = PAPER.ink;
    ctx.font = `600 29px ${FONT}`;
    ctx.fillText(clipped(ctx, member.name, colW - 60), 76, y - 12);
    ctx.fillStyle = member.speaking ? PAPER.live : PAPER.soft;
    ctx.font = `500 21px ${FONT}`;
    ctx.fillText(clipped(ctx, member.speaking ? labels.speaking : labels.state[member.state], colW - 60), 76, y + 17);
  });
  if (model.hidden > 0) {
    ctx.fillStyle = PAPER.faint;
    ctx.font = `500 22px ${FONT}`;
    ctx.fillText(labels.more.replace("{0}", String(model.hidden)), 76, H - 22);
  }
  ctx.fillStyle = "rgba(59,66,80,0.28)";
  ctx.fillRect(colW + 44, 112, 2, H - 136);

  // Right: the newest lines of the team's chat, the latest at the bottom.
  const left = colW + 72, width = W - left - 36, lineH = 31;
  if (model.lines.length === 0) {
    if (!model.note) return;
    ctx.fillStyle = PAPER.soft;
    ctx.font = `500 27px ${FONT}`;
    wrap(ctx, model.note, width, 4).forEach((row, i) => ctx.fillText(row, left, 150 + i * 36));
    return;
  }
  ctx.font = `500 25px ${FONT}`;
  const blocks = model.lines.map((line) => ({ line, rows: wrap(ctx, line.text, width, 3) }));
  let y = H - 22;
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    const { line, rows } = blocks[i];
    const height = 30 + rows.length * lineH + 10;
    if (y - height < 104) break;
    y -= height;
    ctx.fillStyle = line.fromPerson ? PAPER.person : PAPER.ink;
    ctx.font = `700 23px ${FONT}`;
    ctx.fillText(clipped(ctx, line.who, width), left, y + 15);
    ctx.fillStyle = PAPER.soft;
    ctx.font = `500 25px ${FONT}`;
    rows.forEach((row, r) => ctx.fillText(row, left, y + 30 + r * lineH + lineH / 2));
  }
}
