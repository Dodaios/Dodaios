import { useMemo, useRef, useState } from "react";
import { SquareTerminal } from "lucide-react";
import { fill, useT } from "@/i18n";
import { promptTerminal, type WorkspacePaneRow } from "@/lib/agenticIdeApi";
import { useEventStore } from "@/store/events";
import { useIdeSkillsStore } from "@/store/ideSkills";
import { useWorkspacePanes } from "@/store/workspacePanes";
import { AgentMark } from "@/components/agentic/AgentMark";
import { ThreadMenuHeading, ThreadMenuItem, ThreadPopover } from "@/components/agentic/threads/ThreadPopover";

/** The longest prompt a terminal takes (`MAX_PROMPT_CHARS` in the backend). */
export const MAX_TERMINAL_CHARS = 6000;

/**
 * "Send to a terminal" under a chat answer: pick one of the open coding
 * agents and the answer is typed into it and submitted.
 *
 * Two clicks on purpose. An answer lands in a running agent's prompt, so the
 * terminal is always chosen by name, never assumed. The pane selected in the
 * grid leads the list.
 */
export function SendToTerminal({ text }: { text: string }) {
  const t = useT();
  const anchor = useRef<HTMLButtonElement | null>(null);
  const [open, setOpen] = useState(false);
  const [sending, setSending] = useState(false);
  // The shared pane poll runs only while a list is open.
  const panes = useWorkspacePanes(open);
  const selected = useIdeSkillsStore((state) => state.target);
  const pushToast = useEventStore((state) => state.pushToast);

  const groups = useMemo(() => {
    // Only a running agent takes a prompt; a plain shell would run the text as a command.
    const targets = panes.filter((pane) => pane.accepts_prompts && pane.status !== "exited" && pane.status !== "error");
    const isSelected = (pane: WorkspacePaneRow) =>
      Boolean(selected) && pane.workspace_id === selected!.workspaceId && (pane.key === selected!.pane || pane.name === selected!.pane);
    const byWorkspace = new Map<string, { name: string; active: boolean; panes: WorkspacePaneRow[] }>();
    for (const pane of targets) {
      const group = byWorkspace.get(pane.workspace_id) ?? { name: pane.workspace_name, active: pane.workspace_active, panes: [] };
      group.panes.push(pane);
      byWorkspace.set(pane.workspace_id, group);
    }
    return [...byWorkspace.values()]
      .sort((a, b) => Number(b.active) - Number(a.active))
      .map((group) => ({ ...group, panes: [...group.panes].sort((a, b) => Number(isSelected(b)) - Number(isSelected(a))), isSelected }));
  }, [panes, selected]);

  const send = async (pane: WorkspacePaneRow) => {
    setOpen(false);
    if (text.length > MAX_TERMINAL_CHARS) {
      pushToast("warning", fill(t("ide_side_panel.chat.too_long"), { count: text.length, max: MAX_TERMINAL_CHARS }));
      return;
    }
    setSending(true);
    try {
      const result = await promptTerminal(pane.key, text, { compose: false, workspaceId: pane.workspace_id });
      // Three answers: it started, the text is provably still in the input box, or nobody can say.
      const key = result.submitted === true ? "sent" : result.submitted === false ? "not_accepted" : "unconfirmed";
      pushToast(result.submitted === true ? "success" : "warning", fill(t(`ide_side_panel.chat.${key}`), { pane: pane.name }));
    } catch (failure) {
      pushToast("error", failure instanceof Error ? failure.message : String(failure));
    } finally {
      setSending(false);
    }
  };

  const label = t("ide_side_panel.chat.send_to_terminal");
  return <>
    <button ref={anchor} type="button" aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open}
      disabled={sending} onClick={() => setOpen((value) => !value)} data-testid="side-chat-send-to-terminal"
      className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-40">
      <SquareTerminal className="h-3.5 w-3.5" />
    </button>
    <ThreadPopover anchor={anchor} open={open} onClose={() => setOpen(false)} side="top" width={320} label={label}>
      {groups.length === 0 && <p className="px-2 py-2 text-sm text-muted-foreground">{t("ide_side_panel.chat.no_terminal")}</p>}
      {groups.map((group) => <div key={group.name}>
        {groups.length > 1 && <ThreadMenuHeading>{group.name}</ThreadMenuHeading>}
        {group.panes.map((pane) => <ThreadMenuItem key={`${pane.workspace_id}:${pane.key}`}
          icon={<AgentMark agent={pane.agent} label={pane.display_name} variant="plain" size="sm" />}
          label={pane.recap ? `${pane.name} · ${pane.recap}` : pane.name}
          selected={group.isSelected(pane)}
          onSelect={() => void send(pane)} />)}
      </div>)}
    </ThreadPopover>
  </>;
}
