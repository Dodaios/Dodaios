// Thin client for the trust layer (dodaios/ui/web/trust_routes.py). Shapes
// mirror dodaios/trust/* one-to-one; nothing here decides behaviour.

export type TrustRuleKind = "tool" | "action" | "folder" | "command";

export interface TrustRule {
  id: string;
  tool: string;
  kind: TrustRuleKind;
  target: string;
  label: string;
  app: string;
  source: string;
  created_ms: number;
}

export interface AgentRule {
  agent_id: string;
  agent: string;
  pattern: string;
  app: string;
  verb: string;
  label: string;
}

export interface TrustRules {
  rules: TrustRule[];
  agent_rules: AgentRule[];
  hard_limits: string[];
}

export interface UndoEntry {
  id: string;
  tool: string;
  label: string;
  state: "ready" | "running" | "undone" | "failed" | "expired";
  error?: string;
  created_ms: number;
  expires_ms: number;
}

export interface ConnectedAccount {
  id: string;
  label: string;
  category: string;
  status: "connected" | "needs_reauth";
}

export interface ProviderInUse {
  role: string;
  provider: string;
  label: string;
  local: boolean;
}

export interface PrivacyOverview {
  accounts: ConnectedAccount[];
  memory: { available: boolean; count: number; learning_paused: boolean; paused_until: string | null };
  providers: ProviderInUse[];
  cloud: ProviderInUse[];
  channels: string[];
  screen_context: boolean;
  known_recipients: number;
}

