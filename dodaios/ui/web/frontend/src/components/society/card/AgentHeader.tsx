/**
 * The chat's header bar: who this is and what it is doing on the left; what
 * it thinks with and how freely it may act on the right; then the details
 * toggle. "Who and how" lives here, "what to say" lives in the composer.
 *
 * The brain picker is the composer's own `AgentModelPicker`, moved up; it
 * already knows every runtime (a Hermes or OpenClaw agent shows its
 * runtime-locked state inside it). The approval picker only offers what the
 * agent's runner can honour and asks once more before loosening a mode.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ChevronDown, Shield, ShieldAlert, ShieldOff, ShieldQuestion } from "lucide-react";

import { AgentChatStoreProvider } from "@/components/agentchat/AgentChatStoreContext";
import { useT } from "@/i18n";
import { fetchSocietyProviders, type AgentApprovalMode, type SocietyAgentRow } from "@/lib/societyApi";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import { AgentSwatch } from "../AgentSwatch";
import { agentTint } from "../agentTint";
import { rowToAgent, type SocietyAgent } from "../data";
import { AgentModelPicker } from "../chat/AgentModelPicker";
import { useSocietyChatStore } from "../chat/AgentChatPanel";
import { previewText, rosterStatus, waitingReasonOf } from "../roster/rosterPreview";
import { StatusMark } from "../roster/RosterRow";
import { AGENT_APPROVAL_MODES, modeSupported, runnerFor } from "./approvalModes";

const MODE_ICON: Record<AgentApprovalMode | "legacy", typeof Shield> = {
  bypass: ShieldOff,
  ask: ShieldQuestion,
  always_ask: ShieldAlert,
  legacy: Shield,
};

/** How strict a mode is; choosing a lower number loosens what the agent may do unasked. */
const STRICTNESS: Record<AgentApprovalMode | "legacy", number> = { bypass: 0, legacy: 1, ask: 1, always_ask: 2 };

export interface AgentHeaderProps {
  agent: SocietyAgent;
  sample?: boolean;
  /** The details-pane toggle; the layout owns it so its state and focus survive. */
  detailsToggle?: ReactNode;
  /** Reports a model save in flight so the composer holds Send meanwhile. */
  onModelSavingChange?: (saving: boolean) => void;
}

export function AgentHeader({ agent, sample = false, detailsToggle, onModelSavingChange }: AgentHeaderProps) {
  const t = useT();
  const assistantName = useEventStore((state) => state.assistantName);
  const displayName = societyDisplayName(agent, assistantName);
  const lead = agent.tier === "lead";
  const busy = useSocietyChatStore((state) => state.busy && state.activeSessionId === agent.chatSessionId);
  const status = rosterStatus(agent, false);
  const reason = waitingReasonOf(agent);

  let phrase: ReactNode;
  if (status === "needs-you") {
    const summary = previewText(reason?.summary);
    phrase = <span className="truncate text-warning">{summary ? `${t("society.shell.preview_needs_you")} · ${summary}` : t("society.shell.status_waiting")}</span>;
  } else if (status === "working") {
    phrase = <span className="as-shimmer truncate">{t("society.shell.preview_working")}</span>;
  } else if (status === "paused") {
    phrase = <span className="truncate">{t("society.state.paused")}</span>;
  } else {
    phrase = <span className="truncate">{agent.title || t("society.state.idle")}</span>;
  }

  return (
    <header className="as-header" data-testid="agent-header" style={agentTint(agent)}>
      <span className="as-avatar">
        <AgentSwatch agent={agent} size={30} />
        <StatusMark status={status} className="[background:hsl(var(--background))]" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <h2 className="truncate text-[13.5px] font-semibold leading-[18px] text-foreground-strong" data-testid="agent-header-name">{displayName}</h2>
        <p className="flex min-w-0 text-xs leading-4 text-muted-foreground" aria-live="polite" data-testid="agent-header-status">{phrase}</p>
      </div>
      {!lead ? (
        <div className="as-header-slot" data-testid="agent-header-model">
          <AgentChatStoreProvider store={useSocietyChatStore}>
            <AgentModelPicker key={agent.agentId} agent={agent} busy={busy} onSavingChange={(saving) => onModelSavingChange?.(saving)} />
          </AgentChatStoreProvider>
        </div>
      ) : null}
      {!lead && !sample ? <ApprovalModePicker agent={agent} /> : null}
      {detailsToggle ? (
        <>
          <span aria-hidden className="mx-0.5 h-5 w-px bg-border" />
          {detailsToggle}
        </>
      ) : null}
    </header>
  );
}

