import { useCallback, useEffect, useMemo, useState, type KeyboardEvent } from "react";
import { ArrowRight, Check, Copy, Loader2, RotateCcw, Sparkles } from "lucide-react";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { robustCopy } from "@/lib/clipboard";
import { promptTerminal, type WorkspacePaneRow } from "@/lib/agenticIdeApi";
import type { CuratedModel } from "@/lib/agentChatApi";
import { offeredModels, useSavedHiddenModels } from "@/lib/agentProviderPrefs";
import { rankModels } from "@/lib/modelRanking";
import { MAX_INSTRUCTION_CHARS, MAX_PROMPT_CHARS, fetchPromptImproverDefaults, improvePrompt } from "@/lib/promptImproverApi";
import { joinProviderOptions, type ProviderOption } from "@/store/agentChat";
import { useIdeSkillsStore } from "@/store/ideSkills";
import { useWorkspacePanes } from "@/store/workspacePanes";
import { AgentMark } from "@/components/agentic/AgentMark";
import { useThreadChatStore } from "@/components/agentic/threads/threadModel";
import { Combobox, type ComboboxGroup, type ComboboxOption } from "@/components/ui/combobox";

const DRAFT_KEY = "jarvis.agenticIde.promptTab.draft.v1";
const MODEL_KEY = "jarvis.agenticIde.promptTab.model.v1";
const INSTRUCTION_KEY = "jarvis.agenticIde.promptTab.instruction.v1";

/** Joins a provider and one of its models into one picker value; neither id holds a newline. */
const SEP = "\n";
/** The picker value for "whoever writes the IDE's task briefs". */
const AUTO = "";

