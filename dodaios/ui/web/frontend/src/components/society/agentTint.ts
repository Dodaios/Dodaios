import type { CSSProperties } from "react";

import { agentColor } from "./AgentSwatch";
import type { SocietyAgent } from "./data";

type TintAgent = Pick<SocietyAgent, "figure" | "palette" | "name"> & Partial<Pick<SocietyAgent, "agentId" | "tier">>;

/**
 * The per-agent tint as a CSS custom property.
 *
 * The Agents section keeps its chrome neutral; the only decorative hue is the
 * colour a person already knows an agent by (its companion colour, or the
 * lead's gold). `agentSection.css` mixes `--agent-tint` into theme tokens with
 * `color-mix`, so a tint never replaces a surface token, it only leans on it.
 */
export function agentTint(agent: TintAgent | null | undefined): CSSProperties {
  if (!agent) return {};
  try {
    return { "--agent-tint": agentColor(agent) } as CSSProperties;
  } catch {
    // An identity without a resolvable look keeps the neutral chrome.
    return {};
  }
}
