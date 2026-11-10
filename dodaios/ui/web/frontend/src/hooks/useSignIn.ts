import { useEffect, useRef, useState } from "react";
import { fill, useT } from "@/i18n";
import { requestPluginFocus } from "@/lib/customConnector";
import { openExternalUrl } from "@/lib/openExternal";
import { useEventStore } from "@/store/events";

/**
 * The sign-in a Connect button runs, shared by the card an agent puts in the
 * chat (ConnectCard) and the notice for a connection that ended
 * (PluginReconnectNotices): start the plugin's own sign-in, then watch until
 * the service reports connected.
 */

const POLL_MS = 2_500;
const GIVE_UP_MS = 10 * 60_000;

export type SignInPhase =
  | { kind: "idle" }
  | { kind: "waiting"; code?: string; verifyUrl?: string }
  | { kind: "failed"; message: string };

export async function postJson(url: string, body?: unknown): Promise<Record<string, unknown>> {
  const res = await fetch(url, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) throw new Error(String(data.error_code ?? data.detail ?? `HTTP ${res.status}`));
  return data;
}

export async function pluginConnected(id: string): Promise<boolean> {
  const res = await fetch("/api/marketplace/plugins");
  if (!res.ok) return false;
  const data = (await res.json()) as { plugins?: { id: string; status?: string }[] };
  return (data.plugins ?? []).some((p) => p.id === id && p.status === "connected");
}

export function useSignIn(label: string, onConnected: () => void | Promise<void>) {
  const t = useT();
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const [phase, setPhase] = useState<SignInPhase>({ kind: "idle" });
  const stopRef = useRef<() => void>(() => {});
  const connectedRef = useRef(onConnected);

  useEffect(() => {
    connectedRef.current = onConnected;
  });
  useEffect(() => () => stopRef.current(), []);

  const stop = () => stopRef.current();

  /** Watch until the service is connected, then say so once. */
  const watch = (check: () => Promise<boolean>) => {
    stopRef.current();
    let alive = true;
    const started = Date.now();
    const tick = async () => {
      if (!alive) return;
      try {
        if (await check()) {
          alive = false;
          await connectedRef.current();
          return;
        }
      } catch {
        // A failed check is retried on the next tick.
      }
      if (!alive) return;
      if (Date.now() - started > GIVE_UP_MS) {
        alive = false;
        setPhase({ kind: "failed", message: t("connect_card.timeout") });
        return;
      }
      timer = window.setTimeout(() => void tick(), POLL_MS);
    };
    let timer = window.setTimeout(() => void tick(), POLL_MS);
    stopRef.current = () => {
      alive = false;
      window.clearTimeout(timer);
    };
  };

  const connectPlugin = async (id: string) => {
    let flow: Record<string, unknown>;
    try {
      flow = await postJson(`/api/marketplace/plugins/${encodeURIComponent(id)}/connect/start`);
    } catch {
      // Token paste, an instance address or a pending client: the Plugins page
      // has the full dialog. The card keeps watching for the connection.
      requestPluginFocus(id);
      setActiveSection("plugins");
      setPhase({ kind: "waiting" });
      watch(() => pluginConnected(id));
      return;
    }
    const flowId = String(flow.flow_id ?? "");
    if (flow.kind === "device_flow") {
      const verifyUrl = String(flow.verification_uri_complete ?? flow.verification_uri ?? "");
      if (verifyUrl) await openExternalUrl(verifyUrl);
      setPhase({ kind: "waiting", code: String(flow.user_code ?? ""), verifyUrl });
    } else {
      if (flow.open_url) await openExternalUrl(String(flow.open_url));
      setPhase({ kind: "waiting" });
    }
    if (flow.kind === "local" || !flowId) {
      watch(() => pluginConnected(id));
      return;
    }
    watch(async () => {
      const res = await fetch(
        `/api/marketplace/plugins/${encodeURIComponent(id)}/connect/poll/${encodeURIComponent(flowId)}`,
      );
      if (res.status === 404) return pluginConnected(id);
      const data = (await res.json()) as { state?: string; error?: string };
      if (data.state === "error") {
        stopRef.current();
        setPhase({ kind: "failed", message: fill(t("connect_card.failed"), { label }) });
        return false;
      }
      return data.state === "connected";
    });
  };

  /** Run one sign-in; whatever it throws ends as the card's "try again" line. */
  const start = (run: () => Promise<void>) => {
    setPhase({ kind: "waiting" });
    run().catch(() => setPhase({ kind: "failed", message: fill(t("connect_card.failed"), { label }) }));
  };

  return { phase, setPhase, watch, stop, connectPlugin, start };
}
