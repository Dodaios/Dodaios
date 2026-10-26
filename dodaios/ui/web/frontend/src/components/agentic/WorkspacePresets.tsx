import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Plus, Trash2 } from "lucide-react";
import {
  fetchLaunchPresets,
  saveLaunchPresets,
  type AgentStatus,
  type LaunchPreset,
  type LaunchPresetAgent,
} from "@/lib/agenticIdeApi";
import { cn } from "@/lib/utils";
import { fill, useT } from "@/i18n";
import { AgentMark } from "./AgentMark";

interface Props {
  agents: AgentStatus[];
  sessions: string[];
  onChange: (sessions: string[]) => void;
  disabled?: boolean;
}

/** A lineup grouped by agent, in first-seen order: [claude, codex, claude] → claude×2, codex×1. */
export function lineupOf(sessions: string[]): LaunchPresetAgent[] {
  const lineup: LaunchPresetAgent[] = [];
  for (const agent of sessions) {
    if (!agent) continue;
    const entry = lineup.find((item) => item.agent === agent);
    if (entry) entry.count += 1;
    else lineup.push({ agent, count: 1 });
  }
  return lineup;
}

/** The sessions a preset starts, grouped by agent. */
export function expandPreset(preset: LaunchPreset): string[] {
  return preset.agents.flatMap((item) => Array<string>(item.count).fill(item.agent));
}

function sameLineup(preset: LaunchPreset, sessions: string[]): boolean {
  const current = lineupOf(sessions);
  return current.length === preset.agents.length
    && preset.agents.every((item) => current.some((entry) => entry.agent === item.agent && entry.count === item.count));
}

function newId(): string {
  return Math.random().toString(36).slice(2, 12);
}

/**
 * Saved lineups for a new workspace: one click fills "2× Claude Code, 1× Codex,
 * 1× Kimi Code". The current lineup can be saved under a name; saving under an
 * existing name updates that preset.
 */
