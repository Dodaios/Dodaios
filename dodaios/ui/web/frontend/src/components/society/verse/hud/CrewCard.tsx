/**
 * The record of the selected crew member, bottom left: name, rank plate and
 * rank, duty status, where they are posted right now, and what the commander
 * can do (open their chat or terminal, bring the camera to them, walk over).
 */
import { RankPlate, type RankId } from "../ranks";

export interface CrewCardInfo {
  id: string;
  name: string;
  rankId: RankId;
  rank: string;
  status: string;
  statusKey: string;
  post: string;
  accent: string | null;
  technician: boolean;
  /** On this deck right now (the camera can go to them). */
  here: boolean;
}

interface Props {
  info: CrewCardInfo;
  t: (key: string) => string;
  onOpen: () => void;
  onShow: () => void;
  onWalk: () => void;
  onClose: () => void;
}

export function CrewCard({ info, t, onOpen, onShow, onWalk, onClose }: Props) {
  return (
    <section className="verse-panel verse-card" aria-label={info.name} style={info.accent ? { borderLeft: `2px solid ${info.accent}` } : undefined}>
      <div className="verse-card-head">
        <div>
          <div className="verse-label">{info.technician ? t("verse.post.terminal") : info.rank}</div>
          <div className="verse-card-name">{info.name}</div>
        </div>
        <button type="button" className="verse-close" aria-label={t("verse.card.close")} onClick={onClose}>
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden><path d="M1 1l8 8M9 1l-8 8" stroke="currentColor" strokeWidth="1.2" /></svg>
        </button>
      </div>
      <div className="verse-card-rows">
        <span className="verse-label">{t("verse.card.rank")}</span>
        <span className="verse-card-value" style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <RankPlate rank={info.rankId} size={22} />
          {info.rank}
        </span>
        <span className="verse-label">{t("verse.card.status")}</span>
        <span className="verse-card-value" style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
          <i className="verse-dot" data-state={info.statusKey} />
          {info.status}
        </span>
        <span className="verse-label">{t("verse.card.post")}</span>
        <span className="verse-card-value">{info.post}</span>
      </div>
      <div className="verse-card-actions">
        <button type="button" className="verse-btn" data-primary="true" onClick={onOpen}>
          {info.technician ? t("verse.card.open_pane") : t("verse.card.open")}
        </button>
        {info.here && <button type="button" className="verse-btn" onClick={onShow}>{t("verse.card.show")}</button>}
        {info.here && <button type="button" className="verse-btn" onClick={onWalk}>{t("verse.card.walk")}</button>}
      </div>
    </section>
  );
}
