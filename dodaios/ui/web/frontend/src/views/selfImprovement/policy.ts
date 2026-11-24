/**
 * Words for a coding policy on the Self-improvement page.
 *
 * A coding policy says how Dodaios hands coding work to agents in one cell:
 * the area of the work, the model, and the coding CLI with its version line
 * (dodaios/rsi/policy.py). The steering learner changes it one step at a time
 * on half of the person's requests, and the selector's gate decides
 * (docs/rsi-policy-selector.md). The backend sends what changed as a closed set
 * of kinds and the trial's numbers; every sentence is built here.
 *
 * The same rule as for the benchmark holds: the gate's lower bound is what is
 * shown as proven, never the bare difference.
 */
import { fill } from "@/i18n";
import {
  POLICY_SURFACE,
  type LearnedChange,
  type Measurement,
  type PolicyFacts,
  type PolicyValue,
} from "@/lib/selfImprovementApi";
import { fmtPercent, fmtPoints } from "./words";

type T = (key: string) => string;

/** The model name the selector records when an order named none. */
const DEFAULT_MODEL = "(default)";

export function isPolicy(change: LearnedChange): change is LearnedChange & { policy: PolicyFacts } {
  return change.surface === POLICY_SURFACE && Boolean(change.policy);
}

function asPolicy(value: unknown): PolicyValue | null {
  if (!value || typeof value !== "object") return null;
  const found = value as Partial<PolicyValue>;
  return typeof found.hold === "boolean" && typeof found.p_max === "number" && typeof found.evidence_wait_s === "number"
    ? { hold: found.hold, p_max: found.p_max, evidence_wait_s: found.evidence_wait_s, lines: Array.isArray(found.lines) ? found.lines : [] }
    : null;
}

/** The area of coding work in words; the raw name when the page has none for it. */
export function codingArea(t: T, domain: string): string {
  const key = `self_improvement.coding_area.${domain}`;
  const word = t(key);
  return word !== key ? word : domain;
}

function kindWords(t: T, kind: string, after: PolicyValue | null): string {
  switch (kind) {
    case "hold":
      return t("self_improvement.policy.hold");
    case "release":
      return t("self_improvement.policy.release");
    case "fewer_fixes":
      if (!after) return t("self_improvement.policy.other");
      if (after.p_max === 0) return t("self_improvement.policy.no_fixes");
      if (after.p_max === 1) return t("self_improvement.policy.fewer_fixes_one");
      return fill(t("self_improvement.policy.fewer_fixes_other"), { n: after.p_max });
    case "shorter_wait":
      if (!after) return t("self_improvement.policy.other");
      return fill(t("self_improvement.policy.shorter_wait"), { minutes: Math.round(after.evidence_wait_s / 60) });
    case "brief_line":
      return t("self_improvement.policy.brief_line");
    default:
      return "";
  }
}

/** Where a policy applies: "for backend work with claude-opus-5-5 in claude-cli 2.1". */
export function policyWhere(t: T, facts: PolicyFacts): string {
  const model = facts.model && facts.model !== DEFAULT_MODEL ? facts.model : t("self_improvement.policy.default_model");
  return fill(t("self_improvement.policy.where"), {
    area: codingArea(t, facts.domain || "other"),
    model,
    harness: facts.harness || "?",
  });
}

/** One plain sentence: what the policy changes, and where. */
export function policySentence(t: T, change: LearnedChange & { policy: PolicyFacts }): string {
  const after = asPolicy(change.after);
  const parts = change.policy.kinds.map((kind) => kindWords(t, kind, after)).filter(Boolean);
  const what = parts.length ? parts.join("; ") : t("self_improvement.policy.other");
  return fill(t("self_improvement.policy.sentence"), { what, where: policyWhere(t, change.policy) });
}

/** What a policy on trial has to show to be kept, fixed before its data; "" when unknown. */
export function claimWords(t: T, facts: PolicyFacts): string {
  const target = facts.claim?.target ?? "";
  if (target !== "pass" && target !== "cost" && target !== "p") return "";
  return t(`self_improvement.policy.claim_${target}`);
}

function fmtUsd(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency: "USD", maximumFractionDigits: 3 }).format(value);
}

function fmtNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
}

/**
 * The measurement that let a policy in, in one sentence:
 * "Passed 92% of 65 requests, against 65% of 65 without it (at least +5.0 points)".
 */
export function policyProof(t: T, found: Measurement | null | undefined, locale: string): string {
  if (!found || typeof found.diff !== "number" || typeof found.low !== "number") {
    return t("self_improvement.effect.none");
  }
  const counts = { n: found.n, m: found.n_reference ?? 0 };
  if (found.metric === "pass") {
    const withIt = found.arms?.candidate?.pass;
    const without = found.arms?.reference?.pass;
    if (typeof withIt !== "number" || typeof without !== "number") return t("self_improvement.effect.none");
    return fill(t("self_improvement.policy.proof_pass"), {
      ...counts,
      with: fmtPercent(withIt, locale),
      without: fmtPercent(without, locale),
      low: fmtPoints(found.low, locale),
    });
  }
  if (found.metric === "cost") {
    return fill(t("self_improvement.policy.proof_cost"), {
      ...counts,
      diff: fmtUsd(found.diff, locale),
      low: fmtUsd(found.low, locale),
    });
  }
  if (found.metric === "p") {
    return fill(t("self_improvement.policy.proof_p"), {
      ...counts,
      diff: fmtNumber(found.diff, locale),
      low: fmtNumber(found.low, locale),
    });
  }
  return t("self_improvement.effect.none");
}
