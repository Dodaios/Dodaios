/**
 * Thread fork and "open a pane as a thread": loaded on use, so the startup
 * bundle does not carry them.
 */
import { invalidateAgentChatSessions, json, type AgentChatSession } from "@/lib/agentChatApi";

/** A thread that continues the conversation a grid pane is having. */
export async function threadFromTerminal(
  name: string,
  workspaceId?: string | null,
): Promise<AgentChatSession> {
  const session = await json<AgentChatSession>(
    await fetch("/api/agent-chat/sessions/from-terminal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, workspace_id: workspaceId ?? null }),
    }),
    "create-failed",
  );
  invalidateAgentChatSessions();
  return session;
}

/** Copy a thread into a new one, optionally in a fresh git worktree. */
export async function forkAgentChatSession(
  sessionId: string,
  input: { worktree?: boolean; name?: string; title?: string } = {},
): Promise<AgentChatSession> {
  const session = await json<AgentChatSession>(
    await fetch(`/api/agent-chat/sessions/${encodeURIComponent(sessionId)}/fork`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    }),
    "fork-failed",
  );
  invalidateAgentChatSessions();
  return session;
}
