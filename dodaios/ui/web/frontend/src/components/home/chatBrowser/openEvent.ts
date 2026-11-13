/**
 * Asks the chat's browser stage to show an agent's browser large. A stage
 * that shows this agent's open browser takes the request (`preventDefault`);
 * when none does, the caller falls back to the agent's own card.
 */
export const OPEN_AGENT_BROWSER_EVENT = "dodaios:open-agent-browser";

/** True when a chat browser stage took the request. */
export function requestAgentBrowserStage(agentId: string): boolean {
  const event = new CustomEvent(OPEN_AGENT_BROWSER_EVENT, { detail: { agentId }, cancelable: true });
  return !window.dispatchEvent(event);
}
