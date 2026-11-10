import { memo, useRef, useState } from "react";
import { fill, useT } from "@/i18n";
import { AgentChatApiError, declineAgentChatCredential, submitAgentChatCredential } from "@/lib/agentChatApi";
import { openExternalUrl } from "@/lib/openExternal";
import { postJson, useSignIn } from "@/hooks/useSignIn";
import { useAgentChat } from "./AgentChatStoreContext";
import { ChatPromptButton, ChatPromptCard } from "./ChatPromptCard";
import { ToolChoiceIcon } from "./ToolChoiceChips";
import type { CredentialState } from "./reduce";
import { serviceIconRow } from "./toolChoices";

/**
 * An agent asks the person to connect a plugin or CLI
 * (dodaios/society/connect_tool.py). The card shows the service's logo and a
 * Connect button that runs the same sign-in as the Plugins and CLIs pages.
 * Once the service reports connected, the card tells the agent's chat; the
 * backend checks the connection again before the agent hears "connected".
 */

async function cliConnected(name: string): Promise<{ connected: boolean; installed: boolean }> {
  const data = await postJson(`/api/clis/${encodeURIComponent(name)}/check`);
  return { connected: Boolean(data.connected), installed: Boolean(data.installed) };
}

export const ConnectCard = memo(function ConnectCard({ credential }: { credential: CredentialState }) {
  const t = useT();
  const sessionId = useAgentChat((s) => s.activeSessionId);
  const [resolved, setResolved] = useState<string | null>(null);
  const reporting = useRef(false);
  const status = resolved ?? credential.status;
  const label = credential.label;
  const tile = (
    <ToolChoiceIcon row={serviceIconRow(credential.kind === "plugin" ? "plugin" : "cli", credential.env, label)} size={24} />
  );

  const { phase, setPhase, watch, stop, connectPlugin, start } = useSignIn(label, () => report("connected"));

  async function report(value: "connected" | "declined") {
    if (reporting.current || !sessionId) return;
    reporting.current = true;
    try {
      const result =
        value === "connected"
          ? await submitAgentChatCredential(sessionId, credential.requestId, "connected")
          : await declineAgentChatCredential(sessionId, credential.requestId);
      stop();
      setResolved(result.status);
    } catch (err) {
      reporting.current = false;
      const closed = err instanceof AgentChatApiError && (err.status === 404 || err.status === 410);
      // "not_connected": the service is not ready yet; keep watching.
      if (closed) setPhase({ kind: "failed", message: t("credential_card.expired") });
    }
  }

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

  const connect = () => start(credential.kind === "plugin" ? () => connectPlugin(credential.env) : connectCli);

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
