/**
 * The agent workspace: the roster, the open agent's chat under its header,
 * and its details pane, in the three-region frame of `AgentChatLayout`.
 * It can be embedded in the section or opened as a modal; Radix Dialog
 * provides focus containment and Escape-to-close for the modal.
 */
import { useState, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { useLocaleChunk, useT } from "@/i18n";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { useEventStore } from "@/store/events";

import type { SocietyAgent } from "../data";
import { AgentChatPanel, useSocietyChatStore } from "../chat/AgentChatPanel";
import { RosterRail } from "../roster/RosterRail";
import { useRosterActivity } from "../roster/useRosterActivity";
import type { SocietyChatGroup } from "@/lib/societyChatGroups";
import { OptionsRail } from "./OptionsRail";
import { AgentChatLayout } from "./AgentChatLayout";
import { AgentHeader } from "./AgentHeader";
import { HeaderModelSlotContext } from "./headerModelSlot";

export interface AgentCardOverlayProps {
  agent: SocietyAgent | null;
  /** Every agent — the rail lists them, the chat @mentions them. */
  roster: SocietyAgent[];
  groups?: SocietyChatGroup[];
  onSelectGroup?: (groupId: string) => void;
  onGroupAgents?: (sourceId: string, targetId: string) => void;
  onAddAgentToGroup?: (agentId: string, groupId: string) => void;
  /** True while the roster is still loading; the rail says so. */
  rosterLoading?: boolean;
  /** True until the teams have answered; the rail holds its list back until then. */
  teamsPending?: boolean;
  /** True while rows come from the sample roster rather than society.db. */
  sample?: boolean;
  /** A row in the rail was clicked: the card swaps to that agent. */
  onSelectAgent?: (agentId: string) => void;
  /** "+" in the rail opens the existing creator. */
  onCreate?: () => void;
  onClose: () => void;
  /** Render as the section workspace instead of a modal. */
  embedded?: boolean;
  /** Drawn at the top of the agent list, in the gray column. */
  railHeader?: ReactNode;
  /** The section-wide roster shortcuts listen while this is true (the section is on screen). */
  active?: boolean;
}

export function AgentCardOverlay({
  agent,
  roster,
  groups = [],
  onSelectGroup,
  onGroupAgents,
  onAddAgentToGroup,
  rosterLoading = false,
  teamsPending = false,
  sample = false,
  onSelectAgent,
  onCreate,
  onClose,
  embedded = false,
  railHeader,
  active = true,
}: AgentCardOverlayProps) {
  const t = useT();
  useLocaleChunk("society");
  const assistantName = useEventStore((s) => s.assistantName);
  const displayName = agent ? societyDisplayName(agent, assistantName) : "";
  const activity = useRosterActivity(roster, useSocietyChatStore);
  const [modelSaving, setModelSaving] = useState(false);
  const Title = embedded ? "h2" : Dialog.Title;
  const Description = embedded ? "p" : Dialog.Description;
  const content = agent ? (
    <>
      {!embedded && (
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-1.5">
          <div data-testid="agent-card-identity" className="min-w-0 flex-1">
            <Title className="truncate font-display text-sm font-semibold tracking-tight text-foreground">{displayName}</Title>
            <Description className="sr-only">{agent.title}</Description>
          </div>
          <button type="button" onClick={onClose} aria-label={t("society.card.close")}
            className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            <X className="h-4 w-4" aria-hidden />
          </button>
        </div>
      )}
      <AgentChatLayout
        resetKey={agent.agentId}
        roster={({ collapsed, onToggleCollapsed }) => (
          <RosterRail
            agents={roster}
            groups={groups}
            onOpenGroup={onSelectGroup}
            onGroupAgents={onGroupAgents}
            onAddAgentToGroup={onAddAgentToGroup}
            loading={rosterLoading}
            teamsPending={teamsPending}
            sample={sample}
            activeAgentId={agent.agentId}
            onOpen={(id) => { if (id !== agent.agentId) onSelectAgent?.(id); }}
            onCreate={() => onCreate?.()}
            side="left"
            className="w-full border-0"
            header={railHeader}
            activity={activity}
            collapsed={collapsed}
            onToggleCollapsed={onToggleCollapsed}
            keyboard={active}
          />
        )}
        header={(details) => <AgentHeader agent={agent} details={details} />}
        options={<OptionsRail agent={agent} onRetired={onClose} sample={sample} onModelSavingChange={setModelSaving} />}
      >
        <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label={t("society.card.chat")} data-testid="agent-card-chat">
          <HeaderModelSlotContext.Provider value={{ saving: modelSaving }}>
            <AgentChatPanel key={agent.agentId} agent={agent} roster={roster} />
          </HeaderModelSlotContext.Provider>
        </section>
      </AgentChatLayout>
    </>
  ) : null;
  if (embedded) {
    return <div data-testid="agent-card" className="agent-card-workspace flex min-h-0 flex-1 flex-col overflow-hidden bg-card">{content}</div>;
  }
  return (
    <Dialog.Root open={agent !== null} onOpenChange={(next) => (next ? undefined : onClose())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim/60 backdrop-blur-sm" />
        <Dialog.Content data-testid="agent-card" className="agent-card-workspace fixed inset-0 z-50 flex flex-col overflow-hidden bg-card focus:outline-none">
          {content}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
