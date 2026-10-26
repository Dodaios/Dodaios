/**
 * The starter gallery and the template import, as the New-agent dialog reads
 * them (`dodaios/society/starters.py`, `/api/society/starters*`). Starters
 * carry no seat: the dialog sends the seat the person picked on this
 * machine, so every runtime and provider works the same way.
 */
import { useQuery } from "@tanstack/react-query";
import { fill, translate } from "@/i18n";
import type { CompanionAppearance } from "../companion/appearance";
import type { AgentRuntime } from "@/lib/societyApi";
import { requestError } from "../data";

export type StarterArea = "coding" | "research" | "inbox" | "writing" | "ops" | "personal";

export interface StarterTool {
  id: string;
  label: string;
  /** The capability exists on this machine (connected or not). */
  available: boolean;
  /** It is connected and ready; only these start ticked. */
  connected: boolean;
}

export interface TemplateSummary {
  instructions_words: number;
  instructions_rules: number;
  /** `null`: the template does not narrow skills, every skill here is usable. */
  skills: number | null;
  routines: number;
  tools: number;
  asks_before: number;
  limited_tools: boolean;
}

export interface StarterRoutine {
  title: string;
  /** A named slot (`weekday_morning`, …) the dialog turns into a sentence. */
  when: string;
  cron: string;
}

export interface Starter {
  id: string;
  area: StarterArea;
  icon: string;
  name: string;
  title: string;
  outcome: string;
  instructions: string;
  first_message: string;
  tools: StarterTool[];
  routine: StarterRoutine | null;
  summary: TemplateSummary;
}

export interface StartersResponse {
  areas: StarterArea[];
  starters: Starter[];
  total: number;
}

export interface TemplatePreview {
  ok: boolean;
  errors: string[];
  template: { name: string; title: string; instructions: string; require_approval: string[] } | null;
  summary: TemplateSummary | null;
  tools: StarterTool[];
}

/** What the dialog picked on this machine; blanks keep the backend defaults. */
export interface StarterSeat {
  provider?: string;
  model?: string;
  account_id?: string;
  runtime?: AgentRuntime;
  execution_environment?: "local" | "sandbox";
  companion?: CompanionAppearance;
}

export interface InstallStarterRequest {
  starterId?: string;
  template?: Record<string, unknown>;
  name?: string;
  tools?: string[];
  seat: StarterSeat;
  withRoutine?: boolean;
}

export interface InstallStarterResult {
  agent: Record<string, unknown> & { agent_id: string; name: string };
  created: boolean;
  renamed_from: string | null;
  first_message: string;
  routine: { id: string; title: string; next_run?: string | null } | null;
  routine_error: string | null;
}

export const STARTERS_QUERY_KEY = ["society", "starters"] as const;

/** A failed request as the dialog shows it: Hermes / OpenClaw refusing the
 *  provider stays typed (`RuntimeProviderUnsupported`), so the dialog says it
 *  in the person's language, exactly like a blank agent's create. */
async function readError(res: Response): Promise<Error> {
  const body = (await res.json().catch(() => null)) as { detail?: unknown } | null;
  return requestError(body, fill(translate("common.request_failed"), { status: res.status }));
}

export async function fetchStarters(): Promise<StartersResponse> {
  const res = await fetch("/api/society/starters", { cache: "no-store" });
  if (!res.ok) throw await readError(res);
  return res.json();
}

/** The gallery; read only once the person opens it. */
export function useStarters(enabled: boolean) {
  return useQuery({ queryKey: STARTERS_QUERY_KEY, queryFn: fetchStarters, enabled, staleTime: 60_000 });
}

export async function previewTemplate(template: Record<string, unknown>): Promise<TemplatePreview> {
  const res = await fetch("/api/society/starters/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ template }),
  });
  if (!res.ok) throw await readError(res);
  return res.json();
}

/** The person's IANA zone, for a starter routine's wall-clock schedule. */
export function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

export async function installStarter(request: InstallStarterRequest): Promise<InstallStarterResult> {
  const body: Record<string, unknown> = { seat: request.seat };
  if (request.starterId) body.starter_id = request.starterId;
  if (request.template) body.template = request.template;
  if (request.name?.trim()) body.name = request.name.trim();
  if (request.tools) body.tools = request.tools;
  if (request.withRoutine) {
    body.with_routine = true;
    body.timezone = localTimezone();
  }
  const res = await fetch("/api/society/starters/install", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await readError(res);
  return res.json();
}

/**
 * A pasted or opened template as an object, or `null` when it is not JSON.
 * A whole marketplace submission (`{kind: "agent", agent}`) is unwrapped.
 */
export function parseTemplateText(text: string): Record<string, unknown> | null {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return null;
  const record = parsed as Record<string, unknown>;
  if (record.kind === "agent" && record.agent && typeof record.agent === "object" && !Array.isArray(record.agent)) {
    return record.agent as Record<string, unknown>;
  }
  return record;
}
