import { useMemo } from "react";
import { Zap } from "lucide-react";
import { brainValue, splitBrainValue } from "@/components/agentchat/AgentComposer";
import { ComposerBrainPicker, type BrainSection } from "@/components/agentchat/ComposerBrainPicker";
import { AgentMark } from "@/components/agentic/AgentMark";
import { ProviderLogo } from "@/components/providers/ProviderLogo";
import { Combobox, type ComboboxGroup, type ComboboxOption } from "@/components/ui/combobox";
import { useT } from "@/i18n";
import { isApiRunner, type CuratedModel, type ModelSpeed } from "@/lib/agentChatApi";
import { offeredModels, useSavedHiddenModels } from "@/lib/agentProviderPrefs";
import { effortLadder } from "@/lib/effortLadder";
import { rankModels } from "@/lib/modelRanking";
import type { ComposerDraft, ProviderOption } from "@/store/agentChat";

/**
 * The picks under a thread's composer: which coding agent and model answer,
 * how hard it thinks and how fast it runs (one menu), and how much it may do
 * without asking. Quiet text buttons until opened; each
 * opens the app's own searchable list.
 */

/** One quiet control in the composer's toolbar: 28 px, medium weight, a lift on hover. */
const TRIGGER = "h-7 w-auto max-w-[240px] gap-1.5 rounded-lg bg-transparent px-2.5 py-0 text-sm font-medium text-foreground-secondary hover:bg-secondary hover:text-foreground";

/** The hairline between two toolbar controls. */
function Separator() {
  return <span aria-hidden className="mx-0.5 hidden h-4 w-px shrink-0 bg-border sm:block" />;
}

/** The name a coding agent goes by, not its API brand ("Claude Code", not "Anthropic Claude"). */
export function agentName(provider: Pick<ProviderOption, "agent" | "label">): string {
  switch (provider.agent) {
    case "claude": return "Claude Code";
    case "codex": return "Codex";
    default: return provider.label;
  }
}

/**
 * A row's own mark: a coding agent's, or the provider's logo for a seat that
 * is an API behind a key. Never a letter in a box.
 */
function ProviderMark({ provider }: { provider: ProviderOption }) {
  return provider.agent
    ? <AgentMark agent={provider.agent} label={provider.label} logoUrl={provider.logoUrl} variant="plain" size="sm" />
    : <ProviderLogo providerId={provider.id} label={provider.label} size="sm" />;
}

