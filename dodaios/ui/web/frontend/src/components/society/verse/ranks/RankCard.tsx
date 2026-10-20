/**
 * The commander's rank card for the HUD: the rank plate, the rank, the level
 * and the bar to the next level, with how much is missing for the next rank.
 * A click opens the service record. The stage mounts it in its HUD slot.
 *
 * `compact` keeps the plate, the rank and the level on one line with a
 * hairline bar under it (for a narrow HUD); `onOpen` runs on the click as
 * well, after the record is opened.
 */
import { useLocaleChunk, useT } from "@/i18n";
import { useProgression } from "../../progression/progressionStore";
import { RankPlate } from "./RankPlate";
import { figure, fill } from "./rankModel";
import { useCommanderRank } from "./useRanks";
import "./ranks.css";

export interface RankCardProps {
  compact?: boolean;
  onOpen?: () => void;
  className?: string;
}

export function RankCard({ compact = false, onOpen, className }: RankCardProps) {
  useLocaleChunk("ship");
  const t = useT();
  const view = useCommanderRank();
  const openRecord = useProgression((s) => s.openRecord);
  const rank = t(`verse.ranks.rank.${view.rank.id}`);
  const tier = t(`verse.ranks.tier.${view.rank.tier}`);
  const next = view.next
    ? fill(t("verse.ranks.card.to_go"), { xp: figure(view.toNextRank), rank: t(`verse.ranks.rank.${view.next.id}`) })
    : t("verse.ranks.card.top");
  const label = `${t("verse.ranks.card.open")}: ${rank}, ${t("verse.ranks.card.level")} ${view.level}. ${next}`;
  return (
    <button
      type="button"
      className={`vr vr-panel vr-card${className ? ` ${className}` : ""}`}
      data-compact={compact}
      onClick={() => { openRecord("record"); onOpen?.(); }}
      aria-label={label}
      title={t("verse.ranks.card.open")}
      data-rank={view.rank.id}
    >
      <RankPlate rank={view.rank.id} size={compact ? 14 : 22} className="vr-card-plate" />
      <span className="vr-card-rank">{rank}</span>
      <span className="vr-card-meta">
        <span className="vr-caps">{t("verse.ranks.card.level")}</span>
        <span className="vr-num">{view.level}</span>
        {!compact && <span className="vr-caps vr-card-tier">{tier}</span>}
      </span>
      {compact ? (
        <span className="vr-card-foot" aria-hidden>
          <span className="vr-bar"><span style={{ width: `${(view.fraction * 100).toFixed(1)}%` }} /></span>
        </span>
      ) : <span className="vr-card-foot" aria-hidden>
        <span className="vr-bar"><span style={{ width: `${(view.fraction * 100).toFixed(1)}%` }} /></span>
        <span className="vr-card-next">
          <span className="vr-caps">{next}</span>
          {!view.atCap && <span className="vr-num">{figure(view.into)}/{figure(view.size)} {t("verse.ranks.card.xp")}</span>}
        </span>
      </span>}
    </button>
  );
}
