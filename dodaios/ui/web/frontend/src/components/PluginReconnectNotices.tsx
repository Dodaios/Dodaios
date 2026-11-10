import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { ChatPromptButton, ChatPromptCard } from "@/components/agentchat/ChatPromptCard";
import { ToolChoiceIcon } from "@/components/agentchat/ToolChoiceChips";
import { serviceIconRow } from "@/components/agentchat/toolChoices";
import { refreshPluginAttention, usePluginAttention, type PluginAttentionItem } from "@/hooks/usePluginAttention";
import { useSignIn } from "@/hooks/useSignIn";
import { fill, useT } from "@/i18n";

/**
 * A plugin's connection ended (the provider withdrew or expired the grant):
 * one small card per plugin with its logo and a Reconnect button that runs the
 * plugin's own sign-in. Closing a card hides it for that disconnect; a later
 * disconnect of the same plugin shows a new one.
 */

const DISMISSED_KEY = "dodaios.plugin_reconnect.dismissed";
const MAX_VISIBLE = 3;
const DONE_MS = 4_000;

function noticeKey(item: PluginAttentionItem): string {
  return `${item.id}@${item.reauthAt ?? ""}`;
}

function readDismissed(): string[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) ?? "[]") as unknown;
    return Array.isArray(raw) ? raw.filter((key): key is string => typeof key === "string") : [];
  } catch {
    return [];
  }
}

function writeDismissed(keys: string[]): void {
  try {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(keys.slice(-200)));
  } catch {
    // Without storage the card is hidden until the next start.
  }
}

export function PluginReconnectNotices() {
  const attention = usePluginAttention();
  const [dismissed, setDismissed] = useState<string[]>(readDismissed);
  // Just reconnected: the card says so for a moment before it leaves.
  const [done, setDone] = useState<PluginAttentionItem[]>([]);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const pending = timers.current;
    return () => pending.forEach((id) => window.clearTimeout(id));
  }, []);

  const dismiss = (item: PluginAttentionItem) => {
    const next = [...dismissed.filter((key) => key !== noticeKey(item)), noticeKey(item)];
    setDismissed(next);
    writeDismissed(next);
  };

  const connected = (item: PluginAttentionItem) => {
    setDone((rows) => [...rows.filter((row) => row.id !== item.id), item]);
    void refreshPluginAttention();
    timers.current.push(
      window.setTimeout(() => setDone((rows) => rows.filter((row) => row.id !== item.id)), DONE_MS),
    );
  };

  const open = attention.items.filter(
    (item) => item.status === "needs_reauth" && item.id && !dismissed.includes(noticeKey(item)),
  );
  const rows = [...done, ...open.filter((item) => !done.some((row) => row.id === item.id))]
    // The newest disconnect first; a row without a date goes last.
    .sort((a, b) => (b.reauthAt ?? "").localeCompare(a.reauthAt ?? "") || a.name.localeCompare(b.name))
    .slice(0, MAX_VISIBLE);

  return (
    <>
      {rows.map((item) => (
        <ReconnectNotice
          key={item.id}
          item={item}
          onDismiss={() => dismiss(item)}
          onConnected={() => connected(item)}
        />
      ))}
    </>
  );
}

function ReconnectNotice({
  item,
  onDismiss,
  onConnected,
}: {
  item: PluginAttentionItem;
  onDismiss: () => void;
  onConnected: () => void;
}) {
  const t = useT();
  const label = item.name || item.id;
  const [connected, setConnected] = useState(false);
  const { phase, connectPlugin, start } = useSignIn(label, () => {
    setConnected(true);
    onConnected();
  });
  const tile = <ToolChoiceIcon row={serviceIconRow("plugin", item.id, label)} size={24} />;
  const look = "pointer-events-auto my-0 w-[400px] max-w-[calc(100vw-2rem)] shadow-lg animate-in slide-in-from-right-4 fade-in duration-200";

  if (connected) {
    return (
      <ChatPromptCard
        testId="plugin-reconnect-notice"
        className={look}
        tile={tile}
        title={label}
        settled={{ tone: "success", label: fill(t("connect_card.connected"), { label }) }}
      />
    );
  }

  const subtitle =
    phase.kind === "waiting"
      ? phase.code
        ? fill(t("plugin_reconnect.code"), { code: phase.code })
        : t("plugin_reconnect.waiting")
      : phase.kind === "failed"
        ? phase.message
        : t("plugin_reconnect.subtitle");

  return (
    <ChatPromptCard
      testId="plugin-reconnect-notice"
      className={look}
      tile={tile}
      title={label}
      subtitle={<span title={typeof subtitle === "string" ? subtitle : undefined}>{subtitle}</span>}
      action={
        <span className="flex shrink-0 items-center gap-1.5">
          <ChatPromptButton
            onClick={() => start(() => connectPlugin(item.id))}
            disabled={phase.kind === "waiting"}
            testId="plugin-reconnect-connect"
          >
            {phase.kind === "waiting" ? t("connect_card.connecting") : t("plugin_reconnect.action")}
          </ChatPromptButton>
          <button
            type="button"
            onClick={onDismiss}
            aria-label={t("common.dismiss")}
            title={t("common.dismiss")}
            data-testid="plugin-reconnect-dismiss"
            className="grid h-7 w-7 shrink-0 place-items-center rounded-full text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X aria-hidden className="h-3.5 w-3.5" />
          </button>
        </span>
      }
    />
  );
}
