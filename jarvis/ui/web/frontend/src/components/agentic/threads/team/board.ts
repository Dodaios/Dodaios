import type { TeamEntry, TeamMember, TeamThread } from "@/lib/teamThreadsApi";

/**
 * The team thread laid out as a board: one lane per member, one band per step.
 *
 * A band holds what each member contributed to one step (the three own plans
 * side by side, a master plan beside the votes on it, a build beside its
 * reviews), so who did what reads across and how the work went reads down.
 * What belongs to nobody's lane (the person's messages, notices, the outcome)
 * sits between the bands at full width.
 *
 * In the planner-and-builder mode a band is a plan round (the plan beside its
 * reviews), a step of the plan (each build beside its review, fixes below in
 * the same lanes) or a round of the final review.
 */

/** One step of the work; a master-plan or review round is a step of its own. */
export type BandStep = "draft" | "challenge" | "converge" | "build" | "review" | "planning" | "step" | "final";

/** What a member does in a band it has not contributed to yet. */
export type CellRole =
  | "plans" | "challenges" | "author" | "voter" | "builder" | "reviewer" | "answers"
  | "writes_plan" | "reviews_plan" | "builds_step" | "reviews_step" | "final_reviewer"
  | "none";

export interface BandCell {
  member: TeamMember;
  /** What the member filed in this step, oldest first. */
  entries: TeamEntry[];
  /** The member's turn for this step is running right now. */
  live: boolean;
  role: CellRole;
}

export interface StepBand {
  type: "step";
  key: string;
  step: BandStep;
  round: number;
  cells: BandCell[];
  /** The step the team is in right now. */
  current: boolean;
  /** A band of one plan step: its number, title and plan version. */
  number?: number;
  title?: string;
  version?: number;
}

export interface NoteBand {
  type: "note";
  key: string;
  entry: TeamEntry;
}

export type Band = StepBand | NoteBand;

const STEP_OF: Partial<Record<TeamEntry["kind"], BandStep>> = {
  draft: "draft",
  critique: "challenge",
  plan: "converge",
  vote: "converge",
  build: "build",
  review: "review",
  fix: "review",
};

const bandKey = (step: BandStep, round: number) => (step === "converge" || step === "review" ? `${step}:${round}` : step);

function roleIn(step: BandStep, member: TeamMember, thread: TeamThread, entries: TeamEntry[]): CellRole {
  if (member.state === "left") return "none";
  if (step === "draft") return "plans";
  if (step === "challenge") return "challenges";
  if (step === "converge") {
    const plan = entries.find((entry) => entry.kind === "plan");
    if (!plan) return member.working ? "author" : "voter";
    return plan.author === member.member_id ? "author" : "voter";
  }
  if (step === "build") return thread.builder === member.member_id ? "builder" : "reviewer";
  return thread.builder === member.member_id ? "answers" : "reviewer";
}

/** The bands of a thread in the order the work happened. */
export function buildBoard(thread: TeamThread): Band[] {
  if (thread.mode === "planner_builder") return buildPlanBoard(thread);
  const bands: Band[] = [];
  const steps = new Map<string, { band: StepBand; entries: TeamEntry[] }>();

  const stepBand = (step: BandStep, round: number) => {
    const key = bandKey(step, round);
    let found = steps.get(key);
    if (!found) {
      found = { band: { type: "step", key, step, round, cells: [], current: false }, entries: [] };
      steps.set(key, found);
      bands.push(found.band);
    }
    return found;
  };

  for (const entry of thread.entries) {
    const step = STEP_OF[entry.kind];
    if (step) stepBand(step, entry.round).entries.push(entry);
    else bands.push({ type: "note", key: `note:${entry.seq}`, entry });
  }

  // The step being worked on shows from its first second, before anything is filed.
  const running = thread.state === "running";
  if (thread.phase !== "done") {
    const step = thread.phase as BandStep;
    const round = step === "converge" ? Math.max(1, thread.rounds.plan) : step === "review" ? Math.max(1, thread.rounds.review) : 0;
    const current = running || steps.has(bandKey(step, round)) ? stepBand(step, round) : null;
    if (current) current.band.current = thread.state !== "stopped" && thread.state !== "failed";
  }

  for (const { band, entries } of steps.values()) {
    band.cells = thread.members.map((member) => {
      const mine = entries.filter((entry) => entry.author === member.member_id);
      return {
        member,
        entries: mine,
        // A member works on the current step; its earlier bands are settled.
        live: band.current && running && member.working,
        role: roleIn(band.step, member, thread, entries),
      };
    });
  }
  return bands;
}

interface Place {
  key: string;
  step: BandStep;
  round: number;
  number?: number;
  title?: string;
  version?: number;
}

