import { describe, expect, test, vi } from "vitest";
import { readComposerDraft, writeComposerDraft } from "@/components/agentchat/composerDrafts";
import type { AgentChatStoreHook } from "@/store/agentChat";
import type { SocietyAgent } from "../data";
import { seedFirstMessage } from "./firstMessage";

const { store } = vi.hoisted(() => ({ store: {} as object }));
vi.mock("../chat/AgentChatPanel", () => ({ useSocietyChatStore: store }));

const chat = store as unknown as AgentChatStoreHook;
const agent = (agentId: string, chatSessionId: string | null = `society:${agentId}`) =>
  ({ agentId, chatSessionId }) as unknown as SocietyAgent;

describe("seedFirstMessage", () => {
  test("puts the message in the agent's composer without sending it", async () => {
    expect(await seedFirstMessage(agent("a1"), "Give me a briefing for today.")).toBe(true);
    expect(readComposerDraft(chat, "society:a1").text).toBe("Give me a briefing for today.");
  });

  test("keeps an open-ended prompt's trailing space for the person to continue", async () => {
    await seedFirstMessage(agent("a2"), "Here is a bug I keep hitting: ");
    expect(readComposerDraft(chat, "society:a2").text).toBe("Here is a bug I keep hitting: ");
  });

  test("falls back to the canonical session and never replaces typed text", async () => {
    await seedFirstMessage(agent("a3", null), "First");
    expect(readComposerDraft(chat, "society:a3").text).toBe("First");
    writeComposerDraft(chat, "society:a4", { text: "my own words", choices: [] });
    expect(await seedFirstMessage(agent("a4"), "Suggested")).toBe(false);
    expect(readComposerDraft(chat, "society:a4").text).toBe("my own words");
  });

  test("an empty suggestion writes nothing", async () => {
    expect(await seedFirstMessage(agent("a5"), "   ")).toBe(false);
    expect(readComposerDraft(chat, "society:a5").text).toBe("");
  });
});
