/**
 * The chat's header: one small pill in the middle with the agent's face and
 * name. Pressing it opens and closes the details pane. While the agent works
 * or waits on the person, the pill says so in a few words; an idle agent
 * shows nothing more than its name.
 *
 * What the agent thinks with lives in the composer's "+" menu and in the
 * Details tab; how freely it may act lives in the Details tab
 * (`ApprovalModePicker`). The approval picker only offers what the agent's
 * runner can honour and asks once more before loosening a mode.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";

import { useT } from "@/i18n";
import { fetchSocietyProviders, type AgentApprovalMode, type SocietyAgentRow } from "@/lib/societyApi";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

import { AgentSwatch } from "../AgentSwatch";
import { agentTint } from "../agentTint";
import { rowToAgent, type SocietyAgent } from "../data";
import { useAttentionStore } from "../attention/attentionStore";
import { previewText, readableWaiting, rosterStatus, waitingReasonOf } from "../roster/rosterPreview";
import { StatusMark } from "../roster/RosterRow";
import type { DetailsControl } from "./AgentChatLayout";
import { AGENT_APPROVAL_MODES, modeSupported, runnerFor } from "./approvalModes";

/** How strict a mode is; choosing a lower number loosens what the agent may do unasked. */
const STRICTNESS: Record<AgentApprovalMode | "legacy", number> = { bypass: 0, legacy: 1, ask: 1, always_ask: 2 };

export interface AgentHeaderProps {
  agent: SocietyAgent;
  /** The details pane's state and toggle; the layout owns them so they survive agent switches. */
  details?: DetailsControl;
}

export function AgentHeader({ agent, details }: AgentHeaderProps) {
  const t = useT();
  const assistantName = useEventStore((state) => state.assistantName);
  const displayName = societyDisplayName(agent, assistantName);
  // Re-read when a card is answered here, so "needs you" clears at once.
  useAttentionStore((state) => state.answered);
  const status = rosterStatus(agent, false);
  const reason = waitingReasonOf(agent);

  let phrase: ReactNode = null;
  if (status === "needs-you") {
    const summary = readableWaiting(previewText(reason?.summary), t);
    phrase = <span className="as-pill-status text-warning">{summary ? `${t("society.shell.preview_needs_you")} · ${summary}` : t("society.shell.status_waiting")}</span>;
  } else if (status === "working") {
    phrase = <span className="as-pill-status as-shimmer">{t("society.shell.preview_working")}</span>;
  } else if (status === "paused") {
    phrase = <span className="as-pill-status">{t("society.state.paused")}</span>;
  }
  const label = details
    ? `${displayName}. ${t(details.open ? "society.card.options_collapse" : "society.card.options_expand")}`
    : displayName;

  const content = (
    <>
      <span className="as-avatar">
        <AgentSwatch agent={agent} size={24} />
        {status === "needs-you" || status === "working" ? <StatusMark status={status} /> : null}
      </span>
      <span className="as-pill-name" data-testid="agent-header-name">{displayName}</span>
      <span className="contents" aria-live="polite" data-testid="agent-header-status">{phrase}</span>
    </>
  );

  return (
    <header className="as-header" data-testid="agent-header" style={agentTint(agent)}>
      <h2 className="sr-only">{displayName}</h2>
      {details ? (
        <button
          ref={details.ref}
          type="button"
          className="as-name-pill"
          onClick={details.toggle}
          aria-expanded={details.open}
          aria-controls={details.controlsId}
          aria-label={label}
          title={t(details.open ? "society.card.options_collapse" : "society.card.options_expand")}
          data-testid="shell-details-toggle"
        >
          {content}
        </button>
      ) : (
        <div className="as-name-pill">{content}</div>
      )}
    </header>
  );
}

/**
 * How freely the agent may act, as one quiet row: the mode's name on the
 * right, a menu of the modes its runner can honour below.
 */
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
        data-testid="agent-approval-mode"
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
        className="ap-line"
      >
        <span className="ap-line-label">{t("society.agent_pane.approvals")}</span>
        <span className="ap-line-value">{label}</span>
      </button>
      {open ? (
        <div id={menuId} role="menu" aria-label={t("society.approval_mode.title")} onKeyDown={onMenuKeyDown}
          className="as-menu absolute inset-x-0 top-full z-50 mt-1.5">
          {AGENT_APPROVAL_MODES.map((mode) => {
            const supported = modeSupported(runner, mode);
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
                <span className="min-w-0 flex-1">
                  <span className={cn("block font-medium", confirm ? "text-warning" : "text-foreground")}>
                    {confirm ? t("society.shell.approval_confirm") : t(`society.approval_mode.${mode}`)}
                  </span>
                  <span className="block text-[13px] leading-[18px] text-muted-foreground">
                    {supported ? t(`society.approval_mode.${mode}_hint`) : t("society.approval_mode.unavailable")}
                  </span>
                </span>
                {selected ? <Check className="mt-0.5 h-4 w-4 shrink-0 text-foreground" aria-hidden /> : null}
              </button>
            );
          })}
          {error ? <p role="alert" className="px-2.5 pb-1.5 pt-1 text-[13px] text-destructive">{error}</p> : null}
        </div>
      ) : null}
    </div>
  );
}
