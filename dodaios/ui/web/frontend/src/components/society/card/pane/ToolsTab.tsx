/**
 * Tools & access: everything that decides what this agent may touch, in one
 * draft with one Save. Reach and tools, approvals and rules, limits and its
 * browser are edited together; a change that lets the agent do MORE asks once
 * before it is saved. Placement (sandbox, computer) saves on its own, as it
 * always did, because it moves the agent rather than tuning it.
 *
 * Every field rides `PATCH /api/society/agents/{id}`, and only the fields that
 * changed are sent. Hermes and OpenClaw agents read the same roster row on
 * every turn (the per-turn tool filter), so a saved change applies from the
 * agent's next turn on every runtime.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";

import { Switch } from "@/components/ui/switch";
import { useLocaleChunk, useT } from "@/i18n";
import { AGENT_APPROVAL_MODES, PERMISSION_CEILINGS, fetchSocietyProviders, type AgentApprovalMode, type BrowserMode } from "@/lib/societyApi";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { resolveToolBrand } from "@/lib/toolBrand";
import { useEventStore } from "@/store/events";

import { capabilityKind, capabilityName } from "../../CapabilityChip";
import { ComputerPicker } from "../../create/ComputerPicker";
import {
  useSetAgentComputer,
  useSocietyCapabilities,
  useUpdateAgentConfig,
  type Capability,
  type GrantMode,
  type PermissionCeiling,
  type SocietyAgent,
} from "../../data";
import { AgentSandboxSection } from "../AgentSandboxSection";
import {
  draftFromAgent,
  isDirty,
  normalizeDomain,
  patchFromDraft,
  setGrantMode,
  setToolState,
  toolState,
  widenings,
  type AccessDraft,
  type ToolState,
  type Widening,
} from "./accessDraft";
import { ChipList, ChoicePill, PaneHint, PaneSection, Segmented, type SegmentOption } from "./ui";

/** Rows shown before "Show all": enough for the tools an agent really uses. */
const TOOL_PREVIEW = 8;

/** Runners that can show an actionable approval card, per mode (mirrors the PATCH validator). */
function modeUnavailable(mode: AgentApprovalMode, provider: string, runner: string | undefined): boolean {
  const unknownRunner = Boolean(provider) && runner == null;
  if (mode === "always_ask") return unknownRunner || (runner != null && runner !== "codex-cli" && runner !== "brain");
  if (mode === "ask") {
    return unknownRunner || (runner != null && !["codex-cli", "claude-cli", "glm-cli", "brain"].includes(runner));
  }
  return false;
}

