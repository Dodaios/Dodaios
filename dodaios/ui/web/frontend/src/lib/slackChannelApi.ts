/**
 * The owner's own Slack app as a conversation channel (`/api/channels/slack`).
 * See `dodaios/ui/web/slack_channel_routes.py`.
 */

export interface SlackChannelState {
  enabled: boolean;
  keys_saved: boolean;
  /** The channel runs with both keys accepted. */
  running: boolean;
  /** The Socket Mode link is up right now. */
  link_up: boolean;
  /** A start failed for a passing reason and is tried again. */
  retrying: boolean;
  /** Why it does not run, or why the link is down; "" when fine. Never a key. */
  error: string;
  team_name: string;
  team_id: string;
  bot_name: string;
  app_id: string;
  /** Opens the direct message with the app; "" until Slack has named the app. */
  dm_url: string;
  owner_paired: boolean;
  pairing_open: boolean;
  pairing_seconds_left: number;
  assistant: string;
  /** Opens Slack's "create app from manifest" with the manifest filled in. */
  create_app_url: string;
  manifest: Record<string, unknown>;
  live_applied?: boolean;
  owner_from_sign_in?: boolean;
}

/** Why a connect failed, as the backend names it. */
export type SlackConnectErrorCode =
  | "bot_token_shape"
  | "app_token_shape"
  | "bot_token_rejected"
  | "app_token_rejected"
  | "socket_mode_off"
  | "different_apps"
  | "slack_unreachable"
  | "store_failed";

export class SlackConnectError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

const BASE = "/api/channels/slack";

async function read(res: Response): Promise<SlackChannelState> {
  if (res.ok) return (await res.json()) as SlackChannelState;
  let code = "unknown";
  let message = `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    const detail = body.detail;
    if (detail && typeof detail === "object") {
      const d = detail as { code?: string; message?: string };
      code = d.code ?? code;
      message = d.message ?? message;
    } else if (typeof detail === "string") {
      message = detail;
    }
  } catch {
    // The status line is all there is.
  }
  throw new SlackConnectError(code, message);
}

export async function fetchSlackChannel(): Promise<SlackChannelState> {
  return read(await fetch(BASE));
}

export async function connectSlackChannel(botToken: string, appToken: string): Promise<SlackChannelState> {
  return read(
    await fetch(`${BASE}/connect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_token: botToken.trim(), app_token: appToken.trim() }),
    }),
  );
}

export async function pairSlackAgain(): Promise<SlackChannelState> {
  return read(await fetch(`${BASE}/pairing`, { method: "POST" }));
}

export async function disconnectSlackChannel(): Promise<SlackChannelState> {
  return read(await fetch(`${BASE}/disconnect`, { method: "POST" }));
}