export function ApprovalModePicker({ agent }: { agent: SocietyAgent }) {
  const t = useT();
  const client = useQueryClient();
  const menuId = useId();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState<AgentApprovalMode | null>(null);
  const root = useRef<HTMLDivElement>(null);
  const providers = useQuery({ queryKey: ["society", "providers"], queryFn: fetchSocietyProviders, staleTime: 60_000 });
  const runner = runnerFor(agent, providers.data);
  const current = agent.approvalMode ?? null;
  const currentKey = current ?? "legacy";
  const Icon = MODE_ICON[currentKey];
  const label = current ? t(`society.approval_mode.${current}`) : t("society.shell.approval_legacy");

  useEffect(() => {
    if (!open) return;
    const onDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        root.current?.querySelector<HTMLButtonElement>("[data-approval-trigger]")?.focus();
      }
    };
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    root.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"]:not([disabled])')?.focus();
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  useEffect(() => {
    setOpen(false);
    setError("");
    setConfirming(null);
  }, [agent.agentId]);

  const choose = async (mode: AgentApprovalMode) => {
    if (saving || mode === current) {
      setOpen(false);
      return;
    }
    if (STRICTNESS[mode] < STRICTNESS[currentKey] && confirming !== mode) {
      setConfirming(mode);
      return;
    }
    setSaving(true);
    setError("");
    try {
      const response = await fetch(`/api/society/agents/${encodeURIComponent(agent.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approval_mode: mode }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null) as { detail?: unknown } | null;
        throw new Error(typeof body?.detail === "string" ? body.detail : t("society.approval_mode.unavailable"));
      }
      const body = await response.json().catch(() => null) as { agent?: SocietyAgentRow } | null;
      if (body?.agent) {
        const updated = rowToAgent(body.agent);
        client.setQueryData<{ agents: SocietyAgent[]; sample: boolean }>(["society", "roster"], (previous) => previous
          ? { ...previous, agents: previous.agents.map((row) => (row.agentId === updated.agentId ? updated : row)) }
          : previous);
      }
      await client.invalidateQueries({ queryKey: ["society", "roster"] });
      setConfirming(null);
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const onMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = [...(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]:not([disabled])'))];
    if (!items.length) return;
    const at = items.indexOf(document.activeElement as HTMLButtonElement);
    items[(at + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
  };

  return (
    <div ref={root} className="relative">
      <button
        type="button"
        data-approval-trigger
        data-testid="agent-header-approval"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        aria-label={`${t("society.approval_mode.title")}: ${label}`}
        title={current ? t(`society.approval_mode.${current}_hint`) : t("society.approval_mode.legacy_hint")}
        disabled={saving}
        onClick={() => {
          setConfirming(null);
          setError("");
          setOpen((value) => !value);
        }}
        className="as-header-control"
      >
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden />
        <span className="as-header-label truncate">{label}</span>
        <ChevronDown className="h-3 w-3 shrink-0 opacity-70" aria-hidden />
      </button>
      {open ? (
        <div id={menuId} role="menu" aria-label={t("society.approval_mode.title")} onKeyDown={onMenuKeyDown}
          className="as-menu absolute right-0 top-full z-50 mt-1.5 w-72">
          <p className="px-2.5 pb-1 pt-1.5 text-[11px] font-medium text-muted-foreground">{t("society.approval_mode.title")}</p>
          {AGENT_APPROVAL_MODES.map((mode) => {
            const supported = modeSupported(runner, mode);
            const ModeIcon = MODE_ICON[mode];
            const selected = mode === current;
            const confirm = confirming === mode;
            return (
              <button
                key={mode}
                type="button"
                role="menuitemradio"
                aria-checked={selected}
                disabled={!supported || saving}
                title={supported ? undefined : t("society.approval_mode.unavailable")}
                onClick={() => void choose(mode)}
                className="as-menu-item"
                data-testid={`approval-mode-${mode}`}
              >
                <ModeIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className={cn("block font-medium", confirm ? "text-warning" : "text-foreground")}>
                    {confirm ? t("society.shell.approval_confirm") : t(`society.approval_mode.${mode}`)}
                  </span>
                  <span className="block text-xs leading-4 text-muted-foreground">
                    {supported ? t(`society.approval_mode.${mode}_hint`) : t("society.approval_mode.unavailable")}
                  </span>
                </span>
                {selected ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-foreground" aria-hidden /> : null}
              </button>
            );
          })}
          {error ? <p role="alert" className="px-2.5 pb-1.5 pt-1 text-xs text-destructive">{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
