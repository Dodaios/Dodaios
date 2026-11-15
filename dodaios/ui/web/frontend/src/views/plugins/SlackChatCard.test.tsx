/**
 * The Slack plugin page's card for chatting with the assistant in Slack: the
 * three setup steps, what a connect sends, how a refused key is worded, and
 * the connected state (who it answers, the pairing window, Open in Slack).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SlackChannelState } from "@/lib/slackChannelApi";
import { SlackChatCard } from "@/views/plugins/SlackChatCard";

const BASE: SlackChannelState = {
  enabled: false,
  keys_saved: false,
  running: false,
  link_up: false,
  retrying: false,
  error: "",
  team_name: "",
  team_id: "",
  bot_name: "",
  app_id: "",
  dm_url: "",
  owner_paired: false,
  pairing_open: false,
  pairing_seconds_left: 0,
  assistant: "Nova",
  create_app_url: "https://api.slack.com/apps?new_app=1&manifest_json=%7B%7D",
  manifest: { display_information: { name: "Nova" } },
};

const CONNECTED: SlackChannelState = {
  ...BASE,
  enabled: true,
  keys_saved: true,
  running: true,
  link_up: true,
  team_name: "Acme Studio",
  team_id: "T0STANDIN1",
  bot_name: "nova",
  app_id: "A0STANDIN1",
  dm_url: "https://slack.com/app_redirect?app=A0STANDIN1&team=T0STANDIN1",
};

function backend(state: SlackChannelState, connect?: { status: number; body: unknown }) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (url.endsWith("/connect") && connect) {
      return new Response(JSON.stringify(connect.body), { status: connect.status });
    }
    return new Response(JSON.stringify(state), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><SlackChatCard /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SlackChatCard", () => {
  it("shows the three setup steps and sends both keys on Connect", async () => {
    const calls = backend(BASE, { status: 200, body: { ...CONNECTED, owner_paired: false, pairing_open: true, pairing_seconds_left: 540 } });
    mount();
    await screen.findByText("Create Nova in Slack");
    expect(screen.getByText("Chat with Nova in Slack")).toBeTruthy();
    fireEvent.change(screen.getByTestId("slack-chat-bot-token"), { target: { value: " xoxb-1-2-abc " } });
    fireEvent.change(screen.getByTestId("slack-chat-app-token"), { target: { value: "xapp-1-A1-2-def" } });
    fireEvent.click(screen.getByText("Connect"));
    await screen.findByTestId("slack-chat-connected");
    const post = calls.find((c) => c.method === "POST");
    expect(post?.url).toBe("/api/channels/slack/connect");
    expect(post?.body).toEqual({ bot_token: "xoxb-1-2-abc", app_token: "xapp-1-A1-2-def" });
    expect(screen.getByTestId("slack-chat-owner").textContent).toContain("within 9 min");
  });

  it("words a refused key so the person knows where to look", async () => {
    backend(BASE, {
      status: 400,
      body: { detail: { code: "app_token_rejected", message: "Slack refused the app-level token (invalid_auth)." } },
    });
    mount();
    await screen.findByText("Create Nova in Slack");
    fireEvent.change(screen.getByTestId("slack-chat-bot-token"), { target: { value: "xoxb-1" } });
    fireEvent.change(screen.getByTestId("slack-chat-app-token"), { target: { value: "xapp-1" } });
    fireEvent.click(screen.getByText("Connect"));
    const error = await screen.findByTestId("slack-chat-error");
    expect(error.textContent).toContain("connections:write");
  });

  it("keeps Connect off until both keys are there", async () => {
    backend(BASE);
    mount();
    await screen.findByText("Create Nova in Slack");
    const connect = screen.getByText("Connect").closest("button") as HTMLButtonElement;
    expect(connect.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("slack-chat-bot-token"), { target: { value: "xoxb-1" } });
    expect(connect.disabled).toBe(true);
  });

  it("says who it answers once connected, and offers the direct message", async () => {
    backend({ ...CONNECTED, owner_paired: true });
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("slack-chat-state").textContent).toBe("Connected to Acme Studio as @nova"),
    );
    expect(screen.getByTestId("slack-chat-owner").textContent).toContain("Only you get answers");
    expect(screen.getByText("Open in Slack")).toBeTruthy();
    expect(screen.getByText("Change owner")).toBeTruthy();
  });

  it("shows a link that is down as reconnecting, with the reason", async () => {
    backend({ ...CONNECTED, link_up: false, owner_paired: true, error: "ConnectError: no route" });
    mount();
    await waitFor(() =>
      expect(screen.getByTestId("slack-chat-state").textContent).toBe("Connecting to Slack again…"),
    );
    expect(screen.getByText("ConnectError: no route")).toBeTruthy();
  });
});
