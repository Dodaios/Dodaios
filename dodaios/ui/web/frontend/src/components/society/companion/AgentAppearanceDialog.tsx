import { useRef, useState, Suspense, lazy } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useT } from "@/i18n";
import { societyDisplayName } from "@/lib/societyDisplayName";
import { useEventStore } from "@/store/events";
import type { SocietyAgent } from "../data";
import { AgentSwatch } from "../AgentSwatch";
import { defaultRecipe, EDITABLE_CELLS, resolvePalette, type FigureRecipe } from "../figures/figureRecipe";
import { HAIR_STYLES } from "../figures/toy/playerProfile";
import { toyLookFor } from "../figures/toy/toyFigureModel";
import { pinLook, withHair } from "../figures/toy/wardrobe";
import { CompanionEditor } from "./CompanionEditor";
import { resolveCompanion } from "./appearance";
import "../calmSheet.css";

const AgentFigureViewer = lazy(() => import("../figures/AgentFigureViewer").then(m => ({ default: m.AgentFigureViewer })));

/** The toy figure's look: hair or hat, and the six colours it wears. */
function CharacterEditor({ value, onChange, disabled }: { value: FigureRecipe; onChange: (r: FigureRecipe) => void; disabled: boolean }) {
  const t = useT();
  // The colours the figure actually wears: an undressed recipe shows its default office outfit.
  const look = toyLookFor(value, "");
  const colors = { ...resolvePalette(value), skin: look.skin, hair: look.hair, primary: look.shirt, secondary: look.pants, accent: look.shirtAccent, shoes: look.shoes };
  const hair = look.hairStyle;
  // Pin the shown look first, so changing one colour never swaps the whole outfit.
  const setCell = (cell: string, color: string) => { const pinned = pinLook(value); onChange({ ...pinned, palette: { ...pinned.palette, [cell]: color } }); };
  return <fieldset disabled={disabled} className="grid gap-4 p-4" data-testid="character-editor">
    <div className="h-60"><Suspense fallback={null}><AgentFigureViewer recipe={value} quiet /></Suspense></div>
    <div className="grid gap-2">
      <span className="text-[14px] font-medium">{t("society.office.hair_label")}</span>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t("society.office.hair_label")}>
        {HAIR_STYLES.map(style => <button key={style} type="button" aria-pressed={hair === style} onClick={() => onChange(withHair(value, style))}
          className="cs-chip">
          {t(`society.office.hair_${style}`)}
        </button>)}
      </div>
    </div>
    <div className="grid grid-cols-2 gap-3">{EDITABLE_CELLS.map(cell => <label key={cell} className="flex min-h-11 items-center justify-between gap-2 rounded-2xl bg-secondary/45 py-1.5 pl-4 pr-2 text-[14px]">{t(`society.cell.${cell}`)}<input type="color" value={colors[cell]} onChange={e => setCell(cell, e.target.value)} className="h-8 w-8 cursor-pointer rounded-full border-0 bg-transparent p-0" /></label>)}</div>
  </fieldset>;
}

export function AgentAppearanceDialog({ agent, sample, onClose }: { agent: SocietyAgent; sample: boolean; onClose: () => void }) {
  const t = useT();
  const client = useQueryClient();
  const assistantName = useEventStore((s) => s.assistantName);
  const displayName = societyDisplayName(agent, assistantName);
  const [recipe, setRecipe] = useState<FigureRecipe>(() => ({ ...(agent.figure ?? defaultRecipe()), companion: resolveCompanion(agent.agentId, agent.figure?.companion) }));
  const [saved, setSaved] = useState(() => JSON.stringify(recipe));
  const [tab, setTab] = useState<"character" | "companion">("companion");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(false);
  const [discard, setDiscard] = useState(false);
  const opener = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  const dirty = JSON.stringify(recipe) !== saved;
  const close = () => { if (saving) return; if (dirty) setDiscard(true); else onClose(); };
  const save = async () => {
    setSaving(true); setError(false);
    try {
      const response = await fetch(`/api/society/agents/${encodeURIComponent(agent.agentId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ avatar: recipe }) });
      if (!response.ok) throw new Error(`appearance ${response.status}`);
      setSaved(JSON.stringify(recipe)); setDiscard(false);
      await Promise.all([client.invalidateQueries({ queryKey: ["society", "roster"] }), client.invalidateQueries({ queryKey: ["mars"] })]);
    } catch { setError(true); } // Keep the draft and display the recoverable failure.
    finally { setSaving(false); }
  };
  return <Dialog.Root open onOpenChange={open => { if (!open) close(); }}><Dialog.Portal>
    <Dialog.Overlay className="fixed inset-0 z-50 bg-scrim/60 backdrop-blur-sm" />
    <Dialog.Content data-testid="agent-appearance-dialog" onCloseAutoFocus={e => { e.preventDefault(); opener.current?.focus(); }} className="cs-sheet fixed left-1/2 top-1/2 z-50 flex max-h-[90dvh] w-[min(640px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden">
      <header className="cs-head"><div className="cs-head-row items-center"><AgentSwatch agent={{ ...agent, figure: recipe }} size={44} /><div className="min-w-0 flex-1"><Dialog.Title className="cs-title truncate">{displayName}</Dialog.Title><Dialog.Description className="cs-sub">{t("society.companion.appearance")}</Dialog.Description></div><button type="button" aria-label={t("society.card.close")} onClick={close} className="cs-close"><X size={16} aria-hidden /></button></div>
      <div className="cs-tabs" role="tablist" aria-label={t("society.companion.appearance")}>{(["character", "companion"] as const).map(value => <button key={value} type="button" role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className="cs-tab">{t(`society.companion.${value}`)}</button>)}</div></header>
      <div className="min-h-0 overflow-y-auto">{tab === "character" ? <CharacterEditor value={recipe} onChange={setRecipe} disabled={saving || sample} /> : <CompanionEditor value={resolveCompanion(agent.agentId, recipe.companion)} onChange={companion => setRecipe(r => ({ ...r, companion }))} disabled={saving || sample} lead={agent.tier === "lead"} agentId={agent.agentId} />}</div>
      <footer className="cs-foot">
        {error && <p role="alert" className="cs-hint w-full" data-tone="error">{t("society.profile_card.save_error")}</p>}
        {discard ? <><span className="cs-foot-note text-foreground" role="alert">{t("society.profile_card.unsaved")}</span><button type="button" className="cs-btn" data-variant="ghost" onClick={() => setDiscard(false)}>{t("society.profile_card.keep_editing")}</button><button type="button" className="cs-btn" data-variant="soft" onClick={onClose}>{t("society.profile_card.discard")}</button></> : <><button type="button" className="cs-btn" data-variant="ghost" onClick={close} disabled={saving}>{t("society.card.close")}</button><button type="button" className="cs-btn" data-variant="primary" onClick={() => void save()} disabled={!dirty || saving || sample}>{t(saving ? "society.card.saving" : "society.card.save")}</button></>}
      </footer>
    </Dialog.Content>
  </Dialog.Portal></Dialog.Root>;
}