/** Where a planner-and-builder entry sits; null for what spans the board. */
function placeOf(entry: TeamEntry): Place | null {
  const payload = entry.payload;
  switch (entry.kind) {
    case "plan_version":
    case "plan_review":
      return { key: `planning:${entry.round}`, step: "planning", round: entry.round };
    case "step_build":
    case "step_review":
      return {
        key: `step:${payload.version ?? 0}:${payload.number ?? 0}`, step: "step", round: 0,
        number: payload.number, title: payload.title, version: payload.version,
      };
    case "review":
    case "fix":
      return { key: `final:${entry.round}`, step: "final", round: entry.round };
    default:
      return null;
  }
}

/** The band the team works in right now, before anything is filed in it. */
function currentPlace(thread: TeamThread): Place | null {
  if (thread.phase === "planning") {
    const round = Math.max(1, thread.rounds.plan_round ?? 1);
    return { key: `planning:${round}`, step: "planning", round };
  }
  if (thread.phase === "steps" && thread.plan) {
    const open = thread.plan.steps.find((step) => step.number === thread.rounds.step)
      ?? thread.plan.steps.find((step) => step.status !== "accepted");
    if (!open) return null;
    return {
      key: `step:${thread.plan.version}:${open.number}`, step: "step", round: 0,
      number: open.number, title: open.title, version: thread.plan.version,
    };
  }
  if (thread.phase === "final") {
    const round = Math.max(1, thread.rounds.final ?? 1);
    return { key: `final:${round}`, step: "final", round };
  }
  return null;
}

function planRole(step: BandStep, member: TeamMember, thread: TeamThread): CellRole {
  if (member.state === "left") return "none";
  // Without a reviewer the builder reads the plan and the planner checks each step.
  const reviewers = thread.members.some((other) => other.state === "active" && other.role === "reviewer");
  if (step === "planning") {
    if (member.role === "planner") return "writes_plan";
    return member.role === "reviewer" || (!reviewers && member.role === "builder") ? "reviews_plan" : "none";
  }
  if (step === "step") {
    if (member.role === "builder") return "builds_step";
    return member.role === "reviewer" || (!reviewers && member.role === "planner") ? "reviews_step" : "none";
  }
  return member.role === "builder" ? "answers" : "final_reviewer";
}

/** The planner-and-builder board: plan rounds, one band per plan step, the final review. */
function buildPlanBoard(thread: TeamThread): Band[] {
  const bands: Band[] = [];
  const steps = new Map<string, { band: StepBand; entries: TeamEntry[] }>();
  const stepBand = (place: Place) => {
    let found = steps.get(place.key);
    if (!found) {
      found = { band: { type: "step", current: false, cells: [], ...place }, entries: [] };
      steps.set(place.key, found);
      bands.push(found.band);
    }
    return found;
  };

  for (const entry of thread.entries) {
    const place = placeOf(entry);
    if (place) stepBand(place).entries.push(entry);
    else bands.push({ type: "note", key: `note:${entry.seq}`, entry });
  }

  const running = thread.state === "running";
  const now = currentPlace(thread);
  if (now) {
    const current = running || steps.has(now.key) ? stepBand(now) : null;
    if (current) current.band.current = thread.state !== "stopped" && thread.state !== "failed";
  }

  for (const { band, entries } of steps.values()) {
    band.cells = thread.members.map((member) => ({
      member,
      entries: entries.filter((entry) => entry.author === member.member_id),
      live: band.current && running && member.working,
      role: planRole(band.step, member, thread),
    }));
  }
  return bands;
}

/** A contribution in a few plain lines: Markdown marks, code fences and blank lines dropped. */
export function gist(text: string, maxChars = 320): string {
  const lines: string[] = [];
  let fenced = false;
  for (const raw of (text ?? "").split(/\r?\n/)) {
    const line = raw.trim();
    if (line.startsWith("```")) {
      fenced = !fenced;
      continue;
    }
    if (fenced || !line) continue;
    const plain = line
      .replace(/^#{1,6}\s+/, "")
      .replace(/^[-*+]\s+/, "")
      .replace(/^>\s?/, "")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/__([^_]+)__/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .trim();
    if (plain) lines.push(plain);
    if (lines.join(" ").length >= maxChars) break;
  }
  const joined = lines.join(" · ");
  return joined.length > maxChars ? `${joined.slice(0, maxChars - 1).trimEnd()}…` : joined;
}

/** How far the work has come, for the step rail: 0 to 5 (5 = every step done); 0 to 3 for planner and builder. */
export function stepsDone(thread: TeamThread): number {
  const order = thread.mode === "planner_builder"
    ? ["planning", "steps", "final", "done"]
    : ["draft", "challenge", "converge", "build", "review", "done"];
  return Math.max(0, order.indexOf(thread.phase));
}
