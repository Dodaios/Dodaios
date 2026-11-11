import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { EMPTY_TIMELINE, reduceEvents, type TurnItem } from "@/components/agentchat/reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { ThreadTurn } from "./ThreadTimeline";

let seq = 0;
const at = (kind: string, ts: number, payload: Record<string, unknown>): AgentChatEvent =>
  ({ seq: ++seq, ts_ms: ts, kind, payload } as AgentChatEvent);
const turnOf = (events: AgentChatEvent[]) =>
  reduceEvents(EMPTY_TIMELINE, events).items.find((item) => item.type === "turn") as TurnItem;

const now = Date.now();
/** A thread's first turn on another computer, three steps in. */
const settingUp = () => [
  at("turn_started", now - 30_000, { turn_id: "t1", provider: "claude-cli" }),
  at("setup_step", now - 29_000, { turn_id: "t1", step: "connect", where: "My VPS" }),
  at("setup_step", now - 27_000, { turn_id: "t1", step: "fetch", host: "github.com" }),
  at("setup_step", now - 12_000, { turn_id: "t1", step: "send" }),
  at("setup_step", now - 12_000, { turn_id: "t1", step: "send" }),
];

afterEach(cleanup);

describe("a thread turn being set up on another computer", () => {
  it("says where it sets up and lists each step, the current one last", () => {
    render(<ThreadTurn turn={turnOf(settingUp())} />);
    expect(screen.getByTestId("thread-setting-up").textContent).toMatch(/^Setting up on My VPS·/);
    expect(screen.getByTestId("thread-working").textContent).not.toContain("Getting ready");
    const steps = [...screen.getByTestId("thread-setup-steps").querySelectorAll("li")];
    // A step told twice stays one line.
    expect(steps.map((step) => step.dataset.step)).toEqual(["connect", "fetch", "send"]);
    expect(steps.map((step) => step.dataset.done)).toEqual(["true", "true", "false"]);
    expect(steps[0].textContent).toBe("Connecting2.0s");
    expect(steps[1].textContent).toBe("Fetching the code from github.com15s");
    expect(steps[2].textContent).toMatch(/^Sending your changes/);
  });

  it("gives way to the agent's work once its first output arrives", () => {
    const turn = turnOf([
      ...settingUp(),
      at("setup_step", now - 2_000, { turn_id: "t1", step: "start", cli: "claude" }),
      at("assistant_text", now, { turn_id: "t1", message_id: "m1", text: "Hello." }),
    ]);
    render(<ThreadTurn turn={turn} />);
    expect(screen.queryByTestId("thread-setting-up")).toBeNull();
    expect(screen.getByTestId("thread-working").textContent).toMatch(/^Working for /);
  });

  it("keeps the plain line for a turn on this computer", () => {
    render(<ThreadTurn turn={turnOf([at("turn_started", now, { turn_id: "t1", provider: "claude-cli" })])} />);
    expect(screen.queryByTestId("thread-setting-up")).toBeNull();
    expect(screen.getByTestId("thread-working").textContent).toContain("Getting ready");
  });
});
