import { afterEach, describe, expect, it, vi } from "vitest";
import { QuickstartError, runLocalQuickstart, stepPercent, type QuickstartPlan, type QuickstartStep } from "./localQuickstart";

function plan(over: Partial<QuickstartPlan> = {}, runtime: Partial<QuickstartPlan["runtime"]> = {}): QuickstartPlan {
  return {
    model: "qwen3.5",
    label: "Qwen 3.5 9B",
    size_gb: 6.6,
    installed: false,
    fit: "comfortable",
    fit_note: "",
    reason: "",
    hardware: { memory_gb: 32, accelerator_gb: 16, accelerator_source: "nvidia", summary: "This computer: 16 GB graphics memory, 32 GB RAM." },
    runtime: { installed: true, running: true, starting: false, host_kind: "local", detail: "", ...runtime },
    server_reachable: true,
    ...over,
  };
}

type Handler = (url: string, init?: RequestInit) => { status?: number; body: unknown } | undefined;

function fakeFetch(handlers: Handler[]) {
  const calls: string[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url}`);
    for (const handler of handlers) {
      const hit = handler(url, init);
      if (hit) return new Response(JSON.stringify(hit.body), { status: hit.status ?? 200 });
    }
    throw new Error(`unexpected ${method} ${url}`);
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

function run() {
  const steps: QuickstartStep[] = [];
  const promise = runLocalQuickstart({ report: (s) => steps.push(s), alive: () => true, pollMs: 0 });
  return { steps, promise };
}

afterEach(() => vi.unstubAllGlobals());

describe("runLocalQuickstart", () => {
  it("installs Ollama, starts it, downloads the pick and makes it the brain", async () => {
    const plans = [plan({}, { installed: false, running: false }), plan()];
    let installPolls = 0;
    let pullPolls = 0;
    let switches = 0;
    const calls = fakeFetch([
      (url) => (url.endsWith("/local-models/quickstart") ? { body: plans.shift() } : undefined),
      (url, init) =>
        url.endsWith("/ollama-runtime/install") && init?.method === "POST"
          ? { body: { phase: "downloading", percent: 5, detail: "", error: "", running: true, log_tail: [], started: true } }
          : undefined,
      (url) =>
        url.endsWith("/ollama-runtime")
          ? {
              body: {
                status: {},
                install: { phase: installPolls++ ? "done" : "installing", percent: 60, detail: "", error: "", running: installPolls === 1, log_tail: [] },
              },
            }
          : undefined,
      (url) => (url.endsWith("/ollama-runtime/start") ? { body: { ok: true, status: {} } } : undefined),
      (url, init) =>
        url.endsWith("/pull") && init?.method === "POST" ? { body: { state: "running", model: "qwen3.5", message: "" } } : undefined,
      (url) =>
        url.includes("/pull/status")
          ? { body: pullPolls++ ? { state: "done", model: "qwen3.5", message: "" } : { state: "running", model: "qwen3.5", message: "", percent: 40 } }
          : undefined,
      (url, init) =>
        url.endsWith("/providers/ollama/model") && init?.method === "PUT"
          ? { body: { ok: true, provider: "ollama", model: "qwen3.5", persisted: true, applied_live: true, restart_required: false, probe: { status: "ok" } } }
          : undefined,
      (url) => {
        if (!url.endsWith("/brain/switch")) return undefined;
        // The brain is still building on the first try.
        return switches++ === 0
          ? { status: 503, body: { detail: "Brain is still starting up or unavailable" } }
          : { body: { ok: true, active: "ollama" } };
      },
    ]);
    const { steps, promise } = run();
    const result = await promise;
    expect(result?.model).toBe("qwen3.5");
    const phases = steps.map((s) => s.phase);
    expect(phases).toEqual(expect.arrayContaining(["checking", "installing", "starting", "downloading", "selecting", "done"]));
    expect(phases.indexOf("installing")).toBeLessThan(phases.indexOf("starting"));
    expect(phases.indexOf("downloading")).toBeLessThan(phases.indexOf("selecting"));
    expect(steps.some((s) => s.phase === "downloading" && s.percent === 40)).toBe(true);
    expect(calls.filter((c) => c.endsWith("/brain/switch"))).toHaveLength(2);
    // The plan is read again once the server answers.
    expect(calls.filter((c) => c.endsWith("/local-models/quickstart"))).toHaveLength(2);
    const last = steps[steps.length - 1];
    expect(last).toMatchObject({ phase: "done", probeFailed: false });
  });

  it("skips install and download when the model is already there", async () => {
    const calls = fakeFetch([
      (url) => (url.endsWith("/local-models/quickstart") ? { body: plan({ installed: true, model: "qwen3:8b", label: "qwen3:8b" }) } : undefined),
      (url) =>
        url.endsWith("/providers/ollama/model")
          ? { body: { ok: true, probe: { status: "model_unavailable" } } }
          : undefined,
      (url) => (url.endsWith("/brain/switch") ? { body: { ok: true } } : undefined),
    ]);
    const { steps, promise } = run();
    await promise;
    expect(calls.some((c) => c.includes("/pull"))).toBe(false);
    expect(calls.some((c) => c.includes("ollama-runtime"))).toBe(false);
    // A cold model that missed the probe is still selected, with a note.
    expect(steps[steps.length - 1]).toMatchObject({ phase: "done", probeFailed: true });
  });

  it("refuses a remote server with its own sentence", async () => {
    fakeFetch([
      (url) =>
        url.endsWith("/local-models/quickstart")
          ? { body: plan({}, { running: false, host_kind: "remote", detail: "No answer from 10.0.0.2." }) }
          : undefined,
    ]);
    const { promise } = run();
    await expect(promise).rejects.toMatchObject({ reason: "remote", message: "No answer from 10.0.0.2." });
  });

  it("retries a dropped download and then reports it", async () => {
    let starts = 0;
    fakeFetch([
      (url) => (url.endsWith("/local-models/quickstart") ? { body: plan() } : undefined),
      (url, init) => {
        if (!(url.endsWith("/pull") && init?.method === "POST")) return undefined;
        starts++;
        return { body: { state: "error", model: "qwen3.5", message: "Could not download qwen3.5: connection reset" } };
      },
    ]);
    const { promise } = run();
    const err = await promise.catch((e: unknown) => e);
    expect(err).toBeInstanceOf(QuickstartError);
    expect((err as QuickstartError).reason).toBe("download");
    expect(starts).toBe(3);
  });

  it("does not retry a name Ollama does not know", async () => {
    let starts = 0;
    fakeFetch([
      (url) => (url.endsWith("/local-models/quickstart") ? { body: plan() } : undefined),
      (url) => {
        if (!url.endsWith("/pull")) return undefined;
        starts++;
        return { body: { state: "error", message: "Ollama does not know a model called 'qwen3.5'." } };
      },
    ]);
    await run().promise.catch(() => undefined);
    expect(starts).toBe(1);
  });

  it("stops writing once the caller is gone", async () => {
    fakeFetch([(url) => (url.endsWith("/local-models/quickstart") ? { body: plan() } : undefined)]);
    const steps: QuickstartStep[] = [];
    const result = await runLocalQuickstart({ report: (s) => steps.push(s), alive: () => false, pollMs: 0 });
    expect(result).toBeNull();
    expect(steps.map((s) => s.phase)).toEqual(["checking"]);
  });
});

describe("stepPercent", () => {
  it("clamps and rounds download progress, and is empty for unmeasured phases", () => {
    const p = plan();
    expect(stepPercent({ phase: "downloading", plan: p, percent: 41.6 })).toBe(42);
    expect(stepPercent({ phase: "downloading", plan: p, percent: 140 })).toBe(100);
    expect(stepPercent({ phase: "downloading", plan: p })).toBeNull();
    expect(stepPercent({ phase: "starting" })).toBeNull();
    expect(stepPercent(null)).toBeNull();
  });
});
