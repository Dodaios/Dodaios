/**
 * The turbolift: the decks top to bottom, the current one marked; choosing
 * another closes the doors and opens them on that deck.
 */
import { useRef } from "react";
import { DECK_IDS, deckNumber, type DeckId } from "../decks";
import { VerseDialog } from "./VerseDialog";

interface Props {
  current: DeckId;
  t: (key: string) => string;
  onRide: (deck: DeckId) => void;
  onClose: () => void;
}

export function LiftPanel({ current, t, onRide, onClose }: Props) {
  const here = useRef<HTMLButtonElement>(null);
  return (
    <VerseDialog title={t("verse.lift.title")} closeLabel={t("verse.card.close")} onClose={onClose} initialFocus={here}>
      {DECK_IDS.map((id) => (
        <button
          key={id}
          ref={id === current ? here : undefined}
          type="button"
          className="verse-lift-row"
          aria-current={id === current}
          onClick={() => (id === current ? onClose() : onRide(id))}
        >
          <b>{String(deckNumber(id)).padStart(2, "0")}</b>
          <span className="verse-lift-name">
            <span>{t(`verse.deck.${id}`)}</span>
            <small>{t(`verse.deck.${id}_about`)}</small>
          </span>
          {id === current && <span className="verse-label">{t("verse.lift.here")}</span>}
        </button>
      ))}
    </VerseDialog>
  );
}
