import { useState, type FormEvent } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useT } from "@/i18n";
import { createSocietyChatGroup, updateSocietyChatGroup, type SocietyChatGroup } from "@/lib/societyChatGroups";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { useEventStore } from "@/store/events";
import type { SocietyAgent } from "../data";
import { AgentSwatch } from "../AgentSwatch";
import "../calmSheet.css";

interface Props {
  group?: SocietyChatGroup;
  agents: SocietyAgent[];
  onClose: () => void;
  onSaved: (groupId: string) => void;
}

export function ChatGroupDialog({ group, agents, onClose, onSaved }: Props) {
  const t = useT();
  const client = useQueryClient();
  const assistantName = useEventStore((s) => s.assistantName);
  const [name, setName] = useState(group?.name ?? "");
  const [members, setMembers] = useState<string[]>(group?.members.filter((id) =>
    agents.some((agent) => agent.agentId === id && agent.lifecycle !== "archived")) ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const choices = agents.filter((agent) => agent.lifecycle !== "archived");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || members.length < 2) return;
    setBusy(true);
    setError("");
    try {
      const saved = group
        ? await updateSocietyChatGroup(group.group_id, name.trim(), members)
        : await createSocietyChatGroup(name.trim(), members);
      await client.invalidateQueries({ queryKey: ["society", "chat-groups"] });
      onSaved(saved.group_id);
      onClose();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  };

  return <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
    <Dialog.Portal>
      <Dialog.Overlay className="fixed inset-0 z-[150] bg-scrim/60" />
      <Dialog.Content className="cs-sheet fixed left-1/2 top-1/2 z-[151] flex max-h-[80vh] w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden">
        <header className="cs-head">
          <div className="cs-head-row">
            <div className="min-w-0 flex-1">
              <Dialog.Title className="cs-title">{t(group ? "society.groups.edit" : "society.groups.create")}</Dialog.Title>
              <Dialog.Description className="cs-sub">{t("society.groups.description")}</Dialog.Description>
            </div>
            <button type="button" aria-label={t("society.groups.cancel")} onClick={onClose} className="cs-close"><X size={16} aria-hidden /></button>
          </div>
        </header>
        <form onSubmit={(event) => void submit(event)} className="flex min-h-0 flex-1 flex-col">
          <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 pb-2 pt-2">
            <label className="flex flex-col gap-2">
              <span className="cs-label">{t("society.groups.name")}</span>
              <input autoFocus maxLength={80} value={name} onChange={(event) => setName(event.target.value)}
                className="w-full text-foreground" />
            </label>
            <div className="flex min-h-0 flex-col gap-2">
              <p className="cs-label">{t("society.groups.members")} <span className="font-normal text-muted-foreground">{members.length}</span></p>
              <div className="cs-card">
                {choices.map((agent) => {
                  const on = members.includes(agent.agentId);
                  return <label key={agent.agentId} className="cs-row min-h-[52px]">
                    <input type="checkbox" className="peer sr-only" checked={on} onChange={() => setMembers((current) => current.includes(agent.agentId) ? current.filter((id) => id !== agent.agentId) : [...current, agent.agentId])} />
                    <AgentSwatch agent={agent} size={30} />
                    <span className="cs-row-text">{societyDisplayName(agent, assistantName)}</span>
                    {group?.lead_agent_id === agent.agentId && <span className="cs-row-end">{t("society.lead.role")}</span>}
                    <span className="cs-tick peer-focus-visible:ring-2 peer-focus-visible:ring-ring" data-on={on} aria-hidden>{on ? <Check className="size-3.5" strokeWidth={3} /> : null}</span>
                  </label>;
                })}
              </div>
            </div>
            {error && <p role="alert" className="cs-hint" data-tone="error">{error}</p>}
          </div>
          <footer className="cs-foot">
            <button type="button" onClick={onClose} className="cs-btn" data-variant="ghost">{t("society.groups.cancel")}</button>
            <button type="submit" disabled={busy || !name.trim() || members.length < 2}
              className="cs-btn" data-variant="primary">{t("society.groups.save")}</button>
          </footer>
        </form>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
