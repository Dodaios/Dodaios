import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useRoutineNavigation } from "@/components/society/chat/routineNavigation";

import type { NoticeItem } from "./reduce";
import { RoutineResultMessage } from "./RoutineResultMessage";

afterEach(() => {
  cleanup();
  useRoutineNavigation.setState({ target: null });
});

/** The notice `dodaios/society/routine_runner.py` posts into the owner's chat when a run answers. */
function result(data: Record<string, unknown> = {}, extra: Partial<NoticeItem> = {}): NoticeItem {
  const payload = {
    kind: "society_result", status: "done", source: "routine", text: "Two new issues: **login fails** and a typo.",
    agent_id: "jarvis", agent_name: "Nova", task_id: "task_1", session_id: "run_s1", title: "Daily issue check", ...data,
  };
  return {
    type: "notice", id: "n-7", kind: "society_result", text: String(payload.text ?? ""), agentName: "Nova",
    agentId: String(payload.agent_id ?? ""), status: "done", tsMs: 1_700_000_000_000, resolved: "", data: payload, ...extra,
  };
}

const line = () => screen.getByTestId("routine-result-line");

describe("in the conversation look", () => {
  it("is the assistant's own grey message, the routine named on a quiet line above it", () => {
    render(<RoutineResultMessage item={result()} look="lead" />);
    const message = screen.getByTestId("routine-result");
    expect(message.getAttribute("data-look")).toBe("lead");
    expect(message.getAttribute("data-message-id")).toBe("n-7");
    // The lanes of an answer: the face lane, then the words.
    expect(message.classList.contains("lead-turn")).toBe(true);
    expect(message.querySelector(".lead-face-lane")).toBeTruthy();
    const bubble = within(message).getByTestId("lead-bubble");
    expect(bubble.className).toContain("jarvis-chat-in");
    expect(bubble.textContent).toBe("Two new issues: login fails and a typo.");
    expect(within(bubble).getByText("login fails").tagName).toBe("STRONG");
    // The line names the routine, small and muted, and stands above the words.
    expect(line().textContent).toBe("Routine · Daily issue check");
    expect(line().className).toContain("text-xs");
    expect(line().className).toContain("text-muted-foreground");
    expect(line().compareDocumentPosition(bubble) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(line().contains(bubble)).toBe(false);
  });

  it("opens the run it came from", () => {
    render(<RoutineResultMessage item={result()} look="lead" />);
    const open = screen.getByRole("button", { name: "Routine · Daily issue check · Open this run" });
    expect(open).toBe(line());
    expect(open.getAttribute("title")).toBe("Open this run");
    fireEvent.click(open);
    expect(useRoutineNavigation.getState().target).toEqual({
      agentId: "jarvis", sessionId: "run_s1", title: "Daily issue check", timestamp: 1_700_000_000_000,
    });
  });

  it("is a plain line when the run's chat is not known", () => {
    render(<RoutineResultMessage item={result({ session_id: undefined })} look="lead" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(line().tagName).toBe("P");
    expect(line().textContent).toBe("Routine · Daily issue check");
  });

  it("says only that it is a routine when the notice names none, and labels a standing task with the task", () => {
    render(<RoutineResultMessage item={result({ title: undefined })} look="lead" />);
    expect(line().textContent).toBe("Routine");
    cleanup();
    render(<RoutineResultMessage item={result({ title: undefined, standing_title: "Inbox watch" })} look="lead" />);
    // A standing task keeps the label it always had in the chat.
    expect(line().textContent).toBe("Standing task: Inbox watch");
  });

  it("draws the line alone for a result without words", () => {
    render(<RoutineResultMessage item={result({ text: "" })} look="lead" />);
    expect(line()).toBeTruthy();
    expect(screen.queryByTestId("lead-bubble")).toBeNull();
  });
});

describe("opening the run", () => {
  it("finds the agent on the payload, else the assistant", () => {
    render(<RoutineResultMessage item={result({ agent_id: "mail" }, { agentId: "" })} look="lead" />);
    fireEvent.click(line());
    expect(useRoutineNavigation.getState().target?.agentId).toBe("mail");
    cleanup();
    render(<RoutineResultMessage item={result({ agent_id: undefined, title: undefined }, { agentId: "" })} look="lead" />);
    fireEvent.click(line());
    expect(useRoutineNavigation.getState().target).toMatchObject({ agentId: "jarvis", title: "Routine" });
  });
});

describe("in other chats", () => {
  it("is the agent's message in its own chat: the bubble its chat passes, under the same line", () => {
    render(
      <RoutineResultMessage item={result()} look="messenger">
        <div data-testid="agent-message-bubble">Two new issues.</div>
      </RoutineResultMessage>,
    );
    const message = screen.getByTestId("routine-result");
    expect(message.getAttribute("data-look")).toBe("messenger");
    expect(message.getAttribute("data-message-id")).toBe("n-7");
    const bubble = within(message).getByTestId("agent-message-bubble");
    expect(line().compareDocumentPosition(bubble) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("button", { name: /Daily issue check/ })).toBe(line());
  });

  it("reads as plain type in a document, without a bubble", () => {
    render(<RoutineResultMessage item={result()} look="document" />);
    const message = screen.getByTestId("routine-result");
    expect(message.getAttribute("data-look")).toBe("document");
    expect(within(message).queryByTestId("lead-bubble")).toBeNull();
    expect(message.textContent).toContain("Two new issues: login fails and a typo.");
    expect(line().textContent).toBe("Routine · Daily issue check");
  });
});

describe("a ritual's card", () => {
  const ritual = (more: Record<string, unknown> = {}): NoticeItem => ({
    type: "notice", id: "r1", kind: "society_result", text: "", agentName: "Nova", agentId: "jarvis",
    status: "done", tsMs: 1, resolved: "",
    data: { kind: "society_result", source: "ritual", ritual_id: "rit_1", ritual_title: "Good morning", ...more },
  });

  it("names the ritual on its line, which opens nothing: a ritual has no run chat of its own", () => {
    render(<RoutineResultMessage item={ritual()} look="document" />);
    const line = screen.getByTestId("routine-result-line");
    expect(line.tagName).toBe("P");
    expect(line.textContent).toBe("“Good morning” started");
  });

  it("adds that the rest follows when nothing was ready yet", () => {
    render(<RoutineResultMessage item={ritual({ pending: true })} look="document" />);
    expect(screen.getByTestId("routine-result").textContent).toContain("The rest is being gathered and follows shortly.");
  });
});
