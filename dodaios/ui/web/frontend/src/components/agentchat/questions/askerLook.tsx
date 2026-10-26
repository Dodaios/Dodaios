import { useContext, type CSSProperties } from "react";
import { QueryClientContext } from "@tanstack/react-query";
import { MessageCircleQuestion } from "lucide-react";
import { AgentSwatch, agentColor } from "@/components/society/AgentSwatch";
import type { RosterData, SocietyAgent } from "@/components/society/data";
import { bubbleTint } from "@/lib/bubbleTint";

/** The society roster's query key (components/society/data.ts). */
const ROSTER_KEY = ["society", "roster"] as const;

/**
 * Who is asking, as far as this chat already knows: the agent's face and its
 * colour. It only READS the roster the society section has loaded, so a card
 * on any other surface (front page, IDE) never triggers a fetch and simply
 * falls back to a neutral mark and the theme's primary fill.
 */
export function useAskerLook(asker: string): { agent: SocietyAgent | null; style: CSSProperties | undefined } {
  const client = useContext(QueryClientContext);
  const name = asker.trim().toLocaleLowerCase();
  const roster = name ? client?.getQueryData<RosterData>(ROSTER_KEY) : undefined;
  const agent = roster?.agents.find((a) => a.name.trim().toLocaleLowerCase() === name) ?? null;
  const tint = agent ? bubbleTint(agentColor(agent)) : null;
  const style = tint ? ({ "--qc-tint": tint.background, "--qc-tint-ink": tint.color } as CSSProperties) : undefined;
  return { agent, style };
}

export function AskerMark({ agent, size = 22 }: { agent: SocietyAgent | null; size?: number }) {
  if (agent) return <AgentSwatch agent={{ ...agent, state: undefined }} size={size} />;
  return (
    <span className="qc-mark" aria-hidden style={{ width: size, height: size }}>
      <MessageCircleQuestion className="h-3.5 w-3.5" />
    </span>
  );
}
