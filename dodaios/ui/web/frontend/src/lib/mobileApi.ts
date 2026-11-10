/**
 * The desktop's client for the phone companion's settings routes
 * (`/api/mobile/*`, never the phone-only `/api/mobile/app/*`).
 */

export interface PairedPhone {
  id: string;
  name: string;
  created_at: number;
  last_seen_at: number;
  push: boolean;
}

export interface Listening {
  bind_host: string;
  loopback_only: boolean;
  port: number;
  https: boolean;
  lan_addresses: string[];
}

export interface WhatsAppState {
  enabled: boolean;
  running: boolean;
  owner_claimed: boolean;
  linked: boolean;
  bridge_url: string;
  start_error?: string;
  missing?: string;
}

export interface MobileStatus {
  devices: PairedPhone[];
  open_codes: number;
  push_ready: boolean;
  listening: Listening;
  whatsapp: WhatsAppState;
}

export interface PairingCode {
  code: string;
  expires_in: number;
  urls: string[];
  listening: Listening;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json" } : undefined,
  });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* a plain-text error keeps the status line */
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export const mobileApi = {
  status: () => request<MobileStatus>("/api/mobile/status"),
  pairCode: () => request<PairingCode>("/api/mobile/pair/code", { method: "POST" }),
  devices: () => request<{ devices: PairedPhone[] }>("/api/mobile/devices").then((r) => r.devices),
  revoke: (id: string) =>
    request<{ removed: boolean }>(`/api/mobile/devices/${encodeURIComponent(id)}`, { method: "DELETE" }),
  rename: (id: string, name: string) =>
    request<PairedPhone>(`/api/mobile/devices/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  whatsapp: (enabled: boolean) =>
    request<WhatsAppState>("/api/mobile/whatsapp", { method: "PUT", body: JSON.stringify({ enabled }) }),
};