export function WorkspacePresets({ agents, sessions, onChange, disabled = false }: Props) {
  const t = useT();
  const [presets, setPresets] = useState<LaunchPreset[] | null>(null);
  const [stored, setStored] = useState(true);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    Promise.resolve()
      .then(() => fetchLaunchPresets())
      .then((response) => { if (alive) { setPresets(response.presets); setStored(response.stored); } })
      .catch(() => { if (alive) { setPresets([]); setStored(true); } });
    return () => { alive = false; };
  }, []);

  useEffect(() => { if (naming) inputRef.current?.focus(); }, [naming]);

  // Before anything was ever saved, offer a few starters built from the agents
  // this machine can launch. They are written only once the user changes the list.
  const starters = useMemo<LaunchPreset[]>(() => {
    const names = agents.map((agent) => agent.name);
    if (names.length === 0) return [];
    const list: LaunchPreset[] = [{ id: "starter-duo", name: t("workspace_launcher.presets.starter_duo"), agents: [{ agent: names[0], count: 2 }] }];
    if (names.length >= 2) {
      list.push({
        id: "starter-squad",
        name: t("workspace_launcher.presets.starter_squad"),
        agents: [{ agent: names[0], count: 2 }, ...names.slice(1, 3).map((agent) => ({ agent, count: 1 }))],
      });
    }
    if (names.length >= 3) {
      list.push({ id: "starter-all", name: t("workspace_launcher.presets.starter_all"), agents: names.slice(0, 8).map((agent) => ({ agent, count: 1 })) });
    }
    return list;
  }, [agents, t]);

  const shown = presets === null ? [] : stored ? presets : starters;
  const available = new Set(agents.map((agent) => agent.name));
  const labelOf = (agent: string) => agents.find((entry) => entry.name === agent)?.display_name ?? agent;
  const current = lineupOf(sessions);
  const matching = shown.find((preset) => sameLineup(preset, sessions));

  const persist = (next: LaunchPreset[]) => {
    const previous = { presets, stored };
    setPresets(next); setStored(true); setError(null);
    saveLaunchPresets(next)
      .then((response) => setPresets(response.presets))
      .catch((reason: Error) => { setPresets(previous.presets); setStored(previous.stored); setError(reason.message); });
  };

  const save = () => {
    const trimmed = name.trim().slice(0, 40);
    if (!trimmed || current.length === 0) return;
    const existing = shown.find((preset) => preset.name.toLocaleLowerCase() === trimmed.toLocaleLowerCase());
    const preset: LaunchPreset = { id: existing?.id ?? newId(), name: trimmed, agents: current };
    persist(existing ? shown.map((item) => item.id === existing.id ? preset : item) : [...shown, preset]);
    setNaming(false); setName("");
  };

  const remove = (id: string) => {
    persist(shown.filter((preset) => preset.id !== id));
    setConfirmDelete(null);
  };

  const card = "relative flex min-h-[4.5rem] min-w-0 flex-col justify-between gap-2 rounded-xl border px-4 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
  const selection = "border-ring/70 bg-muted ring-1 ring-ring/20";
  const idle = "border-border bg-background/40 hover:border-foreground/30 hover:bg-muted/60";

  return <section aria-label={t("workspace_launcher.presets.aria")}>
    <div className="mb-3 flex items-center justify-between gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{t("workspace_launcher.presets.title")}</h3>
      <span className="text-xs text-muted-foreground">{t("workspace_launcher.presets.hint")}</span>
    </div>
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
      {shown.map((preset) => {
        const missing = preset.agents.filter((item) => !available.has(item.agent));
        const total = preset.agents.reduce((sum, item) => sum + item.count, 0);
        const selected = matching?.id === preset.id;
        const summary = preset.agents.map((item) => `${item.count}× ${labelOf(item.agent)}`).join(", ");
        const blocked = disabled || missing.length > 0;
        return <div key={preset.id} className="group relative min-w-0">
          <button type="button" aria-pressed={selected} disabled={blocked}
            aria-label={fill(t("workspace_launcher.presets.apply"), { preset: preset.name, lineup: summary })}
            title={missing.length > 0 ? fill(t("workspace_launcher.presets.missing"), { agents: missing.map((item) => labelOf(item.agent)).join(", ") }) : summary}
            onClick={() => { onChange(expandPreset(preset)); setConfirmDelete(null); }}
            className={cn(card, "w-full disabled:cursor-not-allowed disabled:opacity-45", selected ? selection : idle)}>
            <span className="flex w-full items-center gap-2 pr-6">
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{preset.name}</span>
              {selected
                ? <Check aria-hidden="true" className="h-4 w-4 shrink-0" />
                : <span aria-hidden="true" className="text-xs tabular-nums text-muted-foreground">{total}</span>}
            </span>
            <span aria-hidden="true" className="flex flex-wrap items-center gap-x-3 gap-y-1">
              {preset.agents.map((item) => <span key={item.agent} className="flex items-center gap-1">
                <AgentMark agent={item.agent} label={labelOf(item.agent)} logoUrl={agents.find((entry) => entry.name === item.agent)?.logo_url} variant="plain" className="h-4 w-4 opacity-100" />
                <span className="text-xs tabular-nums text-muted-foreground">×{item.count}</span>
              </span>)}
            </span>
          </button>
          {confirmDelete === preset.id
            ? <button type="button" autoFocus disabled={disabled} onClick={() => remove(preset.id)}
              className="absolute right-2 top-2 rounded-md bg-destructive px-2 py-0.5 text-[11px] font-medium text-destructive-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onBlur={() => setConfirmDelete(null)}>
              {t("workspace_launcher.presets.confirm_delete")}
            </button>
            : <button type="button" disabled={disabled} aria-label={fill(t("workspace_launcher.presets.delete"), { preset: preset.name })}
              onClick={() => setConfirmDelete(preset.id)}
              className="absolute right-2 top-2 rounded-md p-1 text-muted-foreground opacity-0 transition-opacity hover:bg-background hover:text-foreground focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring group-hover:opacity-100">
              <Trash2 aria-hidden="true" className="h-3.5 w-3.5" />
            </button>}
        </div>;
      })}

      {naming
        ? <form className={cn(card, "border-ring/70 bg-muted/40")} onSubmit={(event) => { event.preventDefault(); save(); }}>
          <input ref={inputRef} value={name} maxLength={40} disabled={disabled} onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); setNaming(false); setName(""); } }}
            placeholder={t("workspace_launcher.presets.name_placeholder")} aria-label={t("workspace_launcher.presets.name_aria")}
            className="w-full bg-transparent text-sm font-medium text-foreground outline-none placeholder:text-muted-foreground" />
          <span className="flex items-center justify-between gap-2">
            <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1" aria-hidden="true">
              {current.map((item) => <span key={item.agent} className="flex items-center gap-1">
                <AgentMark agent={item.agent} label={labelOf(item.agent)} logoUrl={agents.find((entry) => entry.name === item.agent)?.logo_url} variant="plain" className="h-4 w-4 opacity-100" />
                <span className="text-xs tabular-nums text-muted-foreground">×{item.count}</span>
              </span>)}
            </span>
            <span className="flex shrink-0 gap-1">
              <button type="button" onClick={() => { setNaming(false); setName(""); }}
                className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-background">{t("common.cancel")}</button>
              <button type="submit" disabled={disabled || !name.trim()}
                className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground disabled:opacity-40">{t("common.save")}</button>
            </span>
          </span>
        </form>
        : !matching && <button type="button" disabled={disabled || current.length === 0 || presets === null}
          onClick={() => { setNaming(true); setName(""); }}
          className={cn(card, "items-start border-dashed border-border text-muted-foreground hover:border-foreground/30 hover:bg-muted/40 hover:text-foreground disabled:cursor-default disabled:opacity-50 disabled:hover:border-border disabled:hover:bg-transparent disabled:hover:text-muted-foreground")}>
          <span className="flex items-center gap-2 text-sm font-medium"><Plus aria-hidden="true" className="h-4 w-4" />
            {t("workspace_launcher.presets.save_current")}</span>
          <span className="text-xs">{t("workspace_launcher.presets.save_hint")}</span>
        </button>}
    </div>
    {error && <p role="alert" className="mt-2 text-xs text-destructive">{error}</p>}
  </section>;
}
