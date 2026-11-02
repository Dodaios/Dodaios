import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThreadTurn } from "@/components/agentic/threads/ThreadTimeline";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { createAgentChatStore } from "@/store/agentChat";
import { AgentChatStoreProvider } from "./AgentChatStoreContext";
import { EMPTY_TIMELINE, reduceEvents, type ToolBlock, type TurnItem } from "./reduce";

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>): AgentChatEvent {
  return { seq: ++seq, ts_ms: 1000, kind, payload } as AgentChatEvent;
}

const USER = "ada@example.org";
const PASSWORD = "correct horse battery";

function card(tool: string, payload: Record<string, unknown>, extra: AgentChatEvent[] = []): AgentChatEvent[] {
  return [
    ev("turn_started", { turn_id: "t1" }),
    ev("tool_call", { turn_id: "t1", call_id: "c1", name: `mcp__jarvis__${tool}`, input: {} }),
    ev("credential_required", { turn_id: "t1", request_id: "r1", asker: "Ada", replace: false, ...payload }),
    ...extra,
  ];
}

const LOGIN = { kind: "login", env: "reddit", label: "Reddit", url: "https://www.reddit.com/login", description: "To post your thread." };
const CONNECT = { kind: "plugin", env: "github", label: "GitHub", description: "To read your issues." };

function draw(events: AgentChatEvent[]) {
  const store = createAgentChatStore("society");
  store.setState({ activeSessionId: "society:ada" });
  return render(
    <AgentChatStoreProvider store={store}>
      <ThreadTurn turn={reduceEvents(EMPTY_TIMELINE, events).items[0] as TurnItem} prompts="inline" />
    </AgentChatStoreProvider>,
  );
}

afterEach(() => {
  cleanup();
  seq = 0;
  vi.restoreAllMocks();
});

describe("login and connect cards", () => {
  it("attach to their own tool calls with their kind", () => {
    const login = reduceEvents(EMPTY_TIMELINE, card("society_request_login", LOGIN)).items[0] as TurnItem;
    expect((login.blocks[0] as ToolBlock).credential).toMatchObject({ kind: "login", url: LOGIN.url, status: null });
    const connect = reduceEvents(EMPTY_TIMELINE, card("society_request_connect", CONNECT)).items[0] as TurnItem;
    expect((connect.blocks[0] as ToolBlock).callId).toBe("c1");
    expect((connect.blocks[0] as ToolBlock).credential?.kind).toBe("plugin");
  });

  it("opens a form and sends both values in one request, never keeping them", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, request_id: "r1", status: "saved" }), { status: 200 }),
    );
    draw(card("society_request_login", LOGIN));
    expect(screen.getByTestId("login-card").textContent).toContain("Reddit");
    fireEvent.click(screen.getByTestId("login-card-open"));
    const form = screen.getByTestId("login-form");
    const [user, pass] = Array.from(form.querySelectorAll("input"));
    expect(pass.getAttribute("type")).toBe("password");
    fireEvent.change(user, { target: { value: ` ${USER} ` } });
    fireEvent.change(pass, { target: { value: PASSWORD } });
    fireEvent.submit(form.querySelector("form")!);
    await waitFor(() => expect(screen.queryByTestId("login-form")).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/credentials/r1");
    expect(JSON.parse(JSON.parse(String(init.body)).value)).toEqual({ username: USER, password: PASSWORD });
    expect(screen.getByTestId("login-card").getAttribute("data-state")).toBe("success");
    expect(document.body.innerHTML).not.toContain(PASSWORD);
  });

  it("shows the saved state once the login is resolved", () => {
    draw(card("society_request_login", LOGIN, [
      ev("credential_resolved", { turn_id: "t1", request_id: "r1", env: "reddit", status: "saved" }),
    ]));
    expect(screen.getByTestId("login-card").getAttribute("data-state")).toBe("success");
    expect(screen.queryByTestId("login-card-open")).toBeNull();
  });

  it("offers Connect with the service's name and closes once connected", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/connect/start")) {
        return new Response(JSON.stringify({ flow_id: "f1", plugin_id: "github", kind: "local", open_url: null }), { status: 200 });
      }
      if (url === "/api/marketplace/plugins") {
        return new Response(JSON.stringify({ plugins: [{ id: "github", status: "connected" }] }), { status: 200 });
      }
      return new Response(JSON.stringify({ ok: true, request_id: "r1", status: "saved" }), { status: 200 });
    });
    draw(card("society_request_connect", CONNECT));
    expect(screen.getByTestId("connect-card").textContent).toContain("GitHub");
    fireEvent.click(screen.getByTestId("connect-card-connect"));
    await waitFor(() => expect(screen.getByTestId("connect-card").getAttribute("data-state")).toBe("success"), { timeout: 6000 });
    const reported = fetchMock.mock.calls.find(([url]) => String(url).includes("/credentials/r1"));
    expect(JSON.parse(String((reported![1] as RequestInit).body)).value).toBe("connected");
  });
});
