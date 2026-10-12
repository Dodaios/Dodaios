import { useState } from "react";
import { Dices } from "lucide-react";
import { useT } from "@/i18n";
import {
  CREATURE_EYES, CREATURE_PALETTES, CREATURE_SEED_MAX, CREATURE_STATES, type CreatureLook, type CreatureState,
} from "./creature";
import { PixelCreature } from "./PixelCreature";

const CHOICES = 8;
const rollSeed = () => Math.floor(Math.random() * (CREATURE_SEED_MAX + 1));
const chip = (on: boolean) => `rounded-full border px-2.5 py-1 text-xs ${on ? "border-transparent bg-primary text-primary-foreground" : "border-border bg-background text-foreground hover:bg-secondary"}`;

/**
 * Everything a pixel creature has to choose: one of eight rolled figures, a
 * colour world and an eye kind. The state row only previews what the
 * creature acts out; it is never saved.
 */
export function CreaturePicker({ value, onChange, mood, onMood }: {
  value: CreatureLook; onChange: (next: CreatureLook) => void;
  mood: CreatureState; onMood: (mood: CreatureState) => void;
}) {
  const t = useT();
  // The worn figure leads the first row, so opening the dialog never loses it.
  const [seeds, setSeeds] = useState(() => [value.seed, ...Array.from({ length: CHOICES - 1 }, rollSeed)]);
  return <div className="flex flex-col gap-5" data-testid="creature-picker">
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="text-sm font-medium">{t("society.companion.creature.figure")}</span>
        <button type="button" onClick={() => setSeeds(Array.from({ length: CHOICES }, rollSeed))}
          className="inline-flex items-center gap-1.5 rounded-full border border-border bg-background px-2.5 py-1 text-xs text-foreground hover:bg-secondary">
          <Dices size={14} aria-hidden />{t("society.companion.creature.roll")}
        </button>
      </div>
      <div className="flex flex-wrap gap-2">{seeds.map((seed, index) => <button key={`${index}-${seed}`} type="button"
        aria-label={t("society.companion.creature.number").replace("{0}", String(seed))} aria-pressed={value.seed === seed} onClick={() => onChange({ ...value, seed })}
        className={`grid h-14 w-14 place-items-center rounded-lg border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${value.seed === seed ? "border-foreground bg-secondary" : "border-border hover:bg-secondary"}`}>
        <PixelCreature creature={{ ...value, seed }} size={40} />
      </button>)}</div>
    </div>
    <div>
      <span className="mb-2 block text-sm font-medium">{t("society.companion.creature.palette")}</span>
      <div className="flex flex-wrap gap-2">{CREATURE_PALETTES.map(palette => <button key={palette.id} type="button"
        aria-label={t(`society.companion.creature.palettes.${palette.id}`)} title={t(`society.companion.creature.palettes.${palette.id}`)}
        aria-pressed={value.palette === palette.id} onClick={() => onChange({ ...value, palette: palette.id })}
        className={`h-9 w-9 rounded-full border border-border ring-offset-2 ring-offset-popover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${value.palette === palette.id ? "ring-2 ring-foreground" : ""}`}
        style={{ background: `linear-gradient(180deg, ${palette.colors.join(", ")})` }} />)}</div>
    </div>
    <div className="flex items-center justify-between gap-3 text-sm"><span>{t("society.companion.eyes")}</span>
      <div className="flex flex-wrap justify-end gap-1.5" role="group" aria-label={t("society.companion.eyes")}>
        {CREATURE_EYES.map(eyes => <button key={eyes} type="button" aria-pressed={value.eyes === eyes} onClick={() => onChange({ ...value, eyes })} className={chip(value.eyes === eyes)}>
          {t(`society.companion.creature.eye_kinds.${eyes}`)}
        </button>)}
      </div>
    </div>
    <div>
      <span className="mb-1 block text-sm font-medium">{t("society.companion.creature.states")}</span>
      <p className="mb-2 text-xs text-muted-foreground">{t("society.companion.creature.states_hint")}</p>
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("society.companion.creature.states")}>
        {CREATURE_STATES.map(state => <button key={state} type="button" aria-pressed={mood === state} onClick={() => onMood(state)} className={chip(mood === state)}>
          {t(`society.companion.creature.state_names.${state}`)}
        </button>)}
      </div>
    </div>
  </div>;
}
