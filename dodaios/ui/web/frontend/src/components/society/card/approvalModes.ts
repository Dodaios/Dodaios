/**
 * Which approval modes an agent's runner can actually honour, mirrored from
 * `society_mode_supported` in `dodaios/agent_chat/permissions.py`.
 *
 * The header only offers a mode the transport can turn into a usable card;
 * the server validates the same rule again on PATCH and answers 422 when the
 * picture here was stale (a seat changed on another window, say).
 */
import { AGENT_APPROVAL_MODES, type AgentApprovalMode, type SocietyProviderRow } from "@/lib/societyApi";

import type { SocietyAgent } from "../data";

export { AGENT_APPROVAL_MODES };

/** Hermes and OpenClaw run every turn in their own loop (service.EXTERNAL_RUNTIME_RUNNERS). */
const EXTERNAL_RUNNERS: Record<string, string> = {
  hermes: "hermes-cli",
  openclaw: "openclaw-cli",
};

const ASK_RUNNERS: ReadonlySet<string> = new Set([
  "brain",
  "codex-cli",
  "claude-cli",
  "glm-cli",
  "hermes-cli",
  "openclaw-cli",
]);
// OpenClaw asks before every native call through Dodaios' gate plugin.
const ALWAYS_ASK_RUNNERS: ReadonlySet<string> = new Set(["brain", "codex-cli", "openclaw-cli"]);

/**
 * The runner that answers this agent's turns, or null while it is not known
 * yet (the provider list is still loading, or names no such provider).
 */
export function runnerFor(
  agent: Pick<SocietyAgent, "provider" | "runtime">,
  providers: readonly Pick<SocietyProviderRow, "id" | "runner">[] | undefined,
): string | null {
  const external = agent.runtime ? EXTERNAL_RUNNERS[agent.runtime] : undefined;
  if (external) return external;
  // No provider = the app's own brain.
  if (!agent.provider) return "brain";
  return providers?.find((row) => row.id === agent.provider)?.runner ?? null;
}

export function modeSupported(runner: string | null, mode: AgentApprovalMode): boolean {
  if (mode === "bypass") return true;
  if (runner === null) return false;
  if (mode === "ask") return ASK_RUNNERS.has(runner);
  if (mode === "always_ask") return ALWAYS_ASK_RUNNERS.has(runner);
  return false;
}
