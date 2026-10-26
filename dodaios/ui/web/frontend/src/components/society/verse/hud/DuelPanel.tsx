/**
 * The duel's start panel: what the duel is, the three opponents (normal,
 * hard, elite) and the controls. Choosing an opponent starts the match at
 * once (riding the turbolift down to Reactor Engineering first when the
 * commander is elsewhere).
 */
import { useRef } from "react";
import { DUEL_DIFFICULTIES, type DuelDifficulty } from "../duel/duelController";
import { VerseDialog } from "./VerseDialog";
import "./duel.css";

interface Props {
  t: (key: string) => string;
  /** The commander is on another deck: the lift ride comes first. */
  ride: boolean;
  /** The difficulty chosen last time (focused first). */
  last: DuelDifficulty;
  onStart: (difficulty: DuelDifficulty) => void;
  onClose: () => void;
}

/** The controls as [key label, action] pairs; key labels are i18n keys when they start with "verse.". */
export const DUEL_CONTROLS: readonly (readonly [string, string])[] = [
  ["W A S D", "verse.duel.controls.move"],
  ["verse.duel.controls.shift", "verse.duel.controls.sprint"],
  ["verse.duel.controls.lmb", "verse.duel.controls.fire"],
  ["verse.duel.controls.rmb", "verse.duel.controls.ads"],
  ["Q", "verse.duel.controls.shield"],
  ["verse.duel.controls.space", "verse.duel.controls.dodge"],
  ["R", "verse.duel.controls.vent"],
  ["verse.duel.controls.esc", "verse.duel.controls.pause"],
];

export function DuelPanel({ t, ride, last, onStart, onClose }: Props) {
  const first = useRef<HTMLButtonElement>(null);
  return (
    <VerseDialog title={t("verse.duel.title")} closeLabel={t("verse.card.close")} onClose={onClose} initialFocus={first} className="verse-duel-panel">
      <p className="verse-duel-intro">{t("verse.duel.intro")}{ride ? ` ${t("verse.duel.ride")}` : ""}</p>
      <div className="verse-duel-section verse-label">{t("verse.duel.choose")}</div>
      {DUEL_DIFFICULTIES.map((d, i) => (
        <button
          key={d}
          ref={d === last ? first : undefined}
          type="button"
          className="verse-lift-row verse-duel-tier"
          data-tier={d}
          onClick={() => onStart(d)}
        >
          <b>{String(i + 1).padStart(2, "0")}</b>
          <span className="verse-lift-name">
            <span>{t(`verse.duel.difficulty.${d}`)}</span>
            <small>{t(`verse.duel.difficulty.${d}_about`)}</small>
          </span>
          <span className="verse-duel-pips" aria-hidden>{[0, 1, 2].map((k) => <i key={k} data-on={k <= i} />)}</span>
        </button>
      ))}
      <div className="verse-duel-section verse-label">{t("verse.duel.controls.title")}</div>
      <dl className="verse-duel-keys">
        {DUEL_CONTROLS.map(([key, action]) => (
          <div key={action}>
            <dt><kbd className="verse-key">{key.startsWith("verse.") ? t(key) : key}</kbd></dt>
            <dd>{t(action)}</dd>
          </div>
        ))}
      </dl>
    </VerseDialog>
  );
}
