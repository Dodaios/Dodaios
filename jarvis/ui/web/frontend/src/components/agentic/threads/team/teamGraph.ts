import type { Translate } from "@/components/agentchat/traceEntries";
import { plural } from "@/components/agentchat/traceEntries";
import { fill } from "@/i18n";
import type { TeamEntry, TeamMember, TeamThread } from "@/lib/teamThreadsApi";
import { buildBoard, type StepBand } from "./board";

/**
 * The team room's canvas as data: who works with whom, and what went across.
 *
 * Every line on the canvas is a real handoff the coordinator made, read from
 * the filed entries: a plan that went to the members who voted on it, a vote
 * back to the plan's author, a change to its reviewers, findings back to the
 * builder, the person's words to every member. One line per direction between
 * two nodes carries all of its exchanges; its label says the newest one.
 *
 * A line is `live` while a member is working on what came across it, `current`
 * when its newest exchange belongs to the step the team is in (or ended in),
 * or the step before it (what the current step works from), and `past`
 * otherwise. The layout is fixed per team size, so nothing moves
 * while the team works.
 */

export const YOU = "you";

export type ExchangeKind =
  | "task" | "message" | "own_plan" | "critique" | "master_plan" | "vote" | "change" | "review" | "fix"
  | "plan_version" | "plan_review" | "step" | "step_review" | "plan_change";

export interface Exchange {
  seq: number;
  from: string;
  to: string;
  kind: ExchangeKind;
  entry: TeamEntry;
  /** A verdict reads as agreement (approves, agrees), as an objection, or as neither. */
  tone: "neutral" | "positive" | "negative";
}

export type EdgeTier = "live" | "current" | "past";

export interface GraphEdge {
  id: string;
  from: string;
  to: string;
  /** Oldest first. */
  exchanges: Exchange[];
  tier: EdgeTier;
}

