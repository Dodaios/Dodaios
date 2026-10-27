/**
 * Per-agent routines: the jobs an agent runs on its own. They live in the
 * same task store and trigger editor as Automations; this list adds the
 * schedule as a sentence, the next run, the last result and its cost, quick
 * pause/test actions, "set one up in chat", and the away-parking note.
 */
import { useEffect, useMemo, useState } from "react";
import { MessageSquarePlus, Plus, Sparkles, X } from "lucide-react";
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
  const [prompt, setPrompt] = useState(""); const [schedule, setSchedule] = useState<Record<string, unknown> | null>(null);
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
  const submit = async () => {
    if (!title.trim() || !prompt.trim() || !schedule) return;
    setSaving(true); setError("");
    try { await create(agentId, { title: title.trim(), prompt: prompt.trim(), schedule }); setTitle(""); setPrompt(""); setOpen(false); }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setSaving(false); }
  };
  if (selectedRoutine) return <AgentRoutineDetail key={`${agentId}:${selected}`} agentId={agentId} routine={selectedRoutine} parked={parked.has(selectedRoutine.id)} onClose={() => setSelected(null)} />;
  const lastRunOf = (routine: LiveRoutine) => (routine.members ?? [routine])
    .map((member) => lastRuns[member.id]).filter(Boolean)
    .sort((a, b) => (b!.started_ms ?? 0) - (a!.started_ms ?? 0))[0] ?? null;
  const activeCount = rows.filter((row) => row.state !== "paused").length;
  return <section className={cn("flex min-h-0 flex-col", className)} data-testid="agent-routines">
    <div className="mb-2 flex shrink-0 items-center justify-between gap-2">
      <h3 className={variant === "sheet" ? "ac-head" : "font-display text-[13px] font-semibold text-foreground"}>
        {t("society.card.routines")}
        {rows.length > 0 && <span className="ml-1.5 font-normal text-muted-foreground" title={own("active_hint")}>{activeCount === rows.length ? rows.length : `${activeCount}/${rows.length}`}</span>}
      </h3>
      <div className="flex items-center gap-0.5">
        {!isSample && <button type="button" data-testid="agent-routines-chat" className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground" aria-label={own("setup_in_chat")} title={own("setup_in_chat")} onClick={setUpInChat}><MessageSquarePlus size={14} /></button>}
        <button type="button" data-testid="agent-routines-add" className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground" aria-label={t("society.card.routines_add")} aria-expanded={open} onClick={() => setOpen((v) => !v)}>{open ? <X size={14} /> : <Plus size={14} />}</button>
      </div>
    </div>
    {parking?.banner && parking.parked_ids.length > 0 && <ParkingBanner agentId={agentId} parking={parking} onAnswered={() => void refresh()} />}
    {open && <form className="mb-3 space-y-2 rounded-xl border border-border bg-card p-2.5 shadow-[0_1px_2px_rgb(var(--scrim-rgb)/0.05),0_4px_12px_-6px_rgb(var(--scrim-rgb)/0.12)]" data-testid="agent-routines-composer" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <input className={field} aria-label={t("society.card.routines_title")} placeholder={t("society.card.routines_title")} value={title} onChange={(e) => setTitle(e.target.value)} />
      <textarea className={cn(field, "resize-y leading-snug")} aria-label={t("society.card.routines_prompt")} placeholder={t("society.card.routines_prompt")} value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} />
      <TriggerBuilder onChange={setSchedule} />
      <div className="flex items-center justify-between gap-2 pt-0.5">
        {!isSample ? <button type="button" className="text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline" onClick={() => { setOpen(false); setUpInChat(); }}>{own("or_chat")}</button> : <span />}
        <button type="submit" disabled={saving || !title.trim() || !prompt.trim() || !schedule} className="rounded-lg bg-foreground px-3 py-1 text-[12px] font-medium text-background transition-colors hover:bg-foreground/90 disabled:opacity-40">{t(saving ? "society.card.saving" : "society.card.routines_save")}</button>
      </div>
      {error && <p role="alert" className="text-[11px] text-destructive">{error}</p>}
    </form>}
    <ul className="-mx-1 min-h-0 flex-1 space-y-0.5 overflow-y-auto px-1">
      {live.error && !live.data && <li role="alert" className="text-[12px] text-destructive">{t("tasks_view.load_error")}</li>}
      {rows.length === 0 && live.isPending && <li className="text-[12px] text-muted-foreground">{t("society.profile_card.loading")}</li>}
      {rows.length === 0 && !live.isPending && !live.error && <li className="rounded-xl border border-dashed border-border px-3 py-4 text-center">
        <Sparkles size={16} aria-hidden className="mx-auto mb-1.5 text-faint-foreground" />
        <p className="text-[12.5px] font-medium text-foreground">{t("society.card.no_routines")}</p>
        <p className="mx-auto mt-1 max-w-[30ch] text-[11.5px] leading-snug text-muted-foreground">{own("empty_body")}</p>
        {!isSample && <button type="button" onClick={setUpInChat} className="mt-2.5 inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11.5px] text-foreground transition-colors hover:bg-secondary"><MessageSquarePlus size={12} />{own("setup_in_chat")}</button>}
      </li>}
      {rows.map((routine) => <RoutineRow key={routine.id} routine={routine} lastRun={lastRunOf(routine)} parked={parked.has(routine.id)}
        locale={locale} now={now} onOpen={() => setSelected(routine.id)} onChanged={() => void refresh()} />)}
    </ul>
    {!isSample && rows.length > 0 && <AwaySetting agentId={agentId} neverAsk={Boolean(parking?.never_ask)} onChanged={() => void refresh()} />}
  </section>;
}
export default AgentRoutinesList;
