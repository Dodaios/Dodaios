// REST client for the Agentic IDE's resource view: one poll that answers
// "who is using this computer", and the one action the view offers.
// Same-origin fetch with `no-store`: a cached reading of a live meter is a lie.

/** Load of a set of processes. Processor share is of the whole machine, 0-100. */
export interface ResourceLoad {
  cpu_percent: number;
  memory_mb: number;
  processes: number;
  threads: number;
  /** Dedicated graphics memory, 0 where the platform does not report it per process. */
  gpu_memory_mb: number;
  gpu_percent: number;
}

/** What an agent started: an MCP server, a test run, a build, a shell. */
export interface ResourceTool extends ResourceLoad {
  /** Handles accepted by {@link endResourceTools}; empty for the folded tail. */
  ids: string[];
  category: string;
  label: string;
  /** How many times the same tool runs; they are shown as one line. */
  instances: number;
  started_at: number;
}

/** A program outside the agent's own processes that one of its tools talks to. */
export interface ResourceLinkedApp extends ResourceLoad {
  id: string;
  label: string;
  port: number;
  /** The tool holding the connection, when it is one of the agent's tools. */
  via: string;
  via_category: string;
  /** How many other agents use the same program. */
  shared_with: number;
}

export interface ResourceAgent extends ResourceLoad {
  id: string;
  /** "pane" | "thread" | "background" (started by this app) | "external". */
  kind: string;
  agent: string;
  agent_label: string;
  label: string;
  detail: string;
  workspace: string;
  pid: number;
  started_at: number;
  /** The CLI itself, without what it started. */
  runtime: ResourceLoad;
  tools: ResourceTool[];
  linked: ResourceLinkedApp[];
}

export interface ResourceGpu {
  name: string;
  util_percent: number;
  memory_used_mb: number;
  memory_total_mb: number;
  per_process: boolean;
}

export interface ResourceSystem {
  cpu_percent: number;
  per_core: number[];
  cores_logical: number;
  cores_physical: number;
  memory_total_mb: number;
  memory_used_mb: number;
  memory_percent: number;
  swap_total_mb: number;
  swap_used_mb: number;
  processes: number;
  /** null when this machine offers no reading of its graphics card. */
  gpu: ResourceGpu | null;
}

export type ResourceGroupKey = "agents" | "linked" | "app" | "other";

export interface ResourceHistory {
  /** Unix seconds of each sample, oldest first. */
  t: number[];
  /** "cpu", "memory", "gpu" and "<cpu|memory>.<group>", all as percent of the machine. */
  series: Record<string, number[]>;
  /** Per agent: processor percent and memory in MB; null before the agent existed. */
  agents: Record<string, { cpu: (number | null)[]; memory: (number | null)[] }>;
}

export interface ResourceSnapshot {
  ts: number;
  interval_s: number;
  platform: string;
  system: ResourceSystem;
  groups: Record<ResourceGroupKey, ResourceLoad>;
  agents: ResourceAgent[];
  app: ResourceLoad & { parts: (ResourceLoad & { role: string })[] };
  other: ResourceLoad & { top: (ResourceLoad & { name: string })[] };
  history: ResourceHistory;
}

const BASE = "/api/agentic-ide/resources";

async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    /* no JSON body */
  }
  return `HTTP ${response.status}`;
}

export async function fetchResources(signal?: AbortSignal): Promise<ResourceSnapshot> {
  const response = await fetch(BASE, { cache: "no-store", signal });
  if (!response.ok) throw new Error(await detail(response));
  return (await response.json()) as ResourceSnapshot;
}

/** End tools an agent started. Returns how many processes were ended. */
export async function endResourceTools(ids: string[]): Promise<number> {
  const response = await fetch(`${BASE}/end`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) throw new Error(await detail(response));
  return ((await response.json()) as { ended: number }).ended;
}
