import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, ExternalLink, Loader2 } from "lucide-react";

import { Panel, SoftButton } from "@/components/extensions/primitives";
import { fill, translate } from "@/i18n";
import { robustCopy } from "@/lib/clipboard";
import { openExternalUrl } from "@/lib/openExternal";
import {
  connectSlackChannel,
  disconnectSlackChannel,
  fetchSlackChannel,
  pairSlackAgain,
  SlackConnectError,
  type SlackChannelState,
} from "@/lib/slackChannelApi";
import { cn } from "@/lib/utils";

const FIELD =
  "mt-2 w-full rounded-md bg-input px-3 py-2 font-mono text-xs text-foreground placeholder:text-faint-foreground focus:border-border-strong focus:outline-none focus:ring-2 focus:ring-border-strong/30";

const ERROR_CODES = new Set([
  "bot_token_shape",
  "app_token_shape",
  "bot_token_rejected",
  "app_token_rejected",
  "socket_mode_off",
  "different_apps",
  "slack_unreachable",
  "store_failed",
]);

function errorText(err: unknown): string {
  if (err instanceof SlackConnectError && ERROR_CODES.has(err.code)) {
    return translate(`slack_chat.err_${err.code}`);
  }
  return err instanceof Error ? err.message : translate("slack_chat.err_unknown");
}

function Step({ num, title, children }: { num: number; title: string; children?: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden
        className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-secondary text-micro font-medium text-foreground"
      >
        {num}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-base text-foreground">{title}</p>
        {children}
      </div>
    </li>
  );
}

/**
 * "Chat with the assistant in Slack": the owner's own Slack app as a
 * conversation channel, shown on the Slack plugin's page under Access.
 *
 * Not connected: three steps (create the app from the prefilled manifest,
 * install it, paste its two keys). Connected: one state line, who it answers,
 * and one button that opens the direct message with the app.
 */
export function SlackChatCard() {
  const queryClient = useQueryClient();
  const state = useQuery({
    queryKey: ["slack-channel"],
    queryFn: fetchSlackChannel,
    retry: false,
    refetchInterval: (query) => {
      if (import.meta.env.MODE === "test") return false;
      const data = query.state.data as SlackChannelState | undefined;
      return data?.pairing_open || (data?.enabled && !data?.link_up) ? 4_000 : 30_000;
    },
  });
  const [botToken, setBotToken] = useState("");
  const [appToken, setAppToken] = useState("");
  const [copied, setCopied] = useState(false);
  const settle = (next: SlackChannelState) => {
    queryClient.setQueryData(["slack-channel"], next);
    void queryClient.invalidateQueries({ queryKey: ["sidebar", "lead-channels"] });
  };
  const connect = useMutation({
    mutationFn: () => connectSlackChannel(botToken, appToken),
    onSuccess: (next) => {
      setBotToken("");
      setAppToken("");
      settle(next);
    },
  });
  const pair = useMutation({ mutationFn: pairSlackAgain, onSuccess: settle });
  const disconnect = useMutation({ mutationFn: disconnectSlackChannel, onSuccess: settle });

  const data = state.data;
  const assistant = data?.assistant || "Nova";
  const sectionLabel = "px-1 text-sm text-muted-foreground";
  const configured = Boolean(data?.enabled && data?.keys_saved);

  const copyManifest = async () => {
    if (!data) return;
    if (await robustCopy(JSON.stringify(data.manifest, null, 2))) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    }
  };

  return (
    <section aria-labelledby="slack-chat" className="flex flex-col gap-2" data-testid="slack-chat-card">
      <h4 id="slack-chat" className={sectionLabel}>
        {fill(translate("slack_chat.title"), { assistant })}
      </h4>
      <Panel>
        <div className="flex flex-col gap-4 px-5 py-4">
          {state.isError && (
            <p className="text-sm text-destructive">{translate("slack_chat.err_state")}</p>
          )}
          {data && configured ? (
            <ConnectedState
              data={data}
              busy={pair.isPending || disconnect.isPending}
              onPair={() => pair.mutate()}
              onDisconnect={() => disconnect.mutate()}
            />
          ) : (
            data && (
              <>
                <p className="text-base text-muted-foreground">
                  {fill(translate("slack_chat.intro"), { assistant })}
                </p>
                <ol className="flex flex-col gap-4">
                  <Step num={1} title={translate("slack_chat.step_create")}>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {translate("slack_chat.step_create_hint")}
                    </p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <SoftButton primary onClick={() => void openExternalUrl(data.create_app_url)}>
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                        {fill(translate("slack_chat.create_app"), { assistant })}
                      </SoftButton>
                      <SoftButton onClick={() => void copyManifest()}>
                        {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
                        {translate(copied ? "slack_chat.copied" : "slack_chat.copy_manifest")}
                      </SoftButton>
                    </div>
                  </Step>
                  <Step num={2} title={translate("slack_chat.step_bot")}>
                    <p className="mt-1 text-sm text-muted-foreground">{translate("slack_chat.step_bot_hint")}</p>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      aria-label={translate("slack_chat.bot_token")}
                      data-testid="slack-chat-bot-token"
                      value={botToken}
                      onChange={(e) => setBotToken(e.target.value)}
                      placeholder="xoxb-…"
                      className={FIELD}
                      disabled={connect.isPending}
                    />
                  </Step>
                  <Step num={3} title={translate("slack_chat.step_app")}>
                    <p className="mt-1 text-sm text-muted-foreground">{translate("slack_chat.step_app_hint")}</p>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      aria-label={translate("slack_chat.app_token")}
                      data-testid="slack-chat-app-token"
                      value={appToken}
                      onChange={(e) => setAppToken(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && botToken.trim() && appToken.trim()) connect.mutate();
                      }}
                      placeholder="xapp-…"
                      className={FIELD}
                      disabled={connect.isPending}
                    />
                  </Step>
                </ol>
                {connect.isError && (
                  <p role="alert" data-testid="slack-chat-error" className="text-sm text-destructive">
                    {errorText(connect.error)}
                  </p>
                )}
                {data.enabled && !data.keys_saved && (
                  <p className="text-sm text-muted-foreground">{translate("slack_chat.keys_missing")}</p>
                )}
                <div className="flex justify-end">
                  <SoftButton
                    primary
                    className="min-w-28 justify-center"
                    disabled={connect.isPending || !botToken.trim() || !appToken.trim()}
                    onClick={() => connect.mutate()}
                  >
                    {connect.isPending && <Loader2 className="animate-spin" />}
                    {translate("plugins_view.connect")}
                  </SoftButton>
                </div>
              </>
            )
          )}
          {!data && state.isLoading && (
            <p className="text-sm text-muted-foreground">{translate("slack_chat.loading")}</p>
          )}
        </div>
      </Panel>
    </section>
  );
}

