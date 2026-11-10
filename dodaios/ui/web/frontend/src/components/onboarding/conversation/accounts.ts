/**
 * The help topics the first conversation offers, the accounts each one
 * suggests, and the sign-in those accounts go through.
 *
 * Accounts are plugins from the marketplace catalog; only ids the catalog
 * actually lists are offered, so a catalog without one simply shows fewer.
 * The sign-in is the same one the Plugins page and the agents' connect
 * cards use: a browser sign-in where the plugin has one, else the plugin's
 * own page in Plugins (a token to paste, an address to enter).
 */
import { requestPluginFocus } from "@/lib/customConnector";
import { openExternalUrl } from "@/lib/openExternal";

export interface HelpTopic {
  /** Also the i18n key: `first_run.conversation.topics.<id>`. */
  id: string;
  /** The words the memory keeps (English: the model reads them). */
  memory: string;
  /** Plugin ids worth connecting for this topic, best first. */
  accounts: readonly string[];
}

export const HELP_TOPICS: readonly HelpTopic[] = [
  { id: "email", memory: "email", accounts: ["gmail", "outlook"] },
  { id: "calendar", memory: "calendar and scheduling", accounts: ["google_calendar", "outlook"] },
  { id: "writing", memory: "writing", accounts: ["notion", "google_drive"] },
  { id: "coding", memory: "coding", accounts: ["github"] },
  { id: "research", memory: "research", accounts: [] },
  { id: "tasks", memory: "tasks and reminders", accounts: ["todoist", "microsoft_todo"] },
  { id: "music", memory: "music", accounts: ["spotify"] },
  { id: "home", memory: "smart home", accounts: ["home_assistant"] },
];

/** Offered when the topics suggest nothing (or too little). */
const DEFAULT_ACCOUNTS = ["gmail", "google_calendar", "outlook", "github", "notion", "spotify"];

export const MAX_ACCOUNTS = 6;

export interface CatalogAccount {
  id: string;
  display_name?: string;
  status?: string;
}

/** The accounts to offer: suggested by the topics first, then the defaults. */
export function suggestedAccounts(topicIds: readonly string[], catalog: readonly CatalogAccount[]): CatalogAccount[] {
  const byId = new Map(catalog.map((p) => [p.id, p]));
  const order: string[] = [];
  for (const topic of HELP_TOPICS) {
    if (!topicIds.includes(topic.id)) continue;
    for (const id of topic.accounts) if (!order.includes(id)) order.push(id);
  }
  for (const id of DEFAULT_ACCOUNTS) if (!order.includes(id)) order.push(id);
  return order
    .map((id) => byId.get(id))
    .filter((p): p is CatalogAccount => Boolean(p))
    .slice(0, MAX_ACCOUNTS);
}

export async function loadAccountCatalog(): Promise<CatalogAccount[]> {
  try {
    const res = await fetch("/api/marketplace/plugins", { cache: "no-store" });
    if (!res.ok) return [];
    const body = (await res.json()) as { plugins?: CatalogAccount[] };
    return body.plugins ?? [];
  } catch {
    // No catalog yet (backend still starting): the step offers no accounts
    // and says where to connect them later.
    return [];
  }
}

export async function accountConnected(id: string): Promise<boolean> {
  const plugins = await loadAccountCatalog();
  return plugins.some((p) => p.id === id && p.status === "connected");
}

export type ConnectStart =
  /** A browser sign-in is open; poll until it lands. `code` for a device flow. */
  | { kind: "browser"; flowId: string; code?: string }
  /** The plugin needs its own page (a token, an address): Plugins opened on it. */
  | { kind: "page" };

/**
 * Starts the plugin's sign-in. Anything the browser flow cannot do here
 * falls back to the plugin's page in Plugins, never to a dead button.
 */
export async function startAccountConnect(id: string): Promise<ConnectStart> {
  let flow: Record<string, unknown>;
  try {
    const res = await fetch(`/api/marketplace/plugins/${encodeURIComponent(id)}/connect/start`, { method: "POST" });
    flow = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    if (!res.ok) throw new Error(String(flow.detail ?? res.status));
  } catch {
    requestPluginFocus(id);
    return { kind: "page" };
  }
  const flowId = String(flow.flow_id ?? "");
  if (flow.kind === "device_flow") {
    const verifyUrl = String(flow.verification_uri_complete ?? flow.verification_uri ?? "");
    if (verifyUrl) await openExternalUrl(verifyUrl);
    return { kind: "browser", flowId, code: String(flow.user_code ?? "") || undefined };
  }
  if (flow.open_url) await openExternalUrl(String(flow.open_url));
  return { kind: "browser", flowId: flow.kind === "local" ? "" : flowId };
}

/** One poll of a started sign-in: connected, failed, or still waiting. */
export async function pollAccountConnect(id: string, flowId: string): Promise<"connected" | "failed" | "waiting"> {
  if (!flowId) return (await accountConnected(id)) ? "connected" : "waiting";
  const res = await fetch(
    `/api/marketplace/plugins/${encodeURIComponent(id)}/connect/poll/${encodeURIComponent(flowId)}`,
  );
  if (res.status === 404) return (await accountConnected(id)) ? "connected" : "waiting";
  const data = (await res.json().catch(() => ({}))) as { state?: string };
  if (data.state === "error") return "failed";
  return data.state === "connected" ? "connected" : "waiting";
}
