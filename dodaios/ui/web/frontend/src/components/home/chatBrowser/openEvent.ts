/**
 * Asks the chat's browser stage to show an agent's browser large. A stage
 * that shows this agent's open browser takes the request (`preventDefault`);
 * when none does, the caller falls back to the agent's own card.
 */
export const OPEN_AGENT_BROWSER_EVENT = "dodaios:open-agent-browser";

export interface OpenAgentBrowserDetail {
  agentId: string;
  /** The person takes control of the page at once (an approval card's "Take over"). */
  takeover?: boolean;
}

/** True when a chat browser stage took the request. */
export function requestAgentBrowserStage(agentId: string, options: { takeover?: boolean } = {}): boolean {
  const detail: OpenAgentBrowserDetail = { agentId, ...options };
  const event = new CustomEvent(OPEN_AGENT_BROWSER_EVENT, { detail, cancelable: true });
  return !window.dispatchEvent(event);
}
