/**
 * The promotion moment, kept restrained.
 *
 * - The commander or the companion drone reaches a new rank: a notice under
 *   the top edge, the new plate whose tiles are laid on one by one, the rank,
 *   the level, one line of salute and whatever the quartermaster issued.
 *   Acknowledge, Escape or seven seconds close it; the focus is never taken.
 * - Any other level-up, and every officer's: a quiet line in the corner that
 *   goes after five seconds or on a click.
 *
 * Everything comes from the progression store (`banners`, `toasts`); the bell
 * itself rings in `useProgressionSync` when the award lands. Reduced motion
 * keeps every word and drops the movement.
 */
import { useEffect, useRef, useState } from "react";
import { useReducedMotion } from "framer-motion";
import { useLocaleChunk, useT } from "@/i18n";
import { rewardKey, slotOf, type RewardId } from "../../progression/levelCatalog";
import { PERSON_SUBJECT } from "../../progression/progressionApi";
import { useProgression, type Celebration } from "../../progression/progressionStore";
import { RankPlate } from "./RankPlate";
import { fill, type CrewMember } from "./rankModel";
import { isPromotion, plateTiles, rankForLevel } from "./ranks";
import "./ranks.css";

export const NOTICE_MS = 7000;
export const TOAST_MS = 5000;
/** Pause between two tiles being laid on. */
export const TILE_STEP_MS = 140;
const MAX_VISIBLE_TOASTS = 3;

export interface PromotionNoticeProps {
  crew?: readonly CrewMember[];
  companionName?: string;
}

/** True when the celebration earns the full notice (a new rank for the commander or the drone). */
export function isNotice(party: Celebration): boolean {
  return party.kind !== "agent" && isPromotion(party.previousLevel, party.level);
}

export function PromotionNotice({ crew = [], companionName }: PromotionNoticeProps) {
  useLocaleChunk("ship");
  const t = useT();
  const banner = useProgression((s) => s.banners[0]);
  const toasts = useProgression((s) => s.toasts);
  const dismissBanner = useProgression((s) => s.dismissBanner);
  const reduced = !!useReducedMotion();
  // A level-up without a new rank is a line in the corner, like an officer's.
  const quietBanner = banner && !isNotice(banner) ? banner : undefined;
  const notice = banner && isNotice(banner) ? banner : undefined;
  if (!banner && toasts.length === 0) return null;
  const nameOf = (party: Celebration): string => {
    if (party.subjectId === PERSON_SUBJECT) return "";
    if (party.kind === "pet") return companionName || t("verse.ranks.kind.pet");
    const id = party.subjectId.slice(party.subjectId.indexOf(":") + 1);
    return crew.find((m) => m.agentId === id)?.name ?? id;
  };
  const lines = [...(quietBanner ? [quietBanner] : []), ...toasts].slice(-MAX_VISIBLE_TOASTS);
  return (
    <div className="vr vr-notice-layer">
      {notice && <Notice key={notice.id} party={notice} reduced={reduced} onDone={dismissBanner} />}
      {lines.length > 0 && (
        <div className="vr-toasts" role="status" aria-live="polite">
          {lines.map((party) => (
            <Toast key={party.id} party={party} who={nameOf(party)} reduced={reduced}
              onDone={party === quietBanner ? dismissBanner : undefined} />
          ))}
        </div>
      )}
    </div>
  );
}

function issuedName(t: (key: string) => string, reward: RewardId): string {
  return slotOf(reward) === "uniform" ? t(`verse.ranks.uniform.${rewardKey(reward)}`) : t(`verse.ranks.ribbon.${reward}`);
}

function Notice({ party, reduced, onDone }: { party: Celebration; reduced: boolean; onDone: () => void }) {
  const t = useT();
  const rank = rankForLevel(party.level);
  const tiles = plateTiles(rank.id).lit.filter(Boolean).length;
  const [revealed, setRevealed] = useState(reduced ? tiles : 0);

  useEffect(() => {
    if (reduced) { setRevealed(tiles); return; }
    let shown = 0;
    const timer = setInterval(() => {
      shown += 1;
      setRevealed(shown);
      if (shown >= tiles) clearInterval(timer);
    }, TILE_STEP_MS);
    return () => clearInterval(timer);
  }, [reduced, tiles]);

  useEffect(() => {
    const timer = setTimeout(onDone, NOTICE_MS);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onDone(); };
    window.addEventListener("keydown", onKey);
    return () => { clearTimeout(timer); window.removeEventListener("keydown", onKey); };
  }, [onDone]);

  const rankName = t(`verse.ranks.rank.${rank.id}`);
  const drone = party.kind === "pet";
  const issued = party.unlocked.map((reward) => issuedName(t, reward)).join(", ");
  return (
    <section
      className="vr-panel vr-notice"
      role="status"
      aria-live="polite"
      aria-label={`${t(drone ? "verse.ranks.promo.eyebrow_drone" : "verse.ranks.promo.eyebrow")}: ${rankName}`}
      data-motion={!reduced}
      data-subject={party.subjectId}
    >
      <span className="vr-caps vr-notice-eyebrow">
        {party.away ? t("verse.ranks.promo.away") : t(drone ? "verse.ranks.promo.eyebrow_drone" : "verse.ranks.promo.eyebrow")}
      </span>
      <RankPlate rank={rank.id} size={44} revealed={revealed} />
      <p className="vr-notice-rank">{rankName}</p>
      <span className="vr-caps">
        {fill(t("verse.ranks.promo.level_up"), { level: party.level })} · {t(`verse.ranks.tier.${rank.tier}`)}
      </span>
      <p className="vr-notice-line">{drone ? t("verse.ranks.promo.salute_drone") : t(`verse.ranks.promo.salute.${rank.tier}`)}</p>
      {issued && <p className="vr-notice-issued">{fill(t("verse.ranks.promo.issued"), { what: issued })}</p>}
      <button type="button" className="vr-btn" data-primary="true" onClick={onDone}>{t("verse.ranks.promo.acknowledge")}</button>
    </section>
  );
}

function Toast({ party, who, reduced, onDone }: { party: Celebration; who: string; reduced: boolean; onDone?: () => void }) {
  const t = useT();
  const dismissToast = useProgression((s) => s.dismissToast);
  const done = onDone ?? (() => dismissToast(party.id));
  // `done` is rebuilt every render; the timer belongs to the toast, so it reads the latest through a ref.
  const doneRef = useRef(done);
  doneRef.current = done;
  useEffect(() => {
    const timer = setTimeout(() => doneRef.current(), TOAST_MS);
    return () => clearTimeout(timer);
  }, [party.id]);
  const rank = rankForLevel(party.level);
  const name = who || t("verse.ranks.promo.you");
  const promoted = isPromotion(party.previousLevel, party.level);
  const text = promoted
    ? fill(t("verse.ranks.promo.toast_promoted"), { who: name, rank: t(`verse.ranks.rank.${rank.id}`) })
    : fill(t("verse.ranks.promo.toast_level"), { who: name, level: party.level });
  return (
    <button type="button" className="vr-panel vr-toast" onClick={done} data-motion={!reduced} data-subject={party.subjectId}>
      <RankPlate rank={rank.id} size={14} />
      <span>{text}</span>
    </button>
  );
}