export interface GraphNode {
  id: string;
  kind: "you" | "member";
  member?: TeamMember;
  /** The node's centre on the canvas. */
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TeamGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export const MEMBER_NODE = { width: 248, height: 88 } as const;
export const YOU_NODE = { width: 176, height: 48 } as const;

/**
 * Member centres per team size: a pair side by side, three as a triangle, four
 * as a trapezoid whose lower pair sits inside the upper one, so the person's
 * lines to it pass between the upper members rather than through them.
 */
const SPOTS: Record<number, [number, number][]> = {
  1: [[0, 200]],
  2: [[-200, 200], [200, 200]],
  3: [[-230, 190], [230, 190], [0, 410]],
  4: [[-340, 190], [340, 190], [-170, 430], [170, 430]],
};

export const edgeId = (from: string, to: string) => `${from}->${to}`;

function tone(entry: TeamEntry): Exchange["tone"] {
  const payload = entry.payload;
  if (entry.kind === "vote" || entry.kind === "plan_review") return payload.agree ? "positive" : "negative";
  if (entry.kind === "review" || entry.kind === "step_review") return payload.approve ? "positive" : "negative";
  if (entry.kind === "step_build" && payload.status === "blocked") return "negative";
  return "neutral";
}

export function buildGraph(thread: TeamThread): TeamGraph {
  const members = thread.members;
  const ids = new Set(members.map((member) => member.member_id));
  const entries = thread.entries;
  const edges = new Map<string, GraphEdge>();
  const firstTask = entries.find((entry) => entry.kind === "user");

  // A member that left only counts as a reader of what it could still have read.
  const lastFiled = new Map<string, number>();
  for (const entry of entries) lastFiled.set(entry.author, entry.seq);
  const reads = (member: TeamMember, seq: number) => member.state === "active" || (lastFiled.get(member.member_id) ?? 0) > seq;
  const othersAt = (author: string, seq: number) =>
    members.filter((member) => member.member_id !== author && reads(member, seq)).map((member) => member.member_id);

  const edge = (from: string, to: string): GraphEdge | null => {
    if (from === to || (from !== YOU && !ids.has(from)) || !ids.has(to)) return null;
    const id = edgeId(from, to);
    let found = edges.get(id);
    if (!found) {
      found = { id, from, to, exchanges: [], tier: "past" };
      edges.set(id, found);
    }
    return found;
  };
  const send = (from: string, to: string, kind: ExchangeKind, entry: TeamEntry) => {
    const line = edge(from, to);
    if (line && !line.exchanges.some((item) => item.seq === entry.seq && item.kind === kind)) {
      line.exchanges.push({ seq: entry.seq, from, to, kind, entry, tone: tone(entry) });
    }
  };
  const authorOf = (seq: number | undefined, kind: TeamEntry["kind"], before: number) => {
    const exact = seq ? entries.find((entry) => entry.seq === seq) : undefined;
    return (exact ?? [...entries].reverse().find((entry) => entry.kind === kind && entry.seq < before))?.author;
  };

  const planned = thread.mode === "planner_builder";
  const roleHolders = (role: TeamMember["role"]) =>
    members.filter((member) => member.role === role && member.state === "active").map((member) => member.member_id);
  const planner = roleHolders("planner")[0] ?? members.find((member) => member.role === "planner")?.member_id ?? "";
  const builder = thread.builder || roleHolders("builder")[0] || "";
  const reviewers = roleHolders("reviewer");
  // Without a reviewer the builder reads the plan and the planner checks each step.
  const planReaders = [...new Set([...(reviewers.length ? reviewers : []), builder])].filter(Boolean);
  const stepReaders = reviewers.length ? reviewers : [planner].filter(Boolean);
  const reviewersOf = (round: number, kind: TeamEntry["kind"], fallback: string) => {
    const found = entries.filter((entry) => entry.kind === kind && entry.round === round).map((entry) => entry.author);
    return found.length ? found : othersAt(fallback, 0);
  };

  for (const entry of entries) {
    const from = entry.author;
    const payload = entry.payload;
    switch (entry.kind) {
      case "user":
        for (const to of othersAt(YOU, entry.seq)) send(YOU, to, entry === firstTask ? "task" : "message", entry);
        break;
      case "draft":
        for (const to of othersAt(from, entry.seq)) send(from, to, "own_plan", entry);
        break;
      case "critique": {
        const author = entries.find((item) => item.kind === "plan" && item.round === 1)?.author;
        if (author) send(from, author, "critique", entry);
        break;
      }
      case "plan":
        for (const to of othersAt(from, entry.seq)) send(from, to, "master_plan", entry);
        break;
      case "vote": {
        const author = authorOf(payload.plan_seq, "plan", entry.seq);
        if (author) send(from, author, "vote", entry);
        break;
      }
      case "build":
        for (const to of othersAt(from, entry.seq)) send(from, to, "change", entry);
        break;
      case "review":
        send(from, builder || authorOf(undefined, "build", entry.seq) || "", "review", entry);
        break;
      case "fix":
        for (const to of reviewersOf(entry.round, "review", from)) send(from, to, "fix", entry);
        break;
      case "plan_version":
        if (payload.valid !== false) for (const to of planReaders) send(from, to, "plan_version", entry);
        break;
      case "plan_review": {
        const author = authorOf(payload.plan_seq, "plan_version", entry.seq) ?? planner;
        send(from, author, "plan_review", entry);
        break;
      }
      case "step_build":
        for (const to of stepReaders) send(from, to, "step", entry);
        if ((payload.status === "blocked" || payload.plan_change) && planner && !stepReaders.includes(planner)) {
          send(from, planner, "plan_change", entry);
        }
        break;
      case "step_review":
        send(from, builder, "step_review", entry);
        break;
      default:
        break;
    }
  }

  // What each working member is working on, as the lines it came across.
  const live = new Set<string>();
  const flow = (from: string, to: string, kind?: ExchangeKind, entry?: TeamEntry) => {
    if (kind && entry) send(from, to, kind, entry);
    const line = edges.get(edgeId(from, to));
    if (line && line.exchanges.length) live.add(line.id);
  };
  if (thread.state === "running") {
    for (const member of members) {
      if (!member.working || member.state !== "active") continue;
      const me = member.member_id;
      const lastOf = (kind: TeamEntry["kind"], test: (entry: TeamEntry) => boolean = () => true) =>
        [...entries].reverse().find((entry) => entry.kind === kind && test(entry));
      if (!planned) {
        if (thread.phase === "draft") {
          if (firstTask) flow(YOU, me, "task", firstTask);
        } else if (thread.phase === "challenge") {
          for (const draft of entries.filter((entry) => entry.kind === "draft" && entry.author !== me)) flow(draft.author, me, "own_plan", draft);
        } else if (thread.phase === "converge") {
          const plan = lastOf("plan", (entry) => entry.round === Math.max(1, thread.rounds.plan));
          if (plan && plan.author !== me) flow(plan.author, me);
          else {
            for (const critique of entries.filter((entry) => entry.kind === "critique" && entry.author !== me)) flow(critique.author, me, "critique", critique);
            const earlier = lastOf("plan", (entry) => entry.round === thread.rounds.plan - 1);
            for (const vote of entries.filter((entry) => entry.kind === "vote" && !entry.payload.agree && earlier && entry.payload.plan_seq === earlier.seq)) {
              flow(vote.author, me, "vote", vote);
            }
          }
        } else if (thread.phase === "review") {
          if (me !== builder) flow(builder, me);
          else {
            for (const review of entries.filter((entry) => entry.kind === "review" && entry.round === thread.rounds.review && !entry.payload.approve)) {
              flow(review.author, me);
            }
          }
        }
        continue;
      }
      if (thread.phase === "planning") {
        if (me === planner) {
          const version = lastOf("plan_version", (entry) => entry.payload.valid !== false);
          const since = version?.seq ?? 0;
          const asks = entries.filter((entry) => entry.seq > since && (
            (entry.kind === "plan_review" && !entry.payload.agree)
            || (entry.kind === "step_build" && (entry.payload.status === "blocked" || Boolean(entry.payload.plan_change)))));
          for (const ask of asks) flow(ask.author, me);
          if (!asks.length && firstTask) flow(YOU, me, "task", firstTask);
        } else if (planner) flow(planner, me);
      } else if (thread.phase === "steps") {
        if (me === builder) {
          const number = thread.rounds.step ?? 0;
          const review = lastOf("step_review", (entry) => entry.payload.number === number);
          const build = lastOf("step_build", (entry) => entry.payload.number === number);
          if (review && !review.payload.approve && (!build || review.seq > build.seq)) flow(review.author, me);
          else if (planner) flow(planner, me);
        } else flow(builder, me);
      } else if (thread.phase === "final") {
        if (me === builder) {
          for (const review of entries.filter((entry) => entry.kind === "review" && entry.round === (thread.rounds.final ?? 1) && !entry.payload.approve)) {
            flow(review.author, me);
          }
        } else flow(builder, me);
      }
    }
  }

  // What the step the team is in (or ended in) exchanged.
  const bands = buildBoard(thread).filter((band): band is StepBand => band.type === "step");
  const focus = bands.find((band) => band.current) ?? bands[bands.length - 1];
  const at = focus ? bands.indexOf(focus) : -1;
  // The step the team is in, and the step whose results it works from.
  const focusSeqs = new Set(bands.slice(Math.max(0, at - 1), at + 1)
    .flatMap((band) => band.cells.flatMap((cell) => cell.entries.map((entry) => entry.seq))));
  // The person's words count as current from the start of that earlier step on.
  const earlier = at > 0 ? bands[at - 1].cells.flatMap((cell) => cell.entries.map((entry) => entry.seq)) : [];
  const since = earlier.length ? Math.min(...earlier) : 0;
  for (const line of edges.values()) {
    line.exchanges.sort((left, right) => left.seq - right.seq);
    const latest = line.exchanges[line.exchanges.length - 1];
    line.tier = live.has(line.id) ? "live"
      : latest && (focusSeqs.has(latest.seq) || (line.from === YOU && latest.seq >= since))
        ? "current" : "past";
  }

  const spots = SPOTS[Math.min(4, Math.max(1, members.length))] ?? SPOTS[4];
  const nodes: GraphNode[] = [
    { id: YOU, kind: "you", x: 0, y: 0, ...YOU_NODE },
    ...members.slice(0, 4).map((member, index): GraphNode => ({
      id: member.member_id, kind: "member", member, x: spots[index][0], y: spots[index][1], ...MEMBER_NODE,
    })),
  ];
  return { nodes, edges: [...edges.values()].filter((line) => line.exchanges.length > 0) };
}

const TIER_RANK: Record<EdgeTier, number> = { past: 0, current: 1, live: 2 };

/** What the canvas draws: a line, or both directions of a pair as one. */
export interface CanvasLine {
  /** The line a click opens (its exchange view shows both directions anyway). */
  line: GraphEdge;
  /** The other direction, when this one line stands for both. */
  partner: GraphEdge | null;
  tier: EdgeTier;
  count: number;
}

/**
 * The lines to draw. When both directions between two nodes last carried the
 * same kind of thing at the same moment of the work (everyone sending everyone
 * their own plan), they are one straight two-way line with one label, instead
 * of two bows saying the same twice.
 */
export function canvasLines(graph: TeamGraph): CanvasLine[] {
  const byId = new Map(graph.edges.map((line) => [line.id, line]));
  const out: CanvasLine[] = [];
  const done = new Set<string>();
  for (const line of graph.edges) {
    if (done.has(line.id)) continue;
    done.add(line.id);
    const back = byId.get(edgeId(line.to, line.from));
    const mine = latestExchange(line);
    const theirs = back ? latestExchange(back) : null;
    if (back && mine && theirs && mine.kind === theirs.kind && mine.tone === theirs.tone && line.tier === back.tier) {
      done.add(back.id);
      out.push({ line, partner: back, tier: line.tier, count: line.exchanges.length + back.exchanges.length });
    } else {
      out.push({ line, partner: null, tier: line.tier, count: line.exchanges.length });
    }
  }
  return out.sort((left, right) => TIER_RANK[left.tier] - TIER_RANK[right.tier]);
}

/** The newest exchange of a line, which its label names. */
export const latestExchange = (line: GraphEdge): Exchange | null => line.exchanges[line.exchanges.length - 1] ?? null;

/** Every exchange between two nodes, both ways, oldest first. */
export function exchangesBetween(graph: TeamGraph, one: string, other: string): Exchange[] {
  return graph.edges
    .filter((line) => (line.from === one && line.to === other) || (line.from === other && line.to === one))
    .flatMap((line) => line.exchanges)
    .sort((left, right) => left.seq - right.seq);
}

const counted = (t: Translate, lang: string, key: string, count: number) =>
  fill(t(`team_threads.graph.${key}_${plural(lang, count)}`), { count });

/** What went across, in a few words: "Master plan · round 2", "3 findings · 1 blocking". */
export function exchangeLabel(exchange: Exchange, t: Translate, lang: string): string {
  const payload = exchange.entry.payload;
  const round = exchange.entry.round > 1 ? ` · ${fill(t("team_threads.round"), { round: exchange.entry.round })}` : "";
  const files = (payload.files ?? []).length;
  const withFiles = (text: string) => (files ? `${text} · ${counted(t, lang, "files", files)}` : text);
  const findings = payload.findings ?? [];
  const blocking = findings.filter((finding) => finding.severity === "blocking").length;
  const verdict = (approved: boolean | undefined) => approved
    ? t("team_threads.graph.approves")
    : findings.length
      ? [counted(t, lang, "findings", findings.length), blocking ? counted(t, lang, "blocking", blocking) : ""].filter(Boolean).join(" · ")
      : t("team_threads.graph.changes");
  const step = payload.number ? `${fill(t("team_threads.plan.step"), { number: payload.number })} · ` : "";
  switch (exchange.kind) {
    case "task": return t("team_threads.graph.task");
    case "message": return t("team_threads.graph.message");
    case "own_plan": return t("team_threads.graph.own_plan");
    case "critique": return t("team_threads.graph.critique");
    case "master_plan": return `${t("team_threads.graph.master_plan")}${round}`;
    case "vote":
    case "plan_review": {
      const objections = (payload.objections ?? []).length;
      return payload.agree ? t("team_threads.graph.agrees")
        : objections ? counted(t, lang, "objections", objections) : t("team_threads.graph.objects");
    }
    case "change": return withFiles(t("team_threads.graph.change"));
    case "fix": return withFiles(t("team_threads.graph.fix"));
    case "review": return verdict(payload.approve);
    case "plan_version": return fill(t("team_threads.plan.version_tag"), { version: payload.version ?? 1 });
    case "step": return `${step}${t(payload.status === "blocked" ? "team_threads.plan.blocked" : "team_threads.plan.done")}`;
    case "step_review": return `${step}${verdict(payload.approve)}`;
    case "plan_change": return t("team_threads.graph.plan_change");
    default: return "";
  }
}

/**
 * Member names as the room shows them: without the model the server appended
 * ("Anthropic Claude · claude-sonnet-5-5" reads "Anthropic Claude"; the model
 * has its own line); two members that would then share a name keep theirs.
 */
export function withShortNames(thread: TeamThread): TeamThread {
  const short = thread.members.map((member) => {
    const suffix = member.model ? ` · ${member.model}` : "";
    return suffix && member.name.endsWith(suffix) ? member.name.slice(0, -suffix.length).trim() : member.name;
  });
  const shared = (name: string) => short.filter((other) => other === name).length > 1;
  const names = thread.members.map((member, index) => (short[index] && !shared(short[index]) ? short[index] : member.name));
  if (names.every((name, index) => name === thread.members[index].name)) return thread;
  return { ...thread, members: thread.members.map((member, index) => ({ ...member, name: names[index] })) };
}
