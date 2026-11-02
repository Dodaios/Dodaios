import { memo, useEffect, useRef, useState } from "react";
import { fill, useT } from "@/i18n";
import { AgentChatApiError, declineAgentChatCredential, submitAgentChatCredential } from "@/lib/agentChatApi";
import { requestPluginFocus } from "@/lib/customConnector";
import { openExternalUrl } from "@/lib/openExternal";
import { useEventStore } from "@/store/events";
import { useAgentChat } from "./AgentChatStoreContext";
import { ChatPromptButton, ChatPromptCard } from "./ChatPromptCard";
import { ToolChoiceIcon } from "./ToolChoiceChips";
import type { CredentialState } from "./reduce";
import type { ToolChoice } from "./toolChoices";

/**
 * An agent asks the person to connect a plugin or CLI
 * (dodaios/society/connect_tool.py). The card shows the service's logo and a
 * Connect button that runs the same sign-in as the Plugins and CLIs pages.
 * Once the service reports connected, the card tells the agent's chat; the
 * backend checks the connection again before the agent hears "connected".
 */

const POLL_MS = 2_500;
const GIVE_UP_MS = 10 * 60_000;

type Phase =
  | { kind: "idle" }
  | { kind: "waiting"; code?: string; verifyUrl?: string }
  | { kind: "failed"; message: string };

function iconRow(credential: CredentialState): ToolChoice {
  const plugin = credential.kind === "plugin";
  return {
    id: `${plugin ? "plugin" : "cli"}:${credential.env}`,
    label: credential.label,
    description: "",
    category: plugin ? "plugins" : "cli",
    group: "",
    brand: credential.env,
    available: false,
    tool_names: [],
    skill: "",
  };
}

async function postJson(url: string, body?: unknown): Promise<Record<string, unknown>> {
  const res = await fetch(url, {
    method: "POST",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) throw new Error(String(data.error_code ?? data.detail ?? `HTTP ${res.status}`));
  return data;
}

async function pluginConnected(id: string): Promise<boolean> {
  const res = await fetch("/api/marketplace/plugins");
  if (!res.ok) return false;
  const data = (await res.json()) as { plugins?: { id: string; status?: string }[] };
  return (data.plugins ?? []).some((p) => p.id === id && p.status === "connected");
}

async function cliConnected(name: string): Promise<{ connected: boolean; installed: boolean }> {
  const data = await postJson(`/api/clis/${encodeURIComponent(name)}/check`);
  return { connected: Boolean(data.connected), installed: Boolean(data.installed) };
}

export const ConnectCard = memo(function ConnectCard({ credential }: { credential: CredentialState }) {
  const t = useT();
  const sessionId = useAgentChat((s) => s.activeSessionId);
  const setActiveSection = useEventStore((s) => s.setActiveSection);
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [resolved, setResolved] = useState<string | null>(null);
  const stop = useRef<() => void>(() => {});
  const reporting = useRef(false);
  const status = resolved ?? credential.status;
  const label = credential.label;
  const tile = <ToolChoiceIcon row={iconRow(credential)} size={24} />;

  useEffect(() => () => stop.current(), []);

  const report = async (value: "connected" | "declined") => {
    if (reporting.current || !sessionId) return;
    reporting.current = true;
    try {
      const result =
        value === "connected"
          ? await submitAgentChatCredential(sessionId, credential.requestId, "connected")
          : await declineAgentChatCredential(sessionId, credential.requestId);
      stop.current();
      setResolved(result.status);
    } catch (err) {
      reporting.current = false;
      const closed = err instanceof AgentChatApiError && (err.status === 404 || err.status === 410);
      // "not_connected": the service is not ready yet; keep watching.
      if (closed) setPhase({ kind: "failed", message: t("credential_card.expired") });
    }
  };

  /** Watch until the service is connected, then report it once. */
  const watch = (check: () => Promise<boolean>) => {
    stop.current();
    let alive = true;
    const started = Date.now();
    const tick = async () => {
      if (!alive) return;
      try {
        if (await check()) {
          alive = false;
          await report("connected");
          return;
        }
      } catch {
        // A failed check is retried on the next tick.
      }
      if (Date.now() - started > GIVE_UP_MS) {
        alive = false;
        setPhase({ kind: "failed", message: t("connect_card.timeout") });
        return;
      }
      timer = window.setTimeout(() => void tick(), POLL_MS);
    };
    let timer = window.setTimeout(() => void tick(), POLL_MS);
    stop.current = () => {
      alive = false;
      window.clearTimeout(timer);
    };
  };

  const connectPlugin = async () => {
    const id = credential.env;
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
        stop.current();
        setPhase({ kind: "failed", message: fill(t("connect_card.failed"), { label }) });
        return false;
      }
      return data.state === "connected";
    });
  };

  const connectCli = async () => {
    const name = credential.env;
    const state = await cliConnected(name).catch(() => ({ connected: false, installed: true }));
    if (state.connected) {
      await report("connected");
      return;
    }
    await postJson(`/api/clis/${encodeURIComponent(name)}/spawn-external`, {
      kind: state.installed ? "login" : "install",
      method: null,
    });
    setPhase({ kind: "waiting" });
    watch(async () => (await cliConnected(name)).connected);
  };

  const connect = () => {
    setPhase({ kind: "waiting" });
    const run = credential.kind === "plugin" ? connectPlugin : connectCli;
    run().catch(() => setPhase({ kind: "failed", message: fill(t("connect_card.failed"), { label }) }));
  };

  if (status !== null) {
    const done = status === "saved";
    return (
      <ChatPromptCard
        testId="connect-card"
        tile={tile}
        title={fill(t("connect_card.title"), { label })}
        settled={{
          tone: done ? "success" : "muted",
          label: fill(t(done ? "connect_card.connected" : "connect_card.declined"), { label }),
        }}
      />
    );
  }

  const subtitle =
    phase.kind === "waiting"
      ? phase.code
        ? fill(t("connect_card.code"), { code: phase.code })
        : t("connect_card.waiting")
      : phase.kind === "failed"
        ? phase.message
        : credential.description || fill(t("connect_card.subtitle"), { agent: credential.asker || t("credential_card.fallback_agent") });

  return (
    <div className="flex flex-col">
      <ChatPromptCard
        testId="connect-card"
        tile={tile}
        title={fill(t("connect_card.title"), { label })}
        subtitle={subtitle}
        action={
          <span className="flex shrink-0 items-center gap-1">
            {phase.kind !== "waiting" ? (
              <button
                type="button"
                onClick={() => void report("declined")}
                className="rounded-full px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted"
              >
                {t("connect_card.not_now")}
              </button>
            ) : null}
            <ChatPromptButton onClick={connect} disabled={phase.kind === "waiting"} testId="connect-card-connect">
              {phase.kind === "waiting" ? t("connect_card.connecting") : t("connect_card.connect")}
            </ChatPromptButton>
          </span>
        }
      />
      {phase.kind === "waiting" && phase.verifyUrl ? (
        <button
          type="button"
          onClick={() => void openExternalUrl(phase.verifyUrl!)}
          className="-mt-1 mb-2 ml-1 self-start text-xs text-muted-foreground underline-offset-2 hover:underline"
        >
          {t("connect_card.open_again")}
        </button>
      ) : null}
    </div>
  );
});