const EFFORTS = new Set(["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "ultracode"]);

/** An effort level in the chat's own words ("" is the agent's default). */
function effortLabel(level: string, t: (key: string) => string): string {
  if (!level) return t("agent_chat.effort_default");
  return EFFORTS.has(level) ? t(`agent_chat.effort_${level}`) : level;
}

/** The models a provider row offers: its live list when it has one, else the curated one. */
export function modelsOf(provider: ProviderOption, liveModels: Record<string, CuratedModel[]>): CuratedModel[] {
  const live = liveModels[provider.id];
  return provider.models_source === "live" && live && live.length ? live : provider.curated_models ?? [];
}

export function AgentModelPicker({
  providers,
  liveModels,
  draft,
  lockedProvider,
  onPick,
}: {
  providers: ProviderOption[];
  liveModels: Record<string, CuratedModel[]>;
  draft: ComposerDraft;
  /** A thread that has started keeps its coding agent; only the model can change. */
  lockedProvider: string | null;
  onPick: (provider: string, model: string) => void;
}) {
  const t = useT();
  const olderLabel = t("agent_chat.older_models");
  const newThreadHint = t("ide_threads.hint_new_thread");
  const notInstalledHint = t("agent_chat.provider_not_installed");
  const connectFirstHint = t("ide_threads.hint_connect_first");
  const saved = useSavedHiddenModels((state) => state.hidden);
  const groups = useMemo<ComboboxGroup[]>(() => providers.map((provider) => {
    const locked = lockedProvider !== null && provider.id !== lockedProvider;
    const disabled = !provider.connected || locked;
    const hint = locked ? newThreadHint : !provider.connected ? (provider.cli_installed === false ? notInstalledHint : connectFirstHint) : undefined;
    const icon = <ProviderMark provider={provider} />;
    // Whose model a row is, on a quiet second line under its name.
    const owner = (note?: string) => <span className="inline-flex min-w-0 items-center gap-1.5">
      <span className="inline-flex shrink-0 scale-[0.86]">{icon}</span>
      <span className="truncate">{note ? `${agentName(provider)} · ${note}` : agentName(provider)}</span>
    </span>;
    // Models switched off on the API Keys page stay out; the current pick stays.
    const current = provider.id === draft.provider ? draft.model : "";
    const models = offeredModels(provider, modelsOf(provider, liveModels), current, saved).filter((model) => model.id);
    const toOption = (model: CuratedModel): ComboboxOption => ({
      value: brainValue(provider.id, model.id),
      label: model.label || model.id,
      description: owner(model.note),
      hint,
      searchText: `${model.id} ${agentName(provider)}`,
      disabled,
    });
    // Newest of each model line first; earlier versions fold away.
    const ranked = rankModels(models);
    return {
      id: provider.id,
      label: agentName(provider),
      options: ranked.current.length || ranked.older.length
        ? ranked.current.map(toOption)
        // A CLI that publishes no model list can only be picked as itself;
        // the row carries the agent's name, never a "Default model" label.
        : [{ value: brainValue(provider.id, ""), label: agentName(provider), description: owner(), hint, disabled, searchText: agentName(provider) }],
      more: ranked.older.length ? { label: olderLabel, options: ranked.older.map(toOption) } : undefined,
    };
  }), [providers, liveModels, lockedProvider, draft.provider, draft.model, saved, olderLabel, newThreadHint, notInstalledHint, connectFirstHint]);
  // The rail on the panel's left: one mark per coding agent, plus favourites.
  const sections = useMemo<BrainSection[]>(() => providers.map((provider) => ({
    id: provider.id,
    family: provider.family,
    access: provider.keyless ? "local" : isApiRunner(provider.runner) ? "api" : "subscription",
    label: agentName(provider),
    icon: <ProviderMark provider={provider} />,
    muted: !provider.connected || (lockedProvider !== null && provider.id !== lockedProvider),
  })), [providers, lockedProvider]);
  const pickedIcon = providers.find((provider) => provider.id === draft.provider);
  return <ComposerBrainPicker testId="thread-model-picker" ariaLabel={t("ide_threads.agent_model_aria")}
    value={brainValue(draft.provider, draft.model)} groups={groups} sections={sections} currentSection={draft.provider}
    onChange={(value) => { const [provider, model] = splitBrainValue(value); onPick(provider, model); }}
    fallbackLabel={draft.model || (providers.length ? t("ide_threads.choose_agent") : t("ide_threads.loading_agents"))} searchPlaceholder={t("ide_threads.search_agents_models")}
    triggerPrefix={pickedIcon ? <ProviderMark provider={pickedIcon} /> : undefined} />;
}

/** The speed tiers the picked model offers ([] = no fast mode for it). */
export function speedsOf(provider: ProviderOption, liveModels: Record<string, CuratedModel[]>, model: string): ModelSpeed[] {
  const row = modelsOf(provider, liveModels).find((entry) => entry.id === model);
  return row?.speeds ?? [];
}

/** Speed rows share the effort menu; this prefix keeps their values apart. */
const SPEED = "speed:";

/** One bolt per step above the standard speed: Fast is one, Ultrafast two. */
function Bolts({ count, testId }: { count: number; testId?: string }) {
  return <span aria-hidden data-testid={testId} data-bolts={count} className="inline-flex shrink-0 items-center -space-x-1 text-accent">
    {Array.from({ length: count }, (_, index) => <Zap key={index} className="h-3.5 w-3.5 fill-current" />)}
  </span>;
}

/**
 * How hard the agent thinks and, where the model has one, its fast mode:
 * one menu with two picks. Claude Code's fast mode reads On / Off; Codex
 * lists the tiers the account has (Fast, Ultrafast). The trigger carries a
 * bolt per step above the standard speed.
 */
export function EffortPicker({ provider, draft, liveModels, onPick, onPickSpeed, separated = false }: {
  separated?: boolean;
  provider: ProviderOption | null;
  draft: ComposerDraft;
  liveModels: Record<string, CuratedModel[]>;
  onPick: (effort: string) => void;
  /** Absent = no fast-mode section (a surface that does not store a speed). */
  onPickSpeed?: (speed: string) => void;
}) {
  const t = useT();
  const levels = useMemo(
    () => (provider ? effortLadder(provider, modelsOf(provider, liveModels), draft.model) : []),
    [provider, liveModels, draft.model],
  );
  const speeds = useMemo(
    () => (provider && onPickSpeed ? speedsOf(provider, liveModels, draft.model) : []),
    [provider, liveModels, draft.model, onPickSpeed],
  );
  const hasEffort = !(levels.length === 0 || (levels.length === 1 && levels[0] === ""));
  if (!hasEffort && speeds.length === 0) return null;
  // A stored tier this model does not offer runs at the standard speed.
  const speedIndex = speeds.findIndex((tier) => tier.id === draft.speed);
  const speed = speedIndex >= 0 ? speeds[speedIndex].id : "";
  const bolts = speedIndex >= 0 ? Math.min(speedIndex + 1, 2) : 0;
  const groups: ComboboxGroup[] = [];
  if (hasEffort) {
    groups.push({ id: "effort", options: levels.map((level) => ({ value: level, label: effortLabel(level, t) })) });
  }
  if (speeds.length) {
    // One tier reads as a switch (On / Off); several keep their names (Fast, Ultrafast).
    const single = speeds.length === 1;
    groups.push({
      id: "speed",
      label: t("agent_chat.speed_group"),
      options: [
        { value: SPEED, label: t("agent_chat.speed_off") },
        ...speeds.map((tier, index) => ({
          value: SPEED + tier.id,
          label: single ? t("agent_chat.speed_on") : tier.label,
          trailing: <Bolts count={Math.min(index + 1, 2)} />,
        })),
      ],
    });
  }
  return <>
    {separated && <Separator />}
    <Combobox ariaLabel={t("agent_chat.pick_effort")} testId="thread-effort-picker" value={hasEffort ? draft.effort : SPEED + speed}
      groups={groups}
      isChecked={(value) => (value.startsWith(SPEED) ? value === SPEED + speed : value === draft.effort)}
      onChange={(value) => (value.startsWith(SPEED) ? onPickSpeed?.(value.slice(SPEED.length)) : onPick(value))}
      fallbackLabel={hasEffort ? effortLabel(draft.effort, t) : t("agent_chat.speed_group")} triggerHint={false}
      triggerPrefix={bolts ? <Bolts count={bolts} testId="thread-speed-bolts" /> : undefined} className={TRIGGER} />
  </>;
}

export function AccessPicker({ provider, draft, onPick, separated = false }: {
  separated?: boolean;
  provider: ProviderOption | null;
  draft: ComposerDraft;
  onPick: (mode: string) => void;
}) {
  const t = useT();
  const modes = provider?.permission_modes ?? [];
  if (modes.length === 0) return null;
  return <>
    {separated && <Separator />}
    <Combobox ariaLabel={t("ide_threads.access_aria")} testId="thread-access-picker" value={draft.permissionMode}
      groups={[{
        id: "access",
        label: t("agent_chat.pick_permission"),
        // Words only: a name and one plain line under it. No glyph per row
        // and no colour on any stance, so the pick reads like the effort
        // pick beside it. The description is a second line, never a
        // right-hand hint: a sentence-long hint pushed the name out of a
        // narrow list.
        options: modes.map((mode) => ({
          value: mode.id,
          label: mode.label,
          searchText: mode.description,
          description: mode.description,
        })),
      }]}
      onChange={onPick} fallbackLabel={draft.permissionMode || t("agent_chat.model_access")} triggerHint={false} panelMinWidth={400}
      className={TRIGGER} />
  </>;
}
