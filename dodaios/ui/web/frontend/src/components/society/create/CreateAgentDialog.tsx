/**
 * "New agent": three ways from an idea to a working teammate.
 *
 *  - Blank: a name and, optionally, one line on its job (the structured
 *    brief's mission), the seat and the companion.
 *  - From a starter: a gallery of job-shaped agents we wrote ourselves
 *    (`dodaios/society/starters`), each previewed with what it brings before
 *    it is created; the chat then opens with a suggested first message in
 *    the composer, never sent.
 *  - Import: a template somebody shared, pasted or opened, previewed the same
 *    way and checked against the marketplace's stranger-safety rules.
 *
 * Every path runs on the seat picked here (`SeatFields`): any runtime
 * (fixed for the agent's life) and any connected provider. Mounted once
 * (App.tsx); every plus opens it through `useCreateAgentDialog`.
 */
import { useEffect, useMemo, useRef, useState, Suspense, lazy, type KeyboardEvent, type ReactNode } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileInput, LayoutGrid, Loader2, PencilLine, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fill, useT } from "@/i18n";
import { cn } from "@/lib/utils";
import { AgentNameTaken, RuntimeProviderUnsupported, rowToAgent, useCreateSocietyAgent, type SocietyAgent } from "../data";
import type { SocietyAgentRow } from "@/lib/societyApi";
import { defaultCompanion, type CompanionAppearance } from "../companion/appearance";
import { randomCreature } from "../companion/creature";
import { announceSpawn } from "../world/spawnStore";
import { useCreateAgentDialog, type CreateAgentMode } from "./createAgentStore";
import { seedFirstMessage } from "./firstMessage";
import { EMPTY_IMPORT, ImportTemplatePane, type ImportState } from "./ImportTemplatePane";
import { SeatFields, SeatSummary, useCreateSeat, type SeatPick } from "./SeatFields";
import { StarterGallery } from "./StarterGallery";
import { defaultTools, starterCopy, type AreaFilter } from "./starterFilters";
import { StarterIcon } from "./starterIcons";
import { installStarter, useStarters, type InstallStarterResult, type Starter, type StarterSeat } from "./startersApi";
import { TemplatePreviewCard } from "./TemplatePreviewCard";

const CompanionEditor = lazy(() =>
  import("../companion/CompanionEditor").then((m) => ({ default: m.CompanionEditor })),
);

const MODES: readonly { id: CreateAgentMode; icon: ReactNode }[] = [
  { id: "quick", icon: <PencilLine className="size-3.5" aria-hidden /> },
  { id: "starter", icon: <LayoutGrid className="size-3.5" aria-hidden /> },
  { id: "import", icon: <FileInput className="size-3.5" aria-hidden /> },
];

/** A new agent starts as a pixel creature; the shape underneath is there for a change of mind. */
function randomCompanion(): CompanionAppearance {
  return { ...defaultCompanion(`${Date.now()}:${Math.random()}`), creature: randomCreature() };
}

function starterSeat(pick: SeatPick, companion: CompanionAppearance): StarterSeat {
  const seat: StarterSeat = { companion, execution_environment: pick.executionEnvironment };
  if (pick.runtime !== "jarvis") seat.runtime = pick.runtime;
  if (pick.provider) {
    seat.provider = pick.provider;
    if (pick.model) seat.model = pick.model;
    if (pick.accountId) seat.account_id = pick.accountId;
  }
  return seat;
}

export function CreateAgentDialogHost() {
  const open = useCreateAgentDialog((s) => s.open);
  const requestId = useCreateAgentDialog((s) => s.requestId);
  // A fresh form every time it opens.
  return open ? <CreateAgentDialog key={requestId} /> : null;
}

