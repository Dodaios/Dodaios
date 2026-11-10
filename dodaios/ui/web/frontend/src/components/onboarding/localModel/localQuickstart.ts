/**
 * "Use a free local model" — one click from nothing to a local model that
 * answers, written as a pure async flow so it can be tested against a faked
 * `fetch` and driven from a hook (`useLocalQuickstart`).
 *
 * The steps, each reported through `report`:
 *
 *  1. checking    — `GET …/local-models/quickstart`: this machine's memory,
 *                   the model that fits it (an installed one first), and
 *                   whether the Ollama runtime is installed and running.
 *  2. installing  — Ollama is installed when it is missing. The button that
 *                   starts this flow says so, so the click is the consent.
 *  3. starting    — a stopped server is started; the plan is then read
 *                   again, because only a running server shows what is
 *                   already downloaded.
 *  4. downloading — the model is pulled when it is not on disk yet, with the
 *                   server's own progress. A dropped connection is retried;
 *                   Ollama keeps the finished parts, so a retry resumes.
 *  5. selecting   — the model is pinned on the Ollama provider and Ollama
 *                   becomes the brain. A brain that is still starting (503)
 *                   is asked again a few times instead of failing.
 *
 * A pinned model is the cure for the "no API key" answer a selected Ollama
 * without a model used to give (issue #836): the voice chain and the chat
 * both see a concrete model the moment this flow ends.
 */
import {
  modelPullStatus,
  ollamaRuntime,
  ollamaRuntimeInstall,
  ollamaRuntimeStart,
  saveBrainProviderModel,
  startModelPull,
  switchBrainProvider,
} from "@/hooks/useProviders";

export const LOCAL_PROVIDER = "ollama";

export interface QuickstartPlan {
  model: string;
  label: string;
  size_gb: number | null;
  installed: boolean;
  fit: string;
  fit_note: string;
  reason: string;
  hardware: {
    memory_gb: number | null;
    accelerator_gb: number;
    accelerator_source: string;
    summary: string;
  };
  runtime: {
    installed: boolean;
    running: boolean;
    starting: boolean;
    host_kind: string;
    detail: string;
  };
  server_reachable: boolean;
}

export type QuickstartStep =
  | { phase: "checking" }
  | { phase: "installing"; percent?: number }
  | { phase: "starting" }
  | { phase: "downloading"; plan: QuickstartPlan; percent?: number }
  | { phase: "selecting"; plan: QuickstartPlan }
  | { phase: "done"; plan: QuickstartPlan; probeFailed: boolean }
  | { phase: "error"; reason: QuickstartFailure; detail: string };

/** Why the flow stopped; each has its own sentence in `first_run.local_model`. */
export type QuickstartFailure =
  | "remote"
  | "install"
  | "start"
  | "no_model"
  | "download"
  | "select"
  | "unknown";

export class QuickstartError extends Error {
  constructor(
    readonly reason: QuickstartFailure,
    detail: string,
  ) {
    super(detail);
    this.name = "QuickstartError";
  }
}

export interface RunQuickstartOptions {
  report: (step: QuickstartStep) => void;
  /** False once the caller unmounted; the flow then stops writing. */
  alive: () => boolean;
  /** Milliseconds between polls (tests: 0). */
  pollMs?: number;
  /** Extra tries for a dropped download or a brain that is still starting. */
  retries?: number;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export async function getQuickstartPlan(): Promise<QuickstartPlan> {
  const res = await fetch(`/api/providers/${LOCAL_PROVIDER}/local-models/quickstart`);
  const body = (await res.json().catch(() => ({}))) as Partial<QuickstartPlan> & { detail?: string };
  if (!res.ok) throw new Error(body.detail ?? `HTTP ${res.status}`);
  return body as QuickstartPlan;
}

async function installRuntime(
  report: (step: QuickstartStep) => void,
  alive: () => boolean,
  pollMs: number,
): Promise<void> {
  const first = await ollamaRuntimeInstall(LOCAL_PROVIDER);
  if (first.phase === "error" || (first.started === false && first.error))
    throw new QuickstartError("install", first.error || first.message || "");
  report({ phase: "installing", percent: first.percent });
  for (;;) {
    if (!alive()) return;
    await sleep(pollMs);
    const { install } = await ollamaRuntime(LOCAL_PROVIDER);
    if (!install.running) {
      if (install.phase === "error") throw new QuickstartError("install", install.error || "");
      return;
    }
    report({ phase: "installing", percent: install.percent });
  }
}

async function withRetries<T>(
  tries: number,
  pollMs: number,
  run: () => Promise<T>,
  retryable: (err: unknown) => boolean = () => true,
): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await run();
    } catch (err) {
      if (attempt >= tries || !retryable(err)) throw err;
      await sleep(pollMs * (attempt + 1));
    }
  }
}

