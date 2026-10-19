/**
 * The promotion moment. For the captain and the companion: a centred card
 * where the old insignia steps aside and the new one is laid on and catches
 * the light, then the rank, the level and what just opened. A level between
 * two ranks shows the insignia alone. For an android: a quiet toast in the
 * corner. Everything comes from the progression store (`banners`, `toasts`);
 * the fanfare itself is played by `useProgressionSync` when the award lands.
 *
 * A card goes on a click, Escape or after six seconds; a toast after five or
 * on a click. Reduced motion keeps every word and drops the movement.
 */
import { useEffect } from "react";
import { useReducedMotion } from "framer-motion";
import { useLocaleChunk } from "@/i18n";
import { useSocietyRoster } from "../../data";
import { useProgression, type Celebration } from "../../progression/progressionStore";
import { Insignia } from "./Insignia";
import { isPromotion } from "./levelModel";
import { fill, useLevelText } from "./levelText";
import { rankFor } from "./ranks";
import "./levels.css";

export const CEREMONY_MS = 6000;
export const TOAST_MS = 5000;
const MAX_VISIBLE_TOASTS = 3;

export function PromotionLayer() {
  useLocaleChunk("ship");
  const banner = useProgression((s) => s.banners[0]);
  const toasts = useProgression((s) => s.toasts);
  const reduced = !!useReducedMotion();
  const roster = useSocietyRoster();
  const agents = roster.data?.agents;
  const nameOf = (agentId: string) => agents?.find((a) => a.agentId === agentId)?.name ?? agentId;
  const companion = agents?.find((a) => a.tier === "lead")?.name ?? "Jarvis";
  if (!banner && toasts.length === 0) return null;
  return (
    <div className="promo-layer" data-reduced={reduced}>
      {banner && <Ceremony key={banner.id} party={banner} reduced={reduced} companion={companion} />}
      {toasts.length > 0 && (
        <div className="promo-toasts" role="status" aria-live="polite">
          {toasts.slice(-MAX_VISIBLE_TOASTS).map((toast) => <AgentToast key={toast.id} party={toast} name={nameOf(toast.subjectId.replace(/^agent:/, ""))} />)}
        </div>
      )}
    </div>
  );
}

function Ceremony({ party, reduced, companion }: { party: Celebration; reduced: boolean; companion: string }) {
  const text = useLevelText();
  const { t } = text;
  const dismiss = useProgression((s) => s.dismissBanner);
  const promoted = isPromotion(party.previousLevel, party.level);
  const before = rankFor(party.previousLevel), after = rankFor(party.level);

  useEffect(() => {
    const timer = setTimeout(dismiss, CEREMONY_MS);
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") dismiss(); };
    document.addEventListener("keydown", onKey);
    return () => { clearTimeout(timer); document.removeEventListener("keydown", onKey); };
  }, [dismiss]);

  const eyebrow = party.away ? t("ship.levels.promotion.away")
    : promoted ? t("ship.levels.promotion.promoted") : t("ship.levels.promotion.level_up");
  const who = party.kind === "pet" ? `${t("ship.levels.who.companion")} · ${companion}` : t("ship.levels.who.captain");

  return (
    <div className="promo-scrim" onClick={dismiss}>
      <section className="promo-card" data-promotion={promoted} role="status" aria-live="polite"
        aria-label={`${eyebrow}: ${text.rank(after.id)}, ${text.level(party.level)}`} onClick={(e) => e.stopPropagation()}>
        <div className="lv-eyebrow">{eyebrow}</div>
        <div className="promo-who">{who}</div>
        <div className="promo-stage" aria-hidden="true">
          {promoted && !reduced && <span className="promo-old"><Insignia rank={before.id} size={80} /></span>}
          <span className="promo-new"><Insignia rank={after.id} size={96} /></span>
        </div>
        <h2 className="promo-rank">{text.rank(after.id)}</h2>
        <div className="promo-level">{text.level(party.level)}</div>
        {party.unlocked.length > 0 && (
          <div className="promo-open">
            <div className="lv-eyebrow">{t("ship.levels.promotion.now_open")}</div>
            <p>{party.unlocked.map((id) => text.reward(id)).join(" · ")}</p>
          </div>
        )}
        <button type="button" onClick={dismiss}>{t("ship.levels.promotion.continue")}</button>
      </section>
    </div>
  );
}

function AgentToast({ party, name }: { party: Celebration; name: string }) {
  const text = useLevelText();
  const { t } = text;
  const dismiss = useProgression((s) => s.dismissToast);
  useEffect(() => {
    const timer = setTimeout(() => dismiss(party.id), TOAST_MS);
    return () => clearTimeout(timer);
  }, [dismiss, party.id]);
  const rank = rankFor(party.level);
  const line = isPromotion(party.previousLevel, party.level)
    ? fill(t("ship.levels.promotion.agent_promoted"), { agent: name, rank: text.rank(rank.id) })
    : fill(t("ship.levels.promotion.agent_level"), { agent: name, n: party.level });
  return (
    <button type="button" className="promo-toast" onClick={() => dismiss(party.id)}>
      <Insignia rank={rank.id} size={24} />
      <span>{line}</span>
    </button>
  );
}