function ConnectedState({
  data,
  busy,
  onPair,
  onDisconnect,
}: {
  data: SlackChannelState;
  busy: boolean;
  onPair: () => void;
  onDisconnect: () => void;
}) {
  const assistant = data.assistant || "Nova";
  const where = data.team_name || translate("slack_chat.your_workspace");
  let line: string;
  let tone: "ok" | "warn" | "error";
  if (data.running && data.link_up) {
    line = data.bot_name
      ? fill(translate("slack_chat.connected_as"), { workspace: where, bot: `@${data.bot_name}` })
      : fill(translate("slack_chat.connected"), { workspace: where });
    tone = "ok";
  } else if (data.running || data.retrying) {
    line = translate("slack_chat.reconnecting");
    tone = "warn";
  } else {
    line = translate("slack_chat.not_running");
    tone = "error";
  }
  const minutes = Math.max(1, Math.ceil(data.pairing_seconds_left / 60));
  let owner: string;
  if (data.owner_paired) owner = translate("slack_chat.owner_paired");
  else if (data.pairing_open) owner = fill(translate("slack_chat.pairing_open"), { assistant, minutes: String(minutes) });
  else owner = translate("slack_chat.pairing_closed");
  const dot = { ok: "bg-success", warn: "bg-foreground", error: "bg-destructive" }[tone];

  return (
    <div className="flex flex-col gap-3" data-testid="slack-chat-connected">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 flex-col gap-1">
          <p className="flex items-center gap-2 text-base text-foreground">
            <span className={cn("h-2 w-2 shrink-0 rounded-full", dot)} aria-hidden />
            <span className="min-w-0 break-words" data-testid="slack-chat-state">{line}</span>
          </p>
          {data.error && tone !== "ok" && (
            <p className="break-words text-sm text-muted-foreground">{data.error}</p>
          )}
          <p className="text-sm text-muted-foreground" data-testid="slack-chat-owner">{owner}</p>
        </div>
        {data.dm_url && data.running && (
          <SoftButton primary className="shrink-0" onClick={() => void openExternalUrl(data.dm_url)}>
            <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            {translate("slack_chat.open_dm")}
          </SoftButton>
        )}
      </div>
      <div className="flex flex-wrap justify-end gap-2">
        {!data.pairing_open && (
          <SoftButton disabled={busy} onClick={onPair}>
            {translate(data.owner_paired ? "slack_chat.pair_someone_else" : "slack_chat.pair_again")}
          </SoftButton>
        )}
        <SoftButton disabled={busy} onClick={onDisconnect}>
          {translate("plugins_view.disconnect")}
        </SoftButton>
      </div>
    </div>
  );
}
