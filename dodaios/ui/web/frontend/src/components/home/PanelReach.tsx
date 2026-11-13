import { useQuery } from "@tanstack/react-query";
import { Phone, PhoneOff } from "lucide-react";

import { FOCUS } from "@/components/home/panelParts";
import { fill, useT } from "@/i18n";
import { fetchLeadChannels, type LeadChannel } from "@/lib/agentChatApi";
import { requestPluginFocus } from "@/lib/customConnector";
import { openExternalUrl } from "@/lib/openExternal";
import { bundledPluginLogo } from "@/lib/pluginLogos";
import { cn } from "@/lib/utils";
import { warmVoiceCall } from "@/lib/voiceApi";
import { useEventStore } from "@/store/events";

/** The channels the panel offers, in the order it draws them. */
const CHANNELS = ["slack", "telegram"] as const;

const BUTTON = cn(
  "inline-flex h-9 min-w-0 items-center justify-center gap-1.5 rounded-lg bg-secondary px-2 text-sm font-medium text-foreground",
  "transition-colors hover:bg-surface-raised disabled:opacity-60",
  FOCUS,
);

interface CallSwitch {
  live: boolean;
  busy: boolean;
  toggle: () => void;
}

/** What a click on a channel does, said as the button's tooltip. */
function channelHint(channel: LeadChannel | undefined, label: string, name: string, t: (key: string) => string): string {
  if (!channel?.connected) return fill(t("sidebar.channel_connect"), { channel: label });
  if (!channel.url) return fill(t("sidebar.channel_connected"), { channel: label });
  if (channel.kind === "chat") return fill(t("sidebar.channel_open_chat"), { assistant: name, channel: label });
  if (!channel.handle) return fill(t("sidebar.channel_open"), { channel: label });
  return fill(t("sidebar.channel_open_workspace"), { workspace: channel.handle, channel: label });
}

/**
 * How the person reaches the assistant: a call, and the channels outside the
 * app. A connected channel wears its own name (the bot's `@name`, the
 * workspace) and opens there; one that is not connected yet leads to the
 * place where it gets connected.
 *
 * `name` is the assistant as the panel's head calls it.
 *
 * Telegram is a conversation with the assistant. Slack is a workspace it
 * works in for the person: the button opens that workspace, because nobody
 * can write to the assistant there.
 */
export function PanelReach({ call, name }: { call: CallSwitch; name: string }) {
  const t = useT();
  const setActive = useEventStore((s) => s.setActiveSection);
  const channels = useQuery({
    queryKey: ["sidebar", "lead-channels"],
    queryFn: fetchLeadChannels,
    staleTime: 30_000,
    refetchInterval: import.meta.env.MODE === "test" ? false : 60_000,
    retry: false,
  });

  const openChannel = (id: (typeof CHANNELS)[number], channel: LeadChannel | undefined) => {
    if (channel?.connected && channel.url) {
      void openExternalUrl(channel.url);
      return;
    }
    requestPluginFocus(id);
    setActive("plugins");
  };

  const CallIcon = call.live ? PhoneOff : Phone;
  return (
    <div data-testid="assistant-panel-reach" className="mt-3 flex items-stretch gap-1.5">
      <button type="button" data-testid="assistant-panel-call" data-live={call.live} disabled={call.busy}
        onClick={call.toggle} onPointerEnter={() => warmVoiceCall()} onFocus={() => warmVoiceCall()}
        title={call.live ? t("agentic_grid.voice_bubble.hang_up_title") : t("assistant_chat.voice_enter_hint")}
        className={cn(BUTTON, "shrink-0")}>
        <CallIcon aria-hidden strokeWidth={1.75} className={cn("h-4 w-4 shrink-0", call.live && "text-destructive")} />
        <span className="truncate">{call.live ? t("agentic_grid.voice_bubble.hang_up") : t("sidebar.call")}</span>
      </button>
      {CHANNELS.map((id) => {
        const channel = channels.data?.find((row) => row.id === id);
        const label = t(`sidebar.channel_${id}`);
        const hint = channelHint(channel, label, name, t);
        const logo = bundledPluginLogo(id);
        return (
          <button key={id} type="button" data-testid={`assistant-panel-channel-${id}`} data-connected={channel?.connected === true}
            onClick={() => openChannel(id, channel)} title={hint} aria-label={hint} className={cn(BUTTON, "flex-1")}>
            {logo && <img src={logo} alt="" draggable={false} className={"h-4 w-4 shrink-0 object-contain"} />}
            <span className={cn("truncate", !channel?.connected && "text-muted-foreground")}>{(channel?.connected && channel.handle) || label}</span>
          </button>
        );
      })}
    </div>
  );
}
