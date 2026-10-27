import { useState } from "react";
import { useT } from "@/i18n";
import {
  CREATURE_EYES, CREATURE_PALETTES, CREATURE_SEED_MAX, CREATURE_STATES, randomCreature, type CreatureLook, type CreatureState,
} from "./creature";
import { PixelCreature } from "./PixelCreature";
import { SegmentedChoice } from "./SegmentedChoice";
import "../calmSheet.css";

const CHOICES = 8;
const rollSeed = () => Math.floor(Math.random() * (CREATURE_SEED_MAX + 1));

/**
 * Everything a pixel creature has to choose: one of eight rolled figures, a
 * colour world and an eye kind. "Roll again" rolls all three at once and
 * wears the result, so one click gives a whole new creature; the rows below
 * fine-tune it. The state row only previews what the creature acts out; it
 * is never saved.
 */
export function CreaturePicker({ value, onChange, mood, onMood }: {
  value: CreatureLook; onChange: (next: CreatureLook) => void;
  mood: CreatureState; onMood: (mood: CreatureState) => void;
}) {
  const t = useT();
  // The worn figure leads the first row, so opening the dialog never loses it.
  const [seeds, setSeeds] = useState(() => [value.seed, ...Array.from({ length: CHOICES - 1 }, rollSeed)]);
  const roll = () => {
    // Always another colour world, so a roll is never mistaken for a reshuffle of the same figure.
    let next = randomCreature();
    for (let tries = 0; next.palette === value.palette && tries < 8; tries++) next = randomCreature();
    setSeeds([next.seed, ...Array.from({ length: CHOICES - 1 }, rollSeed)]);
    onChange(next);
  };
  return <div className="flex flex-col gap-5" data-testid="creature-picker">
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-[14px] font-medium">{t("society.companion.creature.figure")}</span>
        <button type="button" onClick={roll} className="cs-btn" data-variant="soft" data-size="sm">
          {t("society.companion.creature.roll")}
        </button>
      </div>
      <div className="flex flex-wrap gap-2">{seeds.map((seed, index) => <button key={`${index}-${seed}`} type="button"
        aria-label={t("society.companion.creature.number").replace("{0}", String(seed))} aria-pressed={value.seed === seed} onClick={() => onChange({ ...value, seed })}
        className="calm-tile h-14 w-14" data-on={value.seed === seed}>
        <PixelCreature creature={{ ...value, seed }} size={40} />
      </button>)}</div>
    </div>
    <div>
      <span className="mb-2 block text-[14px] font-medium">{t("society.companion.creature.palette")}</span>
      <div className="flex flex-wrap gap-2">{CREATURE_PALETTES.map(palette => <button key={palette.id} type="button"
        aria-label={t(`society.companion.creature.palettes.${palette.id}`)} title={t(`society.companion.creature.palettes.${palette.id}`)}
        aria-pressed={value.palette === palette.id} onClick={() => onChange({ ...value, palette: palette.id })}
        className={`h-9 w-9 rounded-full shadow-[inset_0_0_0_1px_hsl(var(--border)/0.6)] ring-offset-2 ring-offset-popover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${value.palette === palette.id ? "ring-2 ring-foreground" : ""}`}
        style={{ background: `linear-gradient(180deg, ${palette.colors.join(", ")})` }} />)}</div>
    </div>
    <div className="flex flex-col gap-2"><span className="text-[14px] font-medium">{t("society.companion.eyes")}</span>
      <SegmentedChoice label={t("society.companion.eyes")} value={value.eyes} onChange={eyes => onChange({ ...value, eyes })}
        options={CREATURE_EYES.map(id => ({ id, label: t(`society.companion.creature.eye_kinds.${id}`) }))} />
    </div>
    <div>
      <span className="mb-1 block text-[14px] font-medium">{t("society.companion.creature.states")}</span>
      <p className="mb-2 text-[13px] text-muted-foreground">{t("society.companion.creature.states_hint")}</p>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t("society.companion.creature.states")}>
        {CREATURE_STATES.map(state => <button key={state} type="button" aria-pressed={mood === state} onClick={() => onMood(state)} className="cs-chip">
          {t(`society.companion.creature.state_names.${state}`)}
        </button>)}
      </div>
    </div>
  </div>;
}
