import { createAgentChatStore } from "@/store/agentChat";

/**
 * The side panel chat's store: its own sessions, socket and model pick, on the
 * `side` surface. That surface is a plain conversation; no seat on it has
 * tools (`dodaios/agent_chat/surface_kits.py`).
 */
export const useSideChatStore = createAgentChatStore("side");