export function ToolsTab({ agent, sample }: { agent: SocietyAgent; sample: boolean }) {
  const t = useT();
  useLocaleChunk("society");
  const lead = agent.tier === "lead";
  const update = useUpdateAgentConfig();
  const assistantName = useEventStore((s) => s.assistantName);
  const capabilities = useSocietyCapabilities(!sample);
  const providers = useQuery({ queryKey: ["society", "providers"], queryFn: fetchSocietyProviders, enabled: !lead && !sample, retry: false });
  const runner = providers.data?.find((row) => row.id === agent.provider)?.runner;

  const base = useMemo(() => draftFromAgent(agent), [agent]);
  const [draft, setDraft] = useState<AccessDraft>(base);
  const agentRef = useRef(agent);
  // A saved change, an approved proposal or a refetch moves the agent: adopt
  // it unless the person is in the middle of an edit of their own. "In the
  // middle of an edit" is judged by meaning, not by text, because the server
  // stores sets sorted and a byte-wise check would freeze a stale draft.
  useEffect(() => {
    const previous = agentRef.current;
    agentRef.current = agent;
    if (previous === agent) return;
    setDraft((current) => (isDirty(previous, current) ? current : draftFromAgent(agent)));
  }, [agent]);
  const confirmRef = useRef<HTMLButtonElement>(null);

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<Widening[] | null>(null);
  const dirty = isDirty(agent, draft);

  const catalog = capabilities.data ?? [];
  const byId = useMemo(() => new Map(catalog.map((c) => [c.id, c])), [catalog]);
  const labelOf = (id: string) => {
    const known = byId.get(id) ?? byId.get(id.split(":").slice(0, 2).join(":"));
    const brand = resolveToolBrand(known?.tool_name || capabilityName(id));
    return brand.brandId ? brand.label : known?.label ?? id;
  };

  const save = async (confirmed: boolean) => {
    const widen = widenings(agent, draft);
    if (!confirmed && widen.length > 0) {
      setConfirm(widen);
      return;
    }
    setConfirm(null);
    setSaving(true);
    setError("");
    try {
      const saved = await update(agent, patchFromDraft(agent, draft));
      // Take the stored values (sorted, normalised) as the new starting point.
      setDraft(draftFromAgent(saved));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  // The confirmation takes focus, so a keyboard user hears it and can answer.
  useEffect(() => {
    if (confirm) confirmRef.current?.focus();
  }, [confirm]);

  const disabled = sample || saving;
  const ceilingOptions: SegmentOption<PermissionCeiling>[] = PERMISSION_CEILINGS.map((step) => ({ value: step, label: t(`society.ceiling.${step}`) }));

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="agent-pane-tools">
      <div className="ap-body">
        {lead ? (
          <PaneSection title={t("society.agent_pane.reach")}>
            <PaneHint>{t("society.agent_pane.lead_tools_hint")}</PaneHint>
          </PaneSection>
        ) : (
          <>
            <PaneSection title={t("society.agent_pane.reach")}>
              <Segmented<GrantMode>
                fill
                label={t("society.agent_pane.reach")}
                value={draft.grantMode}
                disabled={disabled}
                testId="agent-pane-grant-mode"
                options={[
                  { value: "all", label: t("society.agent_pane.reach_all") },
                  { value: "allowlist", label: t("society.agent_pane.reach_allowlist") },
                ]}
                onChange={(mode) => setDraft((d) => setGrantMode(d, mode))}
              />
              <PaneHint>
                {t(draft.grantMode === "all" ? "society.agent_pane.reach_all_hint" : "society.agent_pane.reach_allowlist_hint")}
              </PaneHint>
            </PaneSection>
            <ToolList
              draft={draft}
              catalog={catalog}
              loading={capabilities.isLoading}
              failed={capabilities.isError}
              disabled={disabled}
              onChange={(id, state) => setDraft((d) => setToolState(d, id, state))}
            />
          </>
        )}

        <PaneSection title={t("society.agent_pane.approvals")} testId="agent-pane-approvals">
          {!lead ? (
            <>
              <Segmented<AgentApprovalMode>
                fill
                label={t("society.approval_mode.title")}
                value={draft.approvalMode}
                disabled={disabled}
                testId="agent-pane-approval-mode"
                options={AGENT_APPROVAL_MODES.map((mode) => {
                  const off = modeUnavailable(mode, agent.provider, runner);
                  return {
                    value: mode,
                    label: t(`society.approval_mode.${mode}`),
                    disabled: off,
                    title: off ? t("society.approval_mode.unavailable") : t(`society.approval_mode.${mode}_hint`),
                  };
                })}
                onChange={(mode) => setDraft((d) => ({ ...d, approvalMode: mode }))}
              />
              <PaneHint>
                {draft.approvalMode ? t(`society.approval_mode.${draft.approvalMode}_hint`) : t("society.approval_mode.legacy_hint")}
              </PaneHint>
            </>
          ) : null}
          {lead || !agent.approvalMode ? (
            <div className="flex flex-col gap-2">
              <span className="ap-sublabel">{t("society.approval_mode.legacy_ceiling")}</span>
              <Segmented<PermissionCeiling>
                fill
                label={t("society.approval_mode.legacy_ceiling")}
                value={draft.permissionCeiling}
                disabled={disabled}
                testId="agent-pane-ceiling"
                options={ceilingOptions}
                onChange={(step) => setDraft((d) => ({ ...d, permissionCeiling: step }))}
              />
            </div>
          ) : null}
        </PaneSection>

        {!lead ? (
          <PaneSection title={t("society.card.approval_rules")} testId="agent-pane-rules">
            <div className="ap-card ap-card-pad">
            <span className="ap-sublabel">{t("society.card.require_approval")}</span>
            <ChipList
              items={draft.requireApproval}
              onChange={(items) => setDraft((d) => ({ ...d, requireApproval: items }))}
              placeholder={t("society.agent_pane.rule_placeholder")}
              addLabel={t("society.agent_pane.add")}
              removeLabel={t("society.agent_pane.remove")}
              suggestions={catalog.map((c) => c.id)}
              disabled={disabled}
              emptyText={t("society.agent_pane.rules_none")}
              testId="agent-pane-require"
            />
            <span className="ap-sublabel mt-3">{t("society.card.always_allow")}</span>
            <ChipList
              items={draft.alwaysAllow}
              onChange={(items) => setDraft((d) => ({ ...d, alwaysAllow: items }))}
              placeholder={t("society.agent_pane.rule_placeholder")}
              addLabel={t("society.agent_pane.add")}
              removeLabel={t("society.agent_pane.remove")}
              suggestions={catalog.map((c) => c.id)}
              disabled={disabled}
              emptyText={t("society.agent_pane.rules_none")}
              testId="agent-pane-allow"
            />
            </div>
            <PaneHint>{t("society.agent_pane.rules_hint")}</PaneHint>
          </PaneSection>
        ) : null}

        <PaneSection title={t("society.card.limits")} testId="agent-pane-limits">
          <div className="ap-card">
            <div className="ap-line">
              <span className="ap-line-label">{t("society.card.budget_cap")}</span>
              <span className="ml-auto flex items-center gap-2">
                {draft.budgetOn ? (
                  <span className="flex items-center gap-1 text-[14px]">
                    <span className="text-muted-foreground">$</span>
                    <input
                    type="number"
                    min={0}
                    step={0.5}
                    inputMode="decimal"
                    disabled={disabled}
                    value={draft.budget}
                    onChange={(e) => setDraft((d) => ({ ...d, budget: e.target.value }))}
                    data-testid="agent-budget-input"
                    aria-label={t("society.card.budget_cap")}
                    className="ap-input"
                  />
                  </span>
                ) : (
                  <span className="ap-line-value">{t("society.card.no_cap")}</span>
                )}
                <Switch
                  checked={draft.budgetOn}
                  onCheckedChange={(on) => setDraft((d) => ({ ...d, budgetOn: on }))}
                  disabled={disabled}
                  aria-label={t("society.card.budget_cap")}
                  data-testid="agent-budget-switch"
                />
              </span>
            </div>
            <label className="ap-line">
              <span className="ap-line-label">{t("society.card.jobs_at_once")}</span>
              <input
                type="number"
                min={1}
                max={10}
                step={1}
                inputMode="numeric"
                disabled={disabled}
                value={draft.jobs}
                onChange={(e) => setDraft((d) => ({ ...d, jobs: e.target.value }))}
                data-testid="agent-jobs-input"
                className="ap-input ml-auto"
              />
            </label>
          </div>
          <PaneHint>{t(draft.budgetOn ? "society.card.budget_hint" : "society.card.budget_off_hint")}</PaneHint>
        </PaneSection>

        <PaneSection title={t("society.agent_pane.browser")} testId="agent-pane-browser-access">
          <Segmented<BrowserMode>
            fill
            label={t("society.agent_pane.browser")}
            value={draft.browserMode}
            disabled={disabled}
            testId="agent-pane-browser-mode"
            options={[
              { value: "own", label: t("society.agent_pane.browser_own") },
              { value: "attach", label: t("society.agent_pane.browser_attach") },
            ]}
            onChange={(mode) => setDraft((d) => ({ ...d, browserMode: mode }))}
          />
          <PaneHint>{t(draft.browserMode === "own" ? "society.agent_pane.browser_own_hint" : "society.agent_pane.browser_attach_hint")}</PaneHint>
          <div className="ap-card ap-card-pad">
          <span className="ap-sublabel">{t("society.agent_pane.sites")}</span>
          <ChipList
            items={draft.domains}
            onChange={(items) => setDraft((d) => ({ ...d, domains: items }))}
            placeholder={t("society.agent_pane.site_placeholder")}
            addLabel={t("society.agent_pane.add")}
            removeLabel={t("society.agent_pane.remove")}
            normalize={normalizeDomain}
            disabled={disabled}
            emptyText={t("society.agent_pane.sites_any")}
            testId="agent-pane-sites"
          />
          </div>
        </PaneSection>

        {!lead && !sample ? (
          <PaneSection title={t("society.card.where")} testId="agent-pane-placement">
            <div className="ap-card">
              <AgentSandboxSection agent={agent} show="choice" layout="row" />
              {agent.executionEnvironment !== "sandbox" ? <RunsOn agent={agent} /> : null}
            </div>
            <PaneHint>{t("society.agent_pane.placement_hint")}</PaneHint>
          </PaneSection>
        ) : null}
      </div>

      {confirm ? (
        <div className="ap-savebar" data-tone="warn" role="alertdialog" aria-label={t("society.agent_pane.widen_title")} data-testid="agent-pane-widen">
          <div className="ap-widen">
            <strong className="text-[13px] font-semibold">{t("society.agent_pane.widen_title").replace("{0}", societyDisplayName(agent, assistantName))}</strong>
            <ul>
              {confirm.map((w) => (
                <li key={w.key}>{wideningText(w, t, labelOf)}</li>
              ))}
            </ul>
          </div>
          <span className="flex-1" />
          <button ref={confirmRef} type="button" className="ap-btn" data-variant="ghost" onClick={() => setConfirm(null)}>
            {t("society.agent_pane.go_back")}
          </button>
          <button type="button" className="ap-btn" data-variant="primary" onClick={() => void save(true)} data-testid="agent-pane-widen-confirm">
            {t("society.agent_pane.allow_and_save")}
          </button>
        </div>
      ) : dirty || error ? (
        <div className="ap-savebar" data-testid="agent-pane-savebar">
          {error ? (
            <span role="alert" className="min-w-0 flex-1 truncate text-[13px] text-destructive" title={error}>{error}</span>
          ) : (
            <span className="min-w-0 flex-1 text-[13px] text-muted-foreground">{t("society.agent_pane.unsaved")}</span>
          )}
          <button type="button" className="ap-btn" data-variant="ghost" disabled={saving} onClick={() => { setDraft(base); setError(""); }}>
            {t("society.agent_pane.discard")}
          </button>
          <button type="button" className="ap-btn" data-variant="primary" disabled={saving || !dirty || sample} onClick={() => void save(false)} data-testid="agent-pane-save">
            {t(saving ? "society.card.saving" : "society.card.save")}
          </button>
        </div>
      ) : null}
    </div>
  );
}

function wideningText(w: Widening, t: (key: string) => string, labelOf: (id: string) => string): string {
  const names = w.items.map(labelOf).join(", ");
  switch (w.key) {
    case "reach_all":
      return t("society.agent_pane.widen_reach_all");
    case "tools_added":
      return t("society.agent_pane.widen_tools").replace("{0}", names);
    case "unblocked":
      return t("society.agent_pane.widen_unblocked").replace("{0}", names);
    case "approval_mode":
      return t("society.agent_pane.widen_mode").replace("{0}", t(`society.approval_mode.${w.items[0]}`));
    case "ceiling":
      return t("society.agent_pane.widen_ceiling").replace("{0}", t(`society.ceiling.${w.items[0]}`));
    case "always_allow":
      return t("society.agent_pane.widen_allow").replace("{0}", w.items.join(", "));
    case "require_removed":
      return t("society.agent_pane.widen_require").replace("{0}", w.items.join(", "));
    case "browser_attach":
      return t("society.agent_pane.widen_browser");
    case "domains_opened":
      return w.items[0] === "*"
        ? t("society.agent_pane.widen_sites_any")
        : t("society.agent_pane.widen_sites").replace("{0}", w.items.join(", "));
  }
}

const KIND_ORDER = ["plugin", "mcp", "cli", "skill", "core"];

function ToolList({
  draft,
  catalog,
  loading,
  failed,
  disabled,
  onChange,
}: {
  draft: AccessDraft;
  catalog: Capability[];
  loading: boolean;
  failed: boolean;
  disabled: boolean;
  onChange: (id: string, state: ToolState) => void;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [all, setAll] = useState(false);
  const allowlist = draft.grantMode === "allowlist";

  const rows = useMemo(() => {
    const known = new Map(catalog.map((c) => [c.id, c]));
    // Ids the agent carries that the catalog no longer lists stay editable.
    for (const id of [...draft.focus, ...draft.grants, ...draft.denies]) {
      if (!known.has(id)) {
        known.set(id, { id, kind: capabilityKind(id) ?? "core", label: capabilityName(id), one_liner: "", risk_tier: "", connected: false, tool_name: "" });
      }
    }
    const rank = (c: Capability) => {
      const state = toolState(draft, c.id);
      if (state === "first") return 0;
      if (state === "blocked") return 2;
      if (allowlist && state === "on") return 1;
      return c.connected ? 3 : 4;
    };
    return [...known.values()].sort((a, b) => {
      const byState = rank(a) - rank(b);
      if (byState) return byState;
      if (rank(a) === 0) return draft.focus.indexOf(a.id) - draft.focus.indexOf(b.id);
      const byKind = KIND_ORDER.indexOf(String(a.kind)) - KIND_ORDER.indexOf(String(b.kind));
      return byKind || a.label.localeCompare(b.label);
    });
    // The order is fixed when the list opens or the search changes, so a row
    // the person just switched does not jump away from under the pointer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog, allowlist, query]);

  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? rows.filter((c) => [c.id, c.label, c.one_liner, ...(c.aliases ?? [])].some((v) => v?.toLowerCase().includes(needle)))
    : rows;
  const shown = needle || all ? filtered : filtered.slice(0, TOOL_PREVIEW);

  const options: SegmentOption<ToolState>[] = [
    { value: "first", label: t("society.agent_pane.tool_first") },
    { value: "on", label: t("society.agent_pane.tool_on") },
    allowlist
      ? { value: "off", label: t("society.agent_pane.tool_off") }
      : { value: "blocked", label: t("society.agent_pane.tool_block") },
  ];
  const stateLabel: Record<ToolState, string> = {
    first: t("society.agent_pane.tool_first"),
    on: t("society.agent_pane.tool_on"),
    off: t("society.agent_pane.tool_off"),
    blocked: t("society.agent_pane.tool_blocked"),
  };

  return (
    <PaneSection title={t("society.agent_pane.tools")} testId="agent-pane-tool-list">
      <label className="ap-search">
        <Search className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
        <input
          type="search"
          value={query}
          placeholder={t("society.agent_pane.search_tools")}
          aria-label={t("society.agent_pane.search_tools")}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {loading ? <PaneHint>{t("society.profile_card.loading")}</PaneHint> : null}
      {failed ? <PaneHint>{t("society.agent_pane.tools_unavailable")}</PaneHint> : null}
      {!loading && filtered.length === 0 ? <PaneHint>{t("society.profile_card.no_results")}</PaneHint> : null}
      {shown.length ? <ul className="ap-card ap-tools">
        {shown.map((c) => {
          const state = toolState(draft, c.id);
          const brand = resolveToolBrand(c.tool_name || capabilityName(c.id));
          const label = brand.brandId ? brand.label : c.label;
          const shownState = allowlist && state === "blocked" ? "off" : state;
          return (
            <li key={c.id} className="ap-tool" data-state={state} data-testid={`agent-pane-tool-${c.id}`}>
              <span className="min-w-0 flex-1" title={c.one_liner || c.id}>
                <span className="ap-tool-name">{label}</span>
                <span className="ap-tool-sub" data-off={c.connected ? undefined : "true"}>
                  {c.connected ? (c.one_liner || c.id) : t("society.card.not_connected")}
                </span>
              </span>
              <ChoicePill<ToolState>
                label={label}
                value={shownState}
                shownLabel={stateLabel[shownState]}
                disabled={disabled}
                options={options}
                onChange={(next) => onChange(c.id, next)}
              />
            </li>
          );
        })}
      </ul> : null}
      {!needle && filtered.length > TOOL_PREVIEW ? (
        <button type="button" className="ap-link self-start" onClick={() => setAll((v) => !v)}>
          {all ? t("society.agent_pane.show_less") : t("society.agent_pane.show_all").replace("{0}", String(filtered.length))}
        </button>
      ) : null}
    </PaneSection>
  );
}

/**
 * Where the agent's work executes — this computer or a connected one. The
 * change applies from the agent's next turn; a turn already running finishes
 * where it started.
 */
function RunsOn({ agent }: { agent: SocietyAgent }) {
  const t = useT();
  const setComputer = useSetAgentComputer();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="flex flex-col" data-testid="agent-runs-on">
      <ComputerPicker
        value={agent.computerId ?? ""}
        layout="row"
        testId="agent-runs-on-picker"
        onChange={(id) => {
          if (saving || id === (agent.computerId ?? "")) return;
          setSaving(true);
          setError("");
          setComputer(agent, id)
            .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
            .finally(() => setSaving(false));
        }}
      />
      {error ? <p role="alert" className="ap-hint ap-line-hint text-destructive">{error}</p> : null}
      {saving ? <p className="ap-hint ap-line-hint">{t("society.card.runs_on_saving")}</p> : null}
    </div>
  );
}