function stored(key: string): string {
  try {
    return localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function persist(key: string, value: string): void {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* a convenience only: the tab keeps the value for this session */
  }
}

const paneId = (pane: Pick<WorkspacePaneRow, "workspace_id" | "key">) => `${pane.workspace_id}${SEP}${pane.key}`;

/** The models a provider row offers: its live list when it has one, else the curated one. */
function modelsOf(provider: ProviderOption, live: Record<string, CuratedModel[]>): CuratedModel[] {
  const rows = live[provider.id];
  return provider.models_source === "live" && rows?.length ? rows : provider.curated_models ?? [];
}

const FIELD =
  "block w-full resize-y rounded-md bg-input px-3 py-2 text-sm leading-6 text-foreground placeholder:text-muted-foreground " +
  "scrollbar-jarvis focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-border-strong";
const QUIET_BTN =
  "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2.5 text-sm text-muted-foreground transition-colors " +
  "hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:cursor-default disabled:opacity-40 disabled:hover:bg-transparent";
const MAIN_BTN =
  "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md bg-accent px-3 text-sm font-medium text-accent-foreground " +
  "transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring " +
  "disabled:cursor-default disabled:opacity-40";
const LABEL = "text-xs font-medium text-muted-foreground";

/**
 * The side panel's Prompt surface: type a rough prompt, have a model of your
 * choice rewrite it, then send the result to the terminal you pick.
 *
 * The rewrite states the goal and leaves the route to the agent, and the
 * writer is told about the repository the chosen terminal works in. Nothing
 * reaches a terminal until Send is pressed; the improved text stays editable.
 */
export function PromptTab() {
  const t = useT();
  const [draft, setDraft] = useState(() => stored(DRAFT_KEY));
  const [pick, setPick] = useState(() => stored(MODEL_KEY));
  const [instruction, setInstruction] = useState(() => stored(INSTRUCTION_KEY));
  const [defaultInstruction, setDefaultInstruction] = useState("");
  const [improved, setImproved] = useState<string | null>(null);
  const [writer, setWriter] = useState("");
  const [chosenPane, setChosenPane] = useState<string | null>(null);
  const [busy, setBusy] = useState<"improve" | "send" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState<{ tone: "ok" | "warn"; text: string } | null>(null);
  const [copied, setCopied] = useState(false);

  const catalog = useThreadChatStore((state) => state.catalog);
  const connections = useThreadChatStore((state) => state.connections);
  const liveModels = useThreadChatStore((state) => state.liveModels);
  const savedHidden = useSavedHiddenModels((state) => state.hidden);
  const selected = useIdeSkillsStore((state) => state.target);
  const panes = useWorkspacePanes();

  useEffect(() => {
    const store = useThreadChatStore.getState();
    if (!store.catalog || store.catalogStale) void store.loadCatalog();
    fetchPromptImproverDefaults()
      .then((defaults) => setDefaultInstruction(defaults.default_instruction))
      .catch(() => undefined); // the placeholder stays empty; the backend still applies its default
  }, []);

  const providers = useMemo(
    () => (catalog ? joinProviderOptions(catalog.providers, connections) : [])
      .slice()
      .sort((a, b) => Number(b.connected) - Number(a.connected)),
    [catalog, connections],
  );

  // A provider with a live model list is asked for it once it is known to be connected.
  useEffect(() => {
    for (const provider of providers) {
      if (provider.connected && provider.models_source === "live") void useThreadChatStore.getState().loadModels(provider.id);
    }
  }, [providers]);

  const [pickedProvider, pickedModel = ""] = pick.split(SEP);

  const modelGroups = useMemo<ComboboxGroup[]>(() => {
    const connectHint = t("ide_side_panel.prompt.connect_first");
    const groups: ComboboxGroup[] = [{
      id: "auto",
      options: [{ value: AUTO, label: t("ide_side_panel.prompt.model_auto"), description: t("ide_side_panel.prompt.model_auto_hint") }],
    }];
    for (const provider of providers) {
      const disabled = !provider.connected;
      const icon = <AgentMark agent={provider.agent ?? ""} label={provider.label} logoUrl={provider.logoUrl} variant="plain" size="sm" />;
      const current = provider.id === pickedProvider ? pickedModel : "";
      const models = offeredModels(provider, modelsOf(provider, liveModels), current, savedHidden).filter((model) => model.id);
      const toOption = (model: CuratedModel): ComboboxOption => ({
        value: `${provider.id}${SEP}${model.id}`,
        label: model.label || model.id,
        triggerLabel: `${provider.label} · ${model.label || model.id}`,
        icon,
        hint: disabled ? connectHint : undefined,
        searchText: `${model.id} ${provider.label}`,
        disabled,
      });
      const ranked = rankModels(models);
      groups.push({
        id: provider.id,
        label: provider.label,
        options: [
          { value: provider.id, label: t("ide_side_panel.prompt.model_default"), triggerLabel: provider.label, icon, hint: disabled ? connectHint : undefined, searchText: provider.label, disabled },
          ...ranked.current.map(toOption),
        ],
        more: ranked.older.length ? { label: t("agent_chat.older_models"), options: ranked.older.map(toOption) } : undefined,
      });
    }
    return groups;
  }, [providers, liveModels, savedHidden, pickedProvider, pickedModel, t]);

  // Only a running agent takes a prompt; a plain shell would run the text as a command.
  const targets = useMemo(() => panes.filter((pane) => pane.accepts_prompts && pane.status !== "exited" && pane.status !== "error"), [panes]);
  const target = useMemo(() => {
    const byChoice = chosenPane ? targets.find((pane) => paneId(pane) === chosenPane) : undefined;
    if (byChoice) return byChoice;
    const inGrid = selected
      ? targets.find((pane) => pane.workspace_id === selected.workspaceId && (pane.key === selected.pane || pane.name === selected.pane))
      : undefined;
    return inGrid ?? targets.find((pane) => pane.workspace_active) ?? targets[0] ?? null;
  }, [targets, chosenPane, selected]);

  const paneGroups = useMemo<ComboboxGroup[]>(() => {
    const byWorkspace = new Map<string, { label: string; active: boolean; panes: WorkspacePaneRow[] }>();
    for (const pane of targets) {
      const group = byWorkspace.get(pane.workspace_id) ?? { label: pane.workspace_name, active: pane.workspace_active, panes: [] };
      group.panes.push(pane);
      byWorkspace.set(pane.workspace_id, group);
    }
    const single = byWorkspace.size === 1;
    // The workspace on screen leads; every workspace numbers its terminals from T1,
    // so the closed picker names the workspace too once there is more than one.
    return [...byWorkspace]
      .sort(([, a], [, b]) => Number(b.active) - Number(a.active))
      .map(([id, group]) => ({
        id,
        label: single ? undefined : group.label,
        options: group.panes.map((pane): ComboboxOption => ({
          value: paneId(pane),
          label: pane.name,
          triggerLabel: single ? pane.name : `${group.label} · ${pane.name}`,
          hint: pane.display_name,
          description: pane.recap || undefined,
          icon: <AgentMark agent={pane.agent} label={pane.display_name} variant="plain" size="sm" />,
          searchText: `${pane.display_name} ${group.label} ${pane.recap}`,
        })),
      }));
  }, [targets]);

  const improve = useCallback(async () => {
    const prompt = draft.trim();
    if (!prompt || busy) return;
    setBusy("improve");
    setError("");
    setNotice(null);
    try {
      const result = await improvePrompt({
        prompt,
        provider: pickedProvider,
        model: pickedModel,
        instruction: instruction.trim(),
        workspaceId: target?.workspace_id,
        pane: target?.key,
      });
      setImproved(result.improved);
      setWriter(result.writer);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }, [draft, busy, pickedProvider, pickedModel, instruction, target]);

  const text = (improved ?? "").trim();
  const tooLong = text.length > MAX_PROMPT_CHARS;

  const send = useCallback(async () => {
    if (!text || tooLong || !target || busy) return;
    setBusy("send");
    setError("");
    setNotice(null);
    try {
      const result = await promptTerminal(target.key, text, { compose: false, workspaceId: target.workspace_id });
      // Three answers: it started, the text is provably still in the input box, or nobody can say.
      const key = result.submitted === true ? "sent" : result.submitted === false ? "not_accepted" : "unconfirmed";
      setNotice({ tone: result.submitted === true ? "ok" : "warn", text: fill(t(`ide_side_panel.prompt.${key}`), { pane: target.name }) });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(null);
    }
  }, [text, tooLong, target, busy, t]);

  const copy = useCallback(() => {
    void robustCopy(text).then((ok) => {
      if (!ok) return setError(t("ide_side_panel.prompt.copy_failed"));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    });
  }, [text, t]);

  const onModifierEnter = (run: () => void) => (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      run();
    }
  };

  return (
    <div data-testid="ide-prompt-tab" className="h-full min-h-0 overflow-y-auto scrollbar-jarvis">
      <div className="flex flex-col gap-3 p-3">
        <textarea
          value={draft}
          onChange={(event) => { setDraft(event.target.value); persist(DRAFT_KEY, event.target.value); }}
          onKeyDown={onModifierEnter(() => void improve())}
          rows={6}
          maxLength={MAX_PROMPT_CHARS}
          spellCheck={false}
          placeholder={t("ide_side_panel.prompt.placeholder")}
          aria-label={t("ide_side_panel.prompt.input_aria")}
          data-testid="ide-prompt-input"
          className={FIELD}
        />
        <div className="flex min-w-0 items-center gap-2">
          <div className="min-w-0 flex-1">
            <Combobox
              ariaLabel={t("ide_side_panel.prompt.model_aria")}
              testId="ide-prompt-model"
              value={pick}
              groups={modelGroups}
              onChange={(value) => { setPick(value); persist(MODEL_KEY, value); }}
              fallbackLabel={pickedModel || pickedProvider || t("ide_side_panel.prompt.model_auto")}
              searchPlaceholder={t("ide_side_panel.prompt.model_search")}
              triggerHint={false}
              panelMinWidth={300}
              className="h-8 py-0"
            />
          </div>
          <button type="button" onClick={() => void improve()} disabled={!draft.trim() || busy !== null}
            data-testid="ide-prompt-improve" className={MAIN_BTN}>
            {busy === "improve" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Sparkles className="h-3.5 w-3.5" aria-hidden />}
            {busy === "improve" ? t("ide_side_panel.prompt.improving") : t("ide_side_panel.prompt.improve")}
          </button>
        </div>

        <details className="group">
          <summary className={cn(LABEL, "cursor-pointer select-none hover:text-foreground")} data-testid="ide-prompt-instruction-toggle">
            {t("ide_side_panel.prompt.instruction")}
            {instruction.trim() && <span className="ms-1.5 text-accent">•</span>}
          </summary>
          <div className="mt-2 flex flex-col gap-1.5">
            <textarea
              value={instruction}
              onChange={(event) => { setInstruction(event.target.value); persist(INSTRUCTION_KEY, event.target.value); }}
              rows={3}
              maxLength={MAX_INSTRUCTION_CHARS}
              placeholder={defaultInstruction}
              aria-label={t("ide_side_panel.prompt.instruction")}
              data-testid="ide-prompt-instruction"
              className={FIELD}
            />
            <div className="flex items-start gap-2">
              <p className="min-w-0 flex-1 text-xs text-muted-foreground">{t("ide_side_panel.prompt.instruction_hint")}</p>
              <button type="button" onClick={() => { setInstruction(""); persist(INSTRUCTION_KEY, ""); }} disabled={!instruction}
                className={cn(QUIET_BTN, "h-7 px-2 text-xs")}>
                <RotateCcw className="h-3 w-3" aria-hidden />
                {t("ide_side_panel.prompt.instruction_reset")}
              </button>
            </div>
          </div>
        </details>

        {improved !== null && (
          <section className="flex flex-col gap-2 border-t border-border/60 pt-3" data-testid="ide-prompt-result">
            <div className="flex items-baseline justify-between gap-2">
              <span className={LABEL}>{t("ide_side_panel.prompt.result")}</span>
              {writer && <span className="min-w-0 truncate text-xs text-muted-foreground">{fill(t("ide_side_panel.prompt.written_by"), { model: writer })}</span>}
            </div>
            <textarea
              value={improved}
              onChange={(event) => { setImproved(event.target.value); setNotice(null); }}
              onKeyDown={onModifierEnter(() => void send())}
              rows={12}
              spellCheck={false}
              aria-label={t("ide_side_panel.prompt.result")}
              data-testid="ide-prompt-output"
              className={FIELD}
            />
            {tooLong && (
              <p role="alert" className="text-xs text-destructive">
                {fill(t("ide_side_panel.prompt.too_long"), { count: text.length, max: MAX_PROMPT_CHARS })}
              </p>
            )}
            <div className="flex min-w-0 items-center gap-2">
              <div className="min-w-0 flex-1">
                <Combobox
                  ariaLabel={t("ide_side_panel.prompt.target_aria")}
                  testId="ide-prompt-target"
                  value={target ? paneId(target) : ""}
                  groups={paneGroups}
                  onChange={setChosenPane}
                  fallbackLabel={t("ide_side_panel.prompt.no_target")}
                  disabled={targets.length === 0}
                  panelMinWidth={260}
                  className="h-8 py-0"
                />
              </div>
              <button type="button" onClick={copy} disabled={!text} data-testid="ide-prompt-copy"
                aria-label={t("ide_side_panel.prompt.copy")} title={t("ide_side_panel.prompt.copy")} className={cn(QUIET_BTN, "w-8 justify-center px-0")}>
                {copied ? <Check className="h-3.5 w-3.5" aria-hidden /> : <Copy className="h-3.5 w-3.5" aria-hidden />}
              </button>
              <button type="button" onClick={() => void send()} disabled={!text || tooLong || !target || busy !== null}
                data-testid="ide-prompt-send" className={MAIN_BTN}>
                {busy === "send" ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <ArrowRight className="h-3.5 w-3.5" aria-hidden />}
                {t("ide_side_panel.prompt.send")}
              </button>
            </div>
            {targets.length === 0 && <p className="text-xs text-muted-foreground">{t("ide_side_panel.prompt.no_target_hint")}</p>}
          </section>
        )}

        {error && <p role="alert" data-testid="ide-prompt-error" className="text-xs text-destructive">{error}</p>}
        {notice && (
          <p role="status" data-testid="ide-prompt-notice" className={cn("text-xs", notice.tone === "ok" ? "text-success" : "text-warning")}>
            {notice.text}
          </p>
        )}
      </div>
    </div>
  );
}
