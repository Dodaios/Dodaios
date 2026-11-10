/**
 * The phone's client for `/api/mobile/app/*`.
 *
 * The device token a redeemed pairing code answered with is the only
 * credential; it lives in this browser's storage and rides as a Bearer header.
 * A 401 means the desktop revoked this phone (or the token never existed):
 * the token is dropped and the app returns to its pairing screen.
 */

export const TOKEN_KEY = "dodaios.mobile.token";

export class Unpaired extends Error {
  constructor() {
    super("unpaired");
    this.name = "Unpaired";
  }
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface TimelineRow {
  id: string;
  kind: "user" | "assistant" | "approval" | "question" | "notice" | "error";
  text: string;
  ts_ms: number;
  approval_id?: string;
  name?: string;
  decision?: string | null;
  answered?: boolean;
  notice_kind?: string;
  status?: string;
}

export interface Timeline {
  rows: TimelineRow[];
  pending_approvals: string[];
  waiting: boolean;
  running: boolean;
  last_seq: number;
  session_id: string;
  title: string;
}

export interface Me {
  device: { id: string; name: string; push: boolean };
  assistant_name: string;
  push_key: string;
  push_subscribed: boolean;
}

export interface Storage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    getItem: (k) => map.get(k) ?? null,
    setItem: (k, v) => void map.set(k, v),
    removeItem: (k) => void map.delete(k),
  };
}

export function safeStorage(): Storage {
  try {
    const probe = "dodaios.mobile.probe";
    window.localStorage.setItem(probe, "1");
    window.localStorage.removeItem(probe);
    return window.localStorage;
  } catch {
    return memoryStorage();
  }
}

export class MobileApi {
  constructor(
    private readonly storage: Storage,
    private readonly fetchImpl: typeof fetch = (input, init) => fetch(input, init),
  ) {}

  get token(): string | null {
    return this.storage.getItem(TOKEN_KEY);
  }

  forget(): void {
    this.storage.removeItem(TOKEN_KEY);
  }

  private async send<T>(path: string, init: RequestInit = {}, raw = false): Promise<T> {
    const token = this.token;
    if (!token && !raw) throw new Unpaired();
    const headers = new Headers(init.headers ?? {});
    if (token) headers.set("Authorization", `Bearer ${token}`);
    if (init.body && !(init.body instanceof ArrayBuffer) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const response = await this.fetchImpl(path, { ...init, headers });
    if (response.status === 401) {
      if (!raw) this.forget();
      let detail = "";
      try {
        detail = String(((await response.json()) as { detail?: unknown }).detail ?? "");
      } catch {
        detail = "";
      }
      if (raw) throw new ApiError(401, detail);
      throw new Unpaired();
    }
    if (!response.ok) {
      let detail = `${response.status}`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        /* a plain-text error keeps the status code */
      }
      throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
  }

  /** Spend a pairing code for this phone's token; keeps the token on success. */
  async pair(code: string, name: string): Promise<{ assistant_name: string }> {
    const body = await this.send<{ token: string; assistant_name: string }>(
      "/api/mobile/pair/redeem",
      { method: "POST", body: JSON.stringify({ code, name }) },
      true,
    );
    this.storage.setItem(TOKEN_KEY, body.token);
    return { assistant_name: body.assistant_name };
  }

  me(): Promise<Me> {
    return this.send<Me>("/api/mobile/app/me");
  }

  lead(tail = 160): Promise<Timeline> {
    return this.send<Timeline>(`/api/mobile/app/lead?tail=${tail}`);
  }

  sendMessage(text: string): Promise<{ turn_id: string; queued: boolean }> {
    return this.send("/api/mobile/app/lead/messages", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  }

  decide(approvalId: string, decision: "allow" | "deny"): Promise<{ ok: boolean }> {
    return this.send(`/api/mobile/app/lead/approvals/${encodeURIComponent(approvalId)}`, {
      method: "POST",
      body: JSON.stringify({ decision }),
    });
  }

  voiceNote(pcm: ArrayBuffer, language: string): Promise<{ text: string }> {
    const query = language ? `&language=${encodeURIComponent(language)}` : "";
    return this.send(`/api/mobile/app/lead/voice-note?sample_rate=16000${query}`, {
      method: "POST",
      body: pcm,
      headers: { "Content-Type": "application/octet-stream" },
    });
  }

  subscribePush(subscription: PushSubscriptionJSON): Promise<{ subscribed: boolean }> {
    return this.send("/api/mobile/app/push/subscription", {
      method: "PUT",
      body: JSON.stringify({ endpoint: subscription.endpoint, keys: subscription.keys ?? {} }),
    });
  }

  unsubscribePush(): Promise<{ subscribed: boolean }> {
    return this.send("/api/mobile/app/push/subscription", { method: "DELETE" });
  }

  async unpair(): Promise<void> {
    try {
      await this.send("/api/mobile/app/unpair", { method: "POST" });
    } finally {
      this.forget();
    }
  }
}

/** The pairing code carried in `#pair=CODE`, or "". */
export function pairingCodeFromHash(hash: string): string {
  const match = /(?:^#|&)pair=([A-Za-z0-9]+)/.exec(hash || "");
  return match ? match[1].toUpperCase() : "";
}
