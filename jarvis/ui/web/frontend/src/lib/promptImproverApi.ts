import { fill, translate } from "@/i18n";

/** The longest prompt a pane takes (`MAX_PROMPT_CHARS` in the backend). */
export const MAX_PROMPT_CHARS = 6000;

/** The longest instruction of the user's own that is passed to the writer. */
export const MAX_INSTRUCTION_CHARS = 1000;

export interface ImproveRequest {
  prompt: string;
  /** A provider id from the agent catalog; "" = whoever writes the IDE's task briefs. */
  provider: string;
  model: string;
  /** The user's own instruction; "" = the default one. */
  instruction: string;
  /** The pane the prompt is meant for: its repository is the writer's context. */
  workspaceId?: string;
  pane?: string;
}

export interface ImprovedPrompt {
  improved: string;
  /** `provider:<id>` for a picked model, else the brief writer's own source. */
  source: string;
  /** The writing model's own name. */
  writer: string;
  /** The repository folder the writer was told about; "" when there was none. */
  folder: string;
}

export interface PromptImproverDefaults {
  default_instruction: string;
  max_prompt_chars: number;
  max_instruction_chars: number;
}

const URL = "/api/agentic-ide/prompt-improver";

async function detail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body?.detail === "string" && body.detail) return body.detail;
  } catch {
    /* fall through */
  }
  return fill(translate("shell_errors.request_failed_status"), { status: res.status });
}

/** The instruction the writer gets when the user typed none. */
export async function fetchPromptImproverDefaults(): Promise<PromptImproverDefaults> {
  const res = await fetch(URL, { cache: "no-store" });
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as PromptImproverDefaults;
}

/** Rewrite one prompt. Nothing is sent to a pane; rejects with the server's own reason. */
export async function improvePrompt(request: ImproveRequest): Promise<ImprovedPrompt> {
  const res = await fetch(URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      prompt: request.prompt,
      provider: request.provider,
      model: request.model,
      instruction: request.instruction,
      workspace: request.workspaceId ?? null,
      pane: request.pane ?? null,
    }),
  });
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as ImprovedPrompt;
}