function CreateAgentDialog() {
  const t = useT();
  const client = useQueryClient();
  const { finish, cancel } = useCreateAgentDialog.getState();
  const initial = useCreateAgentDialog((s) => s.initial);
  const createAgent = useCreateSocietyAgent();
  const seat = useCreateSeat();
  const [mode, setMode] = useState<CreateAgentMode>(initial.mode ?? "quick");
  const modeTabs = useRef<(HTMLButtonElement | null)[]>([]);
  function onModeKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const last = MODES.length - 1;
    const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: last }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    const target = (next + MODES.length) % MODES.length;
    modeTabs.current[target]?.focus();
    setMode(MODES[target].id);
    setError(null);
  }
  const [name, setName] = useState("");
  const [job, setJob] = useState("");
  const [companion, setCompanion] = useState<CompanionAppearance>(randomCompanion);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Created, but the routine it was asked for could not be set up: say so before the chat opens.
  const [created, setCreated] = useState<{ agent: SocietyAgent; routineError: string } | null>(null);

  // Starter path.
  const starters = useStarters(mode === "starter");
  const [area, setArea] = useState<AreaFilter>("all");
  const [query, setQuery] = useState("");
  const [starterId, setStarterId] = useState<string | null>(null);
  const [starterName, setStarterName] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [routineOn, setRoutineOn] = useState(false);
  const [mobilePreview, setMobilePreview] = useState(false);
  const starterList = useMemo(() => starters.data?.starters ?? [], [starters.data]);
  const starter = starterList.find((entry) => entry.id === starterId) ?? null;
  const copy = starter ? starterCopy(t, starter) : null;

  function pickStarter(next: Starter) {
    if (next.id === starterId) { setMobilePreview(true); return; }
    setStarterId(next.id);
    setStarterName(starterCopy(t, next).name);
    setPicked(new Set(defaultTools(next.tools)));
    setRoutineOn(false);
    setMobilePreview(true);
  }
  useEffect(() => {
    // The preview is never empty: the gallery opens on its first starter.
    if (!starterId && starterList.length) {
      const first = starterList[0];
      setStarterId(first.id);
      setStarterName(starterCopy(t, first).name);
      setPicked(new Set(defaultTools(first.tools)));
    }
    // `t` is a fresh function every render; the first pick only follows the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [starterId, starterList]);

  // Import path.
  const [importText, setImportText] = useState(() => initial.template ? JSON.stringify(initial.template, null, 2) : "");
  const [imported, setImported] = useState<ImportState>(EMPTY_IMPORT);
  const [importName, setImportName] = useState("");
  const [importPicked, setImportPicked] = useState<Set<string>>(new Set());
  const importKey = imported.preview ? JSON.stringify(imported.template) : "";
  useEffect(() => {
    if (!imported.preview) return;
    setImportName(imported.preview.template?.name ?? "");
    // The author's tools all stay picked; unticking narrows, nothing is added.
    setImportPicked(new Set(imported.preview.tools.map((tool) => tool.id)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [importKey]);

  const pathReady = mode === "quick" ? true : mode === "starter" ? Boolean(starter) : Boolean(imported.preview && imported.template && !imported.pending);
  const canCreate = !saving && seat.ready && pathReady;

  async function afterInstall(result: InstallStarterResult, firstMessage: string) {
    const agent = rowToAgent(result.agent as unknown as SocietyAgentRow);
    // The island owes this row an entrance: it walks out of the foundry.
    announceSpawn(agent.agentId);
    await client.invalidateQueries({ queryKey: ["society", "roster"] });
    await seedFirstMessage(agent, firstMessage).catch(() => false);
    if (result.routine_error) {
      setCreated({ agent, routineError: result.routine_error });
      setSaving(false);
      return;
    }
    finish(agent);
  }

  async function submit() {
    if (created) { finish(created.agent); return; }
    if (!canCreate) return;
    setSaving(true);
    setError(null);
    try {
      if (mode === "quick") {
        const agent = await createAgent({
          name,
          mission: job,
          runtime: seat.pick.runtime,
          executionEnvironment: seat.pick.executionEnvironment,
          provider: seat.pick.provider,
          model: seat.pick.model,
          accountId: seat.pick.accountId,
          companion,
        });
        finish(agent);
        return;
      }
      if (mode === "starter" && starter && copy) {
        const result = await installStarter({
          starterId: starter.id,
          // The name is optional: an emptied field keeps the starter's own.
          name: starterName.trim() || copy.name,
          tools: [...picked],
          withRoutine: Boolean(starter.routine && routineOn),
          seat: starterSeat(seat.pick, companion),
        });
        await afterInstall(result, copy.firstMessage);
        return;
      }
      if (mode === "import" && imported.template) {
        const result = await installStarter({
          template: imported.template,
          name: importName.trim() || imported.preview?.template?.name || "",
          tools: [...importPicked],
          seat: starterSeat(seat.pick, companion),
        });
        await afterInstall(result, "");
      }
    } catch (exc) {
      setError(
        exc instanceof AgentNameTaken
          ? t("society.create_agent.name_taken")
          : exc instanceof RuntimeProviderUnsupported
            ? t("society.runtime.provider_unsupported")
            : exc instanceof Error ? exc.message : String(exc),
      );
      setSaving(false);
    }
  }

  const toggle = (set: Set<string>, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  };

  const submitLabel = created
    ? t("agent_create.open_chat")
    : t(saving ? "society.create_agent.creating" : "society.create_agent.create");

  return (
    <Dialog.Root open onOpenChange={(next) => { if (!next && !saving) (created ? finish(created.agent) : cancel()); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-scrim/60 backdrop-blur-sm motion-safe:animate-in motion-safe:fade-in-0" />
        <Dialog.Content
          data-testid="create-agent-dialog"
          aria-describedby={undefined}
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[92dvh] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden",
            "rounded-[18px] border border-border bg-popover text-foreground shadow-float",
            mode === "quick" ? "w-[min(880px,calc(100vw-24px))]" : "h-[min(720px,92dvh)] w-[min(960px,calc(100vw-24px))]",
          )}
        >
          <header className="flex shrink-0 flex-col gap-3 border-b border-border px-5 pb-3 pt-4">
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <Dialog.Title className="text-lg font-semibold text-foreground-strong">{t("society.create_agent.title")}</Dialog.Title>
                <p className="text-sm text-muted-foreground" data-testid="create-agent-subtitle">{t(`agent_create.mode.${mode}_hint`)}</p>
              </div>
              <button type="button" aria-label={t("society.card.close")} onClick={() => { if (!saving) (created ? finish(created.agent) : cancel()); }}
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                <X size={18} />
              </button>
            </div>
            <div role="tablist" aria-label={t("agent_create.mode.label")} className="flex w-full gap-1 rounded-[10px] border border-border bg-background/60 p-1 sm:w-auto sm:self-start">
              {MODES.map((entry, index) => {
                const on = entry.id === mode;
                return (
                  <button
                    key={entry.id}
                    ref={(node) => { modeTabs.current[index] = node; }}
                    type="button"
                    role="tab"
                    aria-selected={on}
                    tabIndex={on ? 0 : -1}
                    onKeyDown={(event) => onModeKey(event, index)}
                    disabled={saving || Boolean(created)}
                    onClick={() => { setMode(entry.id); setError(null); }}
                    data-testid={`create-agent-mode-${entry.id}`}
                    className={cn(
                      "inline-flex flex-1 items-center justify-center gap-1.5 rounded-[7px] px-3 py-1.5 text-sm transition-colors duration-150 sm:flex-none",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                      on ? "bg-secondary text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {entry.icon}
                    {t(`agent_create.mode.${entry.id}`)}
                  </button>
                );
              })}
            </div>
          </header>

          <form className="flex min-h-0 flex-1 flex-col" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
            {mode === "quick" ? (
              <div className="grid min-h-0 flex-1 overflow-y-auto md:grid-cols-2 md:overflow-hidden">
                <div className="flex min-h-0 flex-col gap-5 p-5 md:overflow-y-auto">
                  <label className="flex flex-col gap-1.5 text-sm">
                    <span className="font-medium">{t("society.create_agent.name_label")}</span>
                    <Input
                      autoFocus
                      value={name}
                      maxLength={40}
                      onChange={(event) => setName(event.target.value)}
                      placeholder={t("society.create_agent.name_placeholder")}
                      disabled={saving}
                      data-testid="create-agent-name"
                    />
                  </label>
                  <label className="flex flex-col gap-1.5 text-sm">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="font-medium">{t("agent_create.quick.job_label")}</span>
                      <span className="text-xs text-foreground-faint">{t("agent_create.quick.optional")}</span>
                    </span>
                    <Input
                      value={job}
                      maxLength={300}
                      onChange={(event) => setJob(event.target.value)}
                      placeholder={t("agent_create.quick.job_placeholder")}
                      disabled={saving}
                      data-testid="create-agent-job"
                    />
                    <span className="text-xs text-muted-foreground">{t("agent_create.quick.job_hint")}</span>
                  </label>
                  <div className="flex flex-col gap-1.5 text-sm">
                    <span className="font-medium">{t("society.create_agent.companion_label")}</span>
                    <div className="-mx-5">
                      <Suspense fallback={null}>
                        <CompanionEditor value={companion} onChange={setCompanion} disabled={saving} />
                      </Suspense>
                    </div>
                  </div>
                </div>
                <div className="min-h-0 border-t border-border p-5 md:overflow-y-auto md:border-l md:border-t-0">
                  <SeatFields seat={seat} disabled={saving} />
                </div>
              </div>
            ) : mode === "starter" ? (
              <div className="grid min-h-0 flex-1 md:grid-cols-[320px_minmax(0,1fr)]">
                <div className={cn("flex min-h-0 flex-col p-4 md:border-r md:border-border", mobilePreview && "hidden md:flex")}>
                  <StarterGallery
                    starters={starterList}
                    areas={starters.data?.areas ?? []}
                    loading={starters.isLoading}
                    failed={starters.isError}
                    onRetry={() => void starters.refetch()}
                    area={area}
                    onAreaChange={setArea}
                    query={query}
                    onQueryChange={setQuery}
                    selectedId={starterId}
                    onSelect={pickStarter}
                  />
                </div>
                <div className={cn("flex min-h-0 flex-col gap-4 overflow-y-auto p-5", !mobilePreview && "hidden md:flex")}>
                  <button type="button" onClick={() => setMobilePreview(false)}
                    className="inline-flex items-center gap-1.5 self-start rounded text-xs text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:hidden">
                    <ArrowLeft className="size-3.5" aria-hidden /> {t("agent_create.gallery.back")}
                  </button>
                  {starter && copy ? (
                    <TemplatePreviewCard
                      icon={<StarterIcon name={starter.icon} />}
                      name={starterName}
                      defaultName={copy.name}
                      onNameChange={setStarterName}
                      outcome={copy.outcome}
                      summary={starter.summary}
                      instructions={starter.instructions}
                      tools={starter.tools}
                      picked={picked}
                      onToggleTool={(id) => setPicked((current) => toggle(current, id))}
                      routine={starter.routine ? { title: copy.routineTitle, when: starter.routine.when } : null}
                      routineOn={routineOn}
                      onRoutineChange={setRoutineOn}
                      firstMessage={copy.firstMessage}
                      disabled={saving || Boolean(created)}
                    />
                  ) : (
                    <EmptyPreview text={t(starters.isLoading ? "agent_create.gallery.loading" : "agent_create.preview.pick_prompt")} />
                  )}
                  <SeatSummary seat={seat} disabled={saving} />
                </div>
              </div>
            ) : (
              <div className="grid min-h-0 flex-1 overflow-y-auto md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] md:overflow-hidden">
                <div className="min-h-0 p-5 md:overflow-y-auto md:border-r md:border-border">
                  <ImportTemplatePane text={importText} onTextChange={setImportText} onChange={setImported} disabled={saving} />
                </div>
                <div className="flex min-h-0 flex-col gap-4 p-5 md:overflow-y-auto">
                  {imported.preview?.template && imported.preview.summary ? (
                    <TemplatePreviewCard
                      icon={<FileInput />}
                      name={importName}
                      defaultName={imported.preview.template.name}
                      onNameChange={setImportName}
                      outcome={imported.preview.template.title || t("agent_create.import.no_title")}
                      summary={imported.preview.summary}
                      instructions={imported.preview.template.instructions}
                      tools={imported.preview.tools}
                      picked={importPicked}
                      onToggleTool={(id) => setImportPicked((current) => toggle(current, id))}
                      disabled={saving || Boolean(created)}
                      note={<p className="text-xs text-foreground-faint">{t("agent_create.import.design_only")}</p>}
                    />
                  ) : (
                    <EmptyPreview text={t("agent_create.import.empty_preview")} />
                  )}
                  <SeatSummary seat={seat} disabled={saving} />
                </div>
              </div>
            )}

            <footer className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t border-border px-5 py-3">
              {created ? (
                <p role="alert" className="mr-auto flex items-center gap-1.5 text-sm text-warning" data-testid="create-agent-routine-error">
                  <TriangleAlert className="size-4 shrink-0" aria-hidden />
                  {fill(t("agent_create.routine_failed"), { agent: created.agent.name })}
                </p>
              ) : error ? (
                <p role="alert" className="mr-auto text-sm text-destructive">{error}</p>
              ) : (
                <p className="mr-auto hidden text-xs text-muted-foreground sm:block">{t(`agent_create.footer.${mode}`)}</p>
              )}
              {!created ? (
                <Button type="button" variant="ghost" onClick={() => cancel()} disabled={saving}>
                  {t("society.create_agent.cancel")}
                </Button>
              ) : null}
              <Button type="submit" disabled={!created && !canCreate} data-testid="create-agent-submit">
                {saving ? <Loader2 className="animate-spin" aria-hidden /> : null}
                {submitLabel}
              </Button>
            </footer>
          </form>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function EmptyPreview({ text }: { text: string }) {
  return (
    <div className="flex min-h-[220px] flex-1 flex-col items-center justify-center gap-2 rounded-[12px] border border-dashed border-border px-6 text-center" data-testid="create-agent-empty-preview">
      <LayoutGrid className="size-5 text-foreground-faint" aria-hidden />
      <p className="max-w-[28ch] text-sm text-muted-foreground">{text}</p>
    </div>
  );
}
