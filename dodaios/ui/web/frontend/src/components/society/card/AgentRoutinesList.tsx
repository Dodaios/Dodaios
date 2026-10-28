/**
 * Per-agent routines: the jobs an agent runs on its own. They live in the
 * same task store and trigger editor as Automations; this list adds the
 * schedule as a sentence, the next run, the last result and its cost, quick
 * pause/test actions, "set one up in chat", and the away-parking note.
 */
import { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { useLocaleChunk, useT } from "@/i18n";
import { useRunLocale } from "@/components/runs/format";
import { cn } from "@/lib/utils";
import { useAgentRoutines, useCreateAgentRoutine, type LiveRoutine } from "../cardData";
import { useSocietyAgent, type AgentRoutine } from "../data";
import { TriggerBuilder } from "./TriggerBuilder";
import { AgentRoutineDetail } from "./AgentRoutineDetail";
import { RoutineRow } from "./routines/RoutineRow";
import { ParkingBanner } from "./routines/ParkingBanner";
import { AwaySetting } from "./routines/AwaySetting";
import { markRoutinesSeen, useRoutineActivity, useRoutineRefresh } from "./routines/routinesApi";
import { seedAgentComposer } from "./routines/editThroughChat";
import { useNow } from "./routines/useNow";
import { humanSchedule } from "./routines/humanSchedule";
import { parseScheduleText } from "./routines/scheduleText";

export interface AgentRoutinesListProps { agentId: string; sampleRoutines?: AgentRoutine[]; variant?: "rail" | "sheet"; className?: string; onDetailOpenChange?: (open: boolean) => void; }
export function AgentRoutinesList({ agentId, sampleRoutines, variant = "rail", className, onDetailOpenChange }: AgentRoutinesListProps) {
  const t = useT(); useLocaleChunk("society");
  const locale = useRunLocale();
  const own = (key: string) => t(`society.agent_routines.list.${key}`);
  const live = useAgentRoutines(agentId); const create = useCreateAgentRoutine();
  const isSample = Boolean(sampleRoutines);
  const activity = useRoutineActivity(isSample ? null : agentId);
  const refresh = useRoutineRefresh(agentId);
  const { agent } = useSocietyAgent(agentId);
  const now = useNow();
  const [open, setOpen] = useState(false); const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState(""); const [built, setBuilt] = useState<Record<string, unknown> | null>(null);
  // The schedule in plain words ("every weekday at 7"); the detailed editor waits under "More options".
  const [when, setWhen] = useState(""); const [more, setMore] = useState(false);
  const typed = useMemo(() => (when.trim() ? parseScheduleText(when) : null), [when]);
  // The detailed editor replaces the words while it is open; closing it brings them back.
  const schedule: Record<string, unknown> | null = more ? built : typed;
  const [saving, setSaving] = useState(false); const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const sample = useMemo(() => (sampleRoutines ?? []).map((row) => ({ id: row.id, title: row.label, state: "scheduled", trigger: null, schedule: row.schedule, dueMs: row.nextFire ? Date.parse(row.nextFire) : null, lastRunMs: null })), [sampleRoutines]);
  const rows: LiveRoutine[] = live.data ?? sample;
  const selectedRoutine = rows.find((row) => row.id === selected);
  const detailOpen = Boolean(selectedRoutine);
  useEffect(() => { onDetailOpenChange?.(detailOpen); }, [detailOpen, onDetailOpenChange]);
  // Showing the routines is looking at their results: a new away period starts.
  useEffect(() => { if (!isSample) markRoutinesSeen(agentId); }, [agentId, isSample]);
  const parking = activity.data?.parking ?? null;
  const parked = new Set(parking?.parked_ids ?? []);
  const lastRuns = activity.data?.lastRuns ?? {};
  const target = { tier: agent?.tier ?? "specialist", chatSessionId: agent?.chatSessionId ?? `society:${agentId}` };
  const setUpInChat = () => void seedAgentComposer(target, own("setup_prompt"));
  const field = "w-full rounded-lg border border-border bg-background px-2.5 py-1.5 text-[12px] text-foreground placeholder:text-faint-foreground transition-colors focus:border-border-strong focus:outline-none";
  // Closing the form drops what it held: a draft nobody sees must never
  // come back under the caret the next time the form opens.
  const closeForm = () => {
    setOpen(false); setTitle(""); setPrompt(""); setWhen(""); setMore(false); setBuilt(null); setError("");
  };
  const submit = async () => {
    if (!title.trim() || !prompt.trim() || !schedule) return;
    setSaving(true); setError("");
    try { await create(agentId, { title: title.trim(), prompt: prompt.trim(), schedule }); closeForm(); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setSaving(false); }
  };
  if (selectedRoutine) return <AgentRoutineDetail key={`${agentId}:${selected}`} agentId={agentId} routine={selectedRoutine} parked={parked.has(selectedRoutine.id)} onClose={() => setSelected(null)} />;
  const lastRunOf = (routine: LiveRoutine) => (routine.members ?? [routine])
    .map((member) => lastRuns[member.id]).filter(Boolean)
    .sort((a, b) => (b!.started_ms ?? 0) - (a!.started_ms ?? 0))[0] ?? null;
  return <section className={cn("flex min-h-0 flex-col", className)} data-testid="agent-routines">
    <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
      <h3 className={variant === "sheet" ? "ac-head" : "px-1 text-[13px] font-medium text-muted-foreground"}>
        {t("society.card.routines")}
      </h3>
      <div className="flex items-center gap-0.5">
        <button type="button" data-testid="agent-routines-add" className="as-round-button h-7 w-7" aria-label={t("society.card.routines_add")} aria-expanded={open} onClick={() => (open ? closeForm() : setOpen(true))}>{open ? <X size={14} /> : <Plus size={14} />}</button>
      </div>
    </div>
    {parking?.banner && parking.parked_ids.length > 0 && <ParkingBanner agentId={agentId} parking={parking} onAnswered={() => void refresh()} />}
    {open && <form className="mb-3 space-y-2 rounded-xl border border-border bg-card p-2.5 shadow-[0_1px_2px_rgb(var(--scrim-rgb)/0.05),0_4px_12px_-6px_rgb(var(--scrim-rgb)/0.12)]" data-testid="agent-routines-composer" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <input className={field} aria-label={t("society.card.routines_title")} placeholder={t("society.card.routines_title")} value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea className={cn(field, "resize-y leading-snug")} aria-label={t("society.card.routines_prompt")} placeholder={t("society.card.routines_prompt")} value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} />
      {!more && <label className="block space-y-1 text-[12px] text-muted-foreground">
        <span>{own("when_label")}</span>
        <input className={field} aria-label={own("when_label")} placeholder={own("when_placeholder")} value={when}
          onChange={(e) => setWhen(e.target.value)} data-testid="agent-routines-when" />
      </label>}
      {!more && when.trim() ? <p aria-live="polite" data-testid="agent-routines-when-preview"
        className={cn("text-[12px] leading-snug", typed ? "text-foreground-secondary" : "text-muted-foreground")}>
        {typed ? humanSchedule(typed, { t, locale }) : own("when_unclear")}
      </p> : null}
      <button type="button" className="text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline" aria-expanded={more}
        onClick={() => setMore((v) => !v)} data-testid="agent-routines-more">{own(more ? "fewer_options" : "more_options")}</button>
      {more ? <TriggerBuilder onChange={setBuilt} /> : null}
      <div className="flex items-center justify-between gap-2 pt-0.5">
        {!isSample ? <button type="button" className="text-[12px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline" onClick={() => { closeForm(); setUpInChat(); }}>{own("or_chat")}</button> : <span />}
        <button type="submit" disabled={saving || !title.trim() || !prompt.trim() || !schedule} className="rounded-full bg-foreground px-3.5 py-1.5 text-[13px] font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-40">{t(saving ? "society.card.saving" : "society.card.routines_save")}</button>
      </div>
      {error && <p role="alert" className="text-[12px] text-destructive">{error}</p>}
    </form>}
    <ul className={cn("min-h-0 shrink overflow-y-auto", rows.length > 0 && "rounded-2xl bg-card p-1")}>
      {live.error && !live.data && <li role="alert" className="text-[12px] text-destructive">{t("tasks_view.load_error")}</li>}
      {rows.length === 0 && live.isPending && <li className="text-[12px] text-muted-foreground">{t("society.profile_card.loading")}</li>}
      {rows.length === 0 && !live.isPending && !live.error && <li className="rounded-2xl bg-card px-4 py-5 text-center">
                <p className="text-[14px] font-medium text-foreground">{t("society.card.no_routines")}</p>
        <p className="mx-auto mt-1 max-w-[30ch] text-[13px] leading-snug text-muted-foreground">{own("empty_body")}</p>
        {!isSample && <button type="button" onClick={setUpInChat} className="mt-3 inline-flex items-center rounded-full bg-secondary px-3.5 py-1.5 text-[13px] text-foreground transition-colors hover:bg-border">{own("setup_in_chat")}</button>}
      </li>}
      {rows.map((routine) => <RoutineRow key={routine.id} routine={routine} lastRun={lastRunOf(routine)} parked={parked.has(routine.id)}
        locale={locale} now={now} onOpen={() => setSelected(routine.id)} onChanged={() => void refresh()} />)}
    </ul>
    {!isSample && rows.length > 0 && <button type="button" data-testid="agent-routines-chat" onClick={setUpInChat}
      className="mt-2 self-start rounded-full px-3 py-1.5 text-[13px] text-muted-foreground transition-colors duration-150 hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{own("setup_in_chat")}</button>}
    {!isSample && rows.length > 0 && <AwaySetting agentId={agentId} neverAsk={Boolean(parking?.never_ask)} onChanged={() => void refresh()} />}
  </section>;
}
export default AgentRoutinesList;
