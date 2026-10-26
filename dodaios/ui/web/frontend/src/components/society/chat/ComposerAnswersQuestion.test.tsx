import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AgentChatStoreProvider } from "@/components/agentchat/AgentChatStoreContext";
import { EMPTY_TIMELINE, reduceEvents } from "@/components/agentchat/reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { createAgentChatStore } from "@/store/agentChat";
import type { SocietyAgent } from "../data";
import { Composer } from "./AgentChatPanel";

vi.mock("../data", async (load) => ({
  ...await load<typeof import("../data")>(),
  useSocietyCapabilities: () => ({ data: [], isLoading: false }),
}));
vi.mock("./AgentModelPicker", () => ({ AgentModelPicker: () => null }));

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ commands: [] }))));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

let seq = 0;
const ev = (kind: string, payload: Record<string, unknown>) => ({ seq: ++seq, ts_ms: 1000, kind, payload }) as AgentChatEvent;

const ASKING = [
  ev("turn_started", { turn_id: "t1" }),
  ev("question_required", {
    turn_id: "t1",
    question_id: "q1",
    asker: "Ada",
    questions: [{ question: "Which database?", options: [{ label: "SQLite" }, { label: "Postgres" }] }],
    expires_ms: Date.now() + 300_000,
  }),
];

function mount(events: AgentChatEvent[], consumed: boolean) {
  const store = createAgentChatStore("society");
  const answerByMessage = vi.fn(async () => consumed);
  store.setState({ activeSessionId: "chat-a", timeline: reduceEvents(EMPTY_TIMELINE, events), answerByMessage });
  const send = vi.fn().mockResolvedValue("sent");
  render(<AgentChatStoreProvider store={store}>
    <Composer agent={{ agentId: "ada", name: "Ada", tier: "specialist" } as unknown as SocietyAgent}
      mentionable={[]} busy sessionId="chat-a" cwd="" provider="local" surface="society"
      onSend={send} onCancel={async () => {}} />
  </AgentChatStoreProvider>);
  return { send, answerByMessage };
}

function write(text: string) {
  const box = screen.getByRole("textbox");
  box.textContent = text;
  fireEvent.input(box);
  return box;
}

it("invites an answer while a question is open", () => {
  mount(ASKING, true);
  expect(screen.getByRole("textbox").getAttribute("aria-placeholder")).toMatch(/answer ada, or write about something else/i);
});

it("a message the running turn takes as its answer is not sent again", async () => {
  const { send, answerByMessage } = mount(ASKING, true);
  fireEvent.keyDown(write("Postgres, please"), { key: "Enter" });
  await waitFor(() => expect(answerByMessage).toHaveBeenCalledWith("Postgres, please"));
  expect(send).not.toHaveBeenCalled();
  expect(screen.getByRole("textbox").textContent).toBe("");
});

it("an end-of-turn card settles and the message still goes out", async () => {
  const { send, answerByMessage } = mount(ASKING, false);
  fireEvent.keyDown(write("Postgres"), { key: "Enter" });
  await waitFor(() => expect(send).toHaveBeenCalledWith("Postgres", []));
  expect(answerByMessage).toHaveBeenCalledTimes(1);
});

it("without an open question the composer is an ordinary composer", async () => {
  const { send, answerByMessage } = mount([...ASKING, ev("turn_finished", { turn_id: "t1", status: "done" })], true);
  expect(screen.getByRole("textbox").getAttribute("aria-placeholder")).not.toMatch(/answer ada/i);
  fireEvent.keyDown(write("hello"), { key: "Enter" });
  await waitFor(() => expect(send).toHaveBeenCalled());
  expect(answerByMessage).not.toHaveBeenCalled();
});