export interface KnownRecipient {
  recipient: string;
  first_ms: number;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string" && body.detail) detail = body.detail;
    } catch {
      /* a plain error body is fine */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

const json = (body: unknown): RequestInit => ({
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const fetchTrustRules = () => request<TrustRules>("/api/trust/rules");

export const revokeTrustRule = (id: string) =>
  request<{ ok: boolean; rule: TrustRule }>(`/api/trust/rules/${encodeURIComponent(id)}`, { method: "DELETE" });

export const revokeAgentRule = (agentId: string, pattern: string) =>
  request<{ ok: boolean }>(
    `/api/trust/agent-rules/${encodeURIComponent(agentId)}?pattern=${encodeURIComponent(pattern)}`,
    { method: "DELETE" },
  );

export async function runUndo(id: string): Promise<UndoEntry> {
  const body = await request<{ ok: boolean; entry: UndoEntry }>(`/api/trust/undo/${encodeURIComponent(id)}`, {
    method: "POST",
  });
  return body.entry;
}

export const fetchPrivacyOverview = () => request<PrivacyOverview>("/api/trust/privacy");

export const fetchKnownRecipients = async () =>
  (await request<{ recipients: KnownRecipient[] }>("/api/trust/recipients")).recipients;

export const forgetRecipient = (recipient: string) =>
  request<{ ok: boolean }>(`/api/trust/recipients?recipient=${encodeURIComponent(recipient)}`, { method: "DELETE" });

/** The memory vault's learning switch (personal_memory_routes.py): off = paused for good. */
export const setLearning = (on: boolean) =>
  request<{ paused: boolean; until: string | null }>("/api/memory/vault/pause", json(on ? {} : { forever: true }));

/** The screen-context master switch (screen_context_routes.py). */
export const setScreenContext = (enabled: boolean) =>
  request<{ enabled: boolean }>("/api/screen-context/settings", json({ enabled }));

export interface ActionReceipt {
  id: string;
  state: "backed" | "none" | "read";
  kind: string;
  summary: string;
  evidence: Record<string, unknown>;
  links: string[];
}

export interface AuditEntry {
  seq: number;
  id: string;
  ts_ms: number;
  day: string;
  tool: string;
  action: string;
  origin: "owner" | "routine" | "trigger" | "agent";
  origin_detail: string;
  approval: string;
  approval_by: string;
  tier: string;
  effect: string;
  outcome: string;
  error: string;
  duration_ms: number;
  args_preview: string;
  receipt: ActionReceipt | null;
}

export interface AuditPage {
  entries: AuditEntry[];
  next_before: number | null;
  days: string[];
  tools: string[];
  chain: { ok: boolean; rows: number; broken_at: number | null };
}

export interface AuditFilter {
  day?: string;
  tool?: string;
  origin?: string;
  before?: number;
}

export function auditQuery(filter: AuditFilter): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filter)) {
    if (value) params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** Read-only: the audit log has no write route. */
export const fetchAudit = (filter: AuditFilter) => request<AuditPage>(`/api/trust/audit${auditQuery(filter)}`);

export const auditExportUrl = (format: "csv" | "json", filter: AuditFilter) => {
  const query = auditQuery({ ...filter, before: undefined });
  return `/api/trust/audit/export${query ? `${query}&` : "?"}format=${format}`;
};

export type SelfChangeState = "proposed" | "trial" | "live" | "reverted" | "blocked";
export type SelfChangeSurface =
  | "skill"
  | "prompt"
  | "instructions"
  | "tool"
  | "code"
  | "config"
  | "routine"
  | "agent";

export interface SelfChange {
  id: string;
  surface: SelfChangeSurface;
  target: string;
  version: number;
  diff: string;
  author: string;
  turn: string;
  reason: string;
  state: SelfChangeState;
  core: boolean;
  core_reasons: string[];
  gate: { status?: string; checks?: { name: string; status: string; detail: string }[] };
  note: string;
  created_ms: number;
  updated_ms: number;
}

export interface SelfChangeSummary {
  total: number;
  waiting: number;
  on_trial: number;
  live: number;
  reverted: number;
  blocked: number;
}

/** The self-change registry (dodaios/self_change). Recording and grading have no route. */
export const fetchSelfChanges = () =>
  request<{ changes: SelfChange[]; summary: SelfChangeSummary }>("/api/self-change");

const post = (url: string, body?: unknown) =>
  request<{ ok: boolean; reverted?: SelfChange[] }>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const decideSelfChange = (id: string, action: "approve" | "reject" | "keep" | "rollback") =>
  post(`/api/self-change/${encodeURIComponent(id)}/${action}`);

export const rollbackSelfChangesSince = (sinceMs: number) =>
  post("/api/self-change/rollback-since", { since_ms: sinceMs });

// ---- Credentials (dodaios/credential_broker): handles and states, never values.

export interface CredentialBackendStatus {
  name: "local" | "bitwarden" | "1password";
  installed: boolean;
  unlocked: boolean;
  state: "ready" | "locked" | "not_installed" | "unavailable";
}

export interface CredentialHandle {
  handle: string;
  domain: string;
  account: string;
  label: string;
  backend: string;
  has_totp: boolean;
  agent_id: string;
  agent: string;
}

export interface CredentialSiteRule {
  id: string;
  agent_id: string;
  agent: string;
  domain: string;
  handle: string;
  otp_from_mail: boolean;
  created_ms: number;
}

export interface CredentialsOverview {
  backend: string;
  backends: CredentialBackendStatus[];
  handles: CredentialHandle[];
  rules: CredentialSiteRule[];
  error: string;
}

export const fetchCredentials = () => request<CredentialsOverview>("/api/trust/credentials");

export const setCredentialBackend = (name: string) =>
  request<{ ok: boolean }>("/api/trust/credentials/backend", json({ name }));

/** The owner's own unlock key, kept in memory by the server; an empty key locks. */
export const setCredentialSession = (backend: string, key: string) =>
  request<{ ok: boolean }>("/api/trust/credentials/session", json({ backend, key }));

export const revokeCredentialRule = (id: string) =>
  request<{ ok: boolean }>(`/api/trust/credentials/rules/${encodeURIComponent(id)}`, { method: "DELETE" });

export const setCredentialOtpMail = (id: string, on: boolean) =>
  request<{ ok: boolean }>(`/api/trust/credentials/rules/${encodeURIComponent(id)}/otp-mail`, json({ on }));
