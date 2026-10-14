import type { TeamEntry, TeamMember, TeamThread } from "@/lib/teamThreadsApi";

/**
 * The team thread laid out as a board: one lane per member, one band per step.
 *
 * A band holds what each member contributed to one step (the three own plans
 * side by side, a master plan beside the votes on it, a build beside its
 * reviews), so who did what reads across and how the work went reads down.
 * What belongs to nobody's lane (the person's messages, notices, the outcome)
 * sits between the bands at full width.
 */

/** One step of the work; a master-plan or review round is a step of its own. */
export type BandStep = "draft" | "challenge" | "converge" | "build" | "review";

/** What a member does in a band it has not contributed to yet. */
export type CellRole = "plans" | "challenges" | "author" | "voter" | "builder" | "reviewer" | "answers" | "none";

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

/** How far the work has come, for the step rail: 0 to 5 (5 = every step done). */
export function stepsDone(thread: TeamThread): number {
  const order = ["draft", "challenge", "converge", "build", "review", "done"];
  return Math.max(0, order.indexOf(thread.phase));
}