async function pullModel(
  plan: QuickstartPlan,
  report: (step: QuickstartStep) => void,
  alive: () => boolean,
  pollMs: number,
): Promise<void> {
  const first = await startModelPull(LOCAL_PROVIDER, plan.model);
  if (first.state === "done") return;
  if (first.state === "error") throw new QuickstartError("download", first.message);
  report({ phase: "downloading", plan, percent: 0 });
  for (;;) {
    if (!alive()) return;
    await sleep(pollMs);
    const pull = await modelPullStatus(LOCAL_PROVIDER, plan.model);
    if (pull.state === "done") return;
    if (pull.state === "error") throw new QuickstartError("download", pull.message);
    report({ phase: "downloading", plan, percent: pull.percent });
  }
}

/** True for a brain that is still building (the switch route's 503). */
function brainStarting(err: unknown): boolean {
  return /still starting|HTTP 503/i.test(message(err));
}

export async function runLocalQuickstart({
  report,
  alive,
  pollMs = 2000,
  retries = 2,
}: RunQuickstartOptions): Promise<QuickstartPlan | null> {
  report({ phase: "checking" });
  let plan = await getQuickstartPlan();
  if (!alive()) return null;

  if (!plan.runtime.running) {
    if (plan.runtime.host_kind === "remote") throw new QuickstartError("remote", plan.runtime.detail);
    if (!plan.runtime.installed) {
      report({ phase: "installing" });
      await installRuntime(report, alive, pollMs);
      if (!alive()) return null;
    }
    report({ phase: "starting" });
    try {
      await withRetries(retries, pollMs, () => ollamaRuntimeStart(LOCAL_PROVIDER));
    } catch (err) {
      throw new QuickstartError("start", message(err));
    }
    if (!alive()) return null;
    // Only a running server shows what is already downloaded.
    report({ phase: "checking" });
    plan = await getQuickstartPlan();
    if (!alive()) return null;
  }

  if (!plan.model) throw new QuickstartError("no_model", "");

  if (!plan.installed) {
    await withRetries(retries, pollMs, () => pullModel(plan, report, alive, pollMs), (err) => {
      // A name Ollama does not know will not appear on a second try.
      return !/does not know a model/i.test(message(err));
    });
    if (!alive()) return null;
  }

  report({ phase: "selecting", plan });
  let probeFailed = false;
  try {
    const saved = await saveBrainProviderModel(LOCAL_PROVIDER, plan.model);
    // A cold model can miss the one-token probe while it loads; the pick is
    // saved either way and the first answer simply takes longer.
    probeFailed = Boolean(saved.probe && saved.probe.status !== "ok");
    await withRetries(retries + 3, pollMs, () => switchBrainProvider(LOCAL_PROVIDER), brainStarting);
  } catch (err) {
    throw new QuickstartError("select", message(err));
  }
  if (!alive()) return null;
  report({ phase: "done", plan, probeFailed });
  return plan;
}

/** Percent for the bar, or null while the phase has no measurable progress. */
export function stepPercent(step: QuickstartStep | null): number | null {
  if (!step) return null;
  if (step.phase === "downloading" || step.phase === "installing")
    return typeof step.percent === "number" ? Math.max(0, Math.min(100, Math.round(step.percent))) : null;
  if (step.phase === "done") return 100;
  return null;
}
