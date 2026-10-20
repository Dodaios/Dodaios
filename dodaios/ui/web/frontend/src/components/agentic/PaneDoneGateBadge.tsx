import type { CSSProperties } from "react";
import { fill, useT } from "@/i18n";
import { themeFor, type TerminalAppearance } from "./terminalThemes";
import { usePaneDoneGate, type DoneGateVerdict, type PaneDoneGate } from "./usePaneDoneGate";

const KEYS: Record<DoneGateVerdict, string> = {
  DONE: "done", WAIT: "wait", FIX: "fix", STUCK: "stuck",
};

function checkedAt(at: string): string {
  const stamp = new Date(at);
  return Number.isNaN(stamp.getTime()) ? "" : stamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/**
 * The done gate's last word on this pane's session, as a quiet label beside
 * the pane's GitHub status: WAIT amber, FIX red, STUCK outlined in red, DONE
 * green. NONE and HOLD show nothing. The tooltip carries the reason and the
 * next step the gate gave the agent.
 */
export function DoneGateLabel({ gate, appearance, name }: {
  gate: PaneDoneGate | null;
  appearance: TerminalAppearance;
  name: string;
}) {
  const t = useT();
  if (!gate) return null;
  const theme = themeFor(appearance);
  const key = KEYS[gate.verdict];
  const label = t(`ide_panes.done_gate.label_${key}`);
  const color = gate.verdict === "DONE" ? theme.green : gate.verdict === "WAIT" ? theme.yellow : theme.red;
  const time = checkedAt(gate.at);
  const lines = [
    t(`ide_panes.done_gate.title_${key}`),
    gate.reason,
    gate.next ? fill(t("ide_panes.done_gate.next"), { next: gate.next }) : "",
    gate.pr ? fill(t("ide_panes.done_gate.pull_request"), { number: gate.pr }) : "",
    time ? fill(t("ide_panes.done_gate.checked"), { time }) : "",
    gate.matched === "folder" ? t("ide_panes.done_gate.matched_folder") : "",
  ].filter(Boolean);
  const style: CSSProperties = {
    color,
    borderColor: gate.verdict === "STUCK" ? color : "transparent",
  };
  return <span data-header-control="true" data-testid={`pane-done-gate-${name}`} data-verdict={gate.verdict}
    role="img" aria-label={fill(t("ide_panes.done_gate.aria"), { pane: name, state: label })}
    title={lines.join("\n")}
    className="inline-flex h-4 shrink-0 cursor-default items-center rounded border px-1 text-[10px] font-medium leading-none tracking-wide"
    style={style}>
    {label}
  </span>;
}

export function PaneDoneGateBadge({ workspaceId, name, appearance }: {
  workspaceId?: string;
  name: string;
  appearance: TerminalAppearance;
}) {
  const gate = usePaneDoneGate(workspaceId, name);
  return <DoneGateLabel gate={gate} appearance={appearance} name={name} />;
}
