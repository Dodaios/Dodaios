/**
 * The quartermaster: the captain's suit. Docked at the side, so the captain
 * stays in view and every change shows on the figure at once. Suit colour,
 * trim and visor are free choices; the cuts beyond the duty suit open with
 * rank (the level system's `suit` rewards) and say at which level.
 */
import { useEffect, useRef } from "react";
import { useProgression } from "../../../progression/progressionStore";
import type { SuitChoice } from "../../../progression/cosmetics";
import { useShip, type CaptainLook } from "../../shipStore";
import type { DeckPanelProps } from "../registry";
import "./quartermaster.css";

const SUITS = ["#2c3340", "#1c2a4a", "#4a1d26", "#20372d", "#6e6248", "#3b3f46"] as const;
const TRIMS = ["#d9a441", "#c9cdd3", "#5fd4ff", "#e04a5a"] as const;
const VISORS = ["#d6a440", "#b9c3cc", "#3c7fd0", "#1d2026"] as const;


export function QuartermasterPanel({ actions }: DeckPanelProps) {
  const { t } = actions;
  const look = useShip((s) => s.captainLook);
  const level = useProgression((s) => s.subjects.person?.level ?? 1);
  const choice = useProgression((s) => s.suit);
  const rewards = useProgression((s) => s.snapshot?.rewards);
  // Automatic (the finest open), the duty suit, then every suit the rulebook lists, lowest first.
  const cuts: { id: SuitChoice; level: number }[] = [
    { id: "auto", level: 1 }, { id: "none", level: 1 },
    ...(rewards ?? []).filter((r) => r.slot === "suit").map((r) => ({ id: r.rewardId as SuitChoice, level: r.levels.person ?? 99 })).sort((a, b) => a.level - b.level),
  ];
  const set = (patch: Partial<CaptainLook>) => useShip.getState().setCaptainLook({ ...look, ...patch });
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  const swatches = (key: "suit" | "trim" | "visor", list: readonly string[], label: string) => (
    <fieldset className="qm-row">
      <legend className="ship-eyebrow">{label}</legend>
      <div className="qm-swatches" role="radiogroup" aria-label={label}>
        {list.map((c, i) => (
          <button key={c} ref={key === "suit" && i === 0 ? first : undefined} type="button" role="radio" aria-checked={look[key] === c}
            className="qm-swatch" style={{ background: c }} aria-label={`${label} ${i + 1}`} onClick={() => set({ [key]: c })} />
        ))}
      </div>
    </fieldset>
  );
  return (
    <aside className="ship-panel qm-panel" role="dialog" aria-label={t("ship.ops.quartermaster.title")}
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); actions.closePanel(); } }}>
      <header className="qm-head">
        <div>
          <div className="ship-eyebrow">{t("ship.station.quartermaster.name")}</div>
          <h2>{t("ship.ops.quartermaster.title")}</h2>
        </div>
        <button type="button" className="ship-tool" aria-label={t("ship.close")} onClick={actions.closePanel}>✕</button>
      </header>
      <fieldset className="qm-row">
        <legend className="ship-eyebrow">{t("ship.ops.quartermaster.cut")}</legend>
        <div className="qm-cuts">
          {cuts.map((cut) => {
            const open = level >= cut.level;
            const key = cut.id === "none" ? "duty" : cut.id.replace(/^suit_/, "");
            return (
              <button key={cut.id} type="button" className="qm-cut" aria-pressed={choice === cut.id} disabled={!open}
                onClick={() => useProgression.getState().chooseSuit(cut.id)}>
                <span>{t(`ship.ops.quartermaster.cuts.${key}`)}</span>
                <small>{open ? t("ship.ops.quartermaster.open") : t("ship.ops.quartermaster.at_level").replace("{n}", String(cut.level))}</small>
              </button>
            );
          })}
        </div>
      </fieldset>
      {swatches("suit", SUITS, t("ship.ops.quartermaster.suit"))}
      {swatches("trim", TRIMS, t("ship.ops.quartermaster.trim"))}
      {swatches("visor", VISORS, t("ship.ops.quartermaster.visor"))}
      <p className="qm-note">{t("ship.ops.quartermaster.note")}</p>
    </aside>
  );
}
