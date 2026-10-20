/**
 * The service record: an accessible dialog with five pages.
 *
 * - Record: the commander's plate, rank, level, XP, the next rank and what is
 *   still missing, the ribbons held, the log of recent awards, the bell.
 * - Ladder: every rank by tier; held ranks plain, the current one marked in
 *   red, the ones ahead dimmed with the XP still missing.
 * - Quartermaster: the uniforms issued by tier (the commander picks one, or
 *   the highest issued) and the ribbons with the levels that open them.
 * - How to earn: every rule the running server pays, in words, with limits.
 * - Crew: every officer's rank, highest first, and the companion drone.
 *
 * Open and page come from the progression store (`record`); the stage opens
 * it from the rank card, the records hall or the quartermaster.
 */
import * as Dialog from "@radix-ui/react-dialog";
import * as Tabs from "@radix-ui/react-tabs";
import { useMemo } from "react";
import { useLocaleChunk, useT, useUiLanguage } from "@/i18n";
import { issuedUniforms, unlockedFor, xpUntilLevel, type UniformChoice } from "../../progression/cosmetics";
import { rewardKey, type RibbonId, type SubjectKind } from "../../progression/levelCatalog";
import { useLevelSound } from "../../progression/levelSounds";
import { PERSON_SUBJECT, petSubject, rewardsOf, type RewardRow } from "../../progression/progressionApi";
import { SERVICE_TABS, useProgression, type ServiceTab } from "../../progression/progressionStore";
import { RankPlate } from "./RankPlate";
import { Ribbon } from "./Ribbon";
import { cooldownText, crewRows, figure, fill, logOf, rankView, rulesByKind, sourceKey, type CrewMember, type RankView } from "./rankModel";
import { RANK_TIERS, RANKS, TIER_STYLE, UNIFORM_CLOTH, tierStart, type RankTier, type UniformId } from "./ranks";
import "./ranks.css";

export interface ServiceRecordProps {
  /** The officers aboard (the roster without the lead). */
  crew?: readonly CrewMember[];
  /** What the companion drone is called; the generic word without one. */
  companionName?: string;
}

export function ServiceRecord({ crew = [], companionName }: ServiceRecordProps) {
  useLocaleChunk("ship");
  const t = useT();
  const tab = useProgression((s) => s.record);
  const openRecord = useProgression((s) => s.openRecord);
  const open = tab !== null;
  return (
    <Dialog.Root open={open} onOpenChange={(next) => { if (!next) openRecord(null); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="vr vr-scrim" />
        <Dialog.Content className="vr vr-panel vr-record" aria-describedby={undefined}>
          <header className="vr-record-head">
            <Dialog.Title className="vr-record-title">{t("verse.ranks.record.title")}</Dialog.Title>
            <Dialog.Close className="vr-x" aria-label={t("verse.ranks.record.close")}>
              <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden><path d="M1 1L11 11M11 1L1 11" stroke="currentColor" strokeWidth="1.2" /></svg>
            </Dialog.Close>
          </header>
          {open && (
            <Tabs.Root value={tab} onValueChange={(value) => openRecord(value as ServiceTab)} className="vr-tabs-root" style={{ display: "contents" }}>
              <Tabs.List className="vr-tabs" aria-label={t("verse.ranks.record.title")}>
                {SERVICE_TABS.map((id) => (
                  <Tabs.Trigger key={id} value={id} className="vr-tab">{t(`verse.ranks.record.tabs.${id}`)}</Tabs.Trigger>
                ))}
              </Tabs.List>
              <Tabs.Content value="record" className="vr-pane"><RecordPage /></Tabs.Content>
              <Tabs.Content value="ladder" className="vr-pane"><LadderPage /></Tabs.Content>
              <Tabs.Content value="rewards" className="vr-pane"><QuartermasterPage /></Tabs.Content>
              <Tabs.Content value="earn" className="vr-pane"><EarnPage /></Tabs.Content>
              <Tabs.Content value="crew" className="vr-pane"><CrewPage crew={crew} companionName={companionName} /></Tabs.Content>
            </Tabs.Root>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function useCommander(): { view: RankView; rewards: readonly RewardRow[] } {
  const subject = useProgression((s) => s.subjects[PERSON_SUBJECT]);
  const snapshot = useProgression((s) => s.snapshot);
  return useMemo(() => ({ view: rankView(subject, snapshot?.levelXp), rewards: rewardsOf(snapshot) }), [subject, snapshot]);
}

function RecordPage() {
  const t = useT();
  const { view, rewards } = useCommander();
  const recent = useProgression((s) => s.snapshot?.recent);
  const sound = useLevelSound();
  const lang = useUiLanguage();
  const ribbons = unlockedFor(rewards, "person", view.level).filter((r) => r.slot === "ribbon");
  const log = useMemo(() => logOf(recent ?? [], PERSON_SUBJECT), [recent]);
  const rank = t(`verse.ranks.rank.${view.rank.id}`);
  return (
    <>
      <div className="vr-ident">
        <RankPlate rank={view.rank.id} size={40} label={rank} />
        <div>
          <span className="vr-caps">{t("verse.ranks.record.rank")} · {t(`verse.ranks.tier.${view.rank.tier}`)}</span>
          <p className="vr-ident-rank">{rank}</p>
        </div>
      </div>
      <div className="vr-facts">
        <div className="vr-fact"><span className="vr-caps">{t("verse.ranks.record.level")}</span><span className="vr-num">{view.level}</span></div>
        <div className="vr-fact"><span className="vr-caps">{t("verse.ranks.record.total_xp")}</span><span className="vr-num">{figure(view.xp)}</span></div>
        <div className="vr-fact">
          <span className="vr-caps">{t("verse.ranks.record.this_level")}</span>
          <span className="vr-num">{view.atCap ? "—" : `${figure(view.into)} / ${figure(view.size)}`}</span>
        </div>
        <div className="vr-fact">
          <span className="vr-caps">{t("verse.ranks.record.next_rank")}</span>
          {view.next
            ? <span className="vr-num" title={t(`verse.ranks.rank.${view.next.id}`)}>{fill(t("verse.ranks.record.xp_ahead"), { xp: figure(view.toNextRank) })}</span>
            : <span className="vr-num">—</span>}
          <small className="vr-caps">{view.next ? t(`verse.ranks.rank.${view.next.id}`) : t("verse.ranks.record.top_rank")}</small>
        </div>
      </div>
      <div className="vr-bar" aria-hidden><span style={{ width: `${(view.fraction * 100).toFixed(1)}%` }} /></div>
      <section className="vr-section">
        <h3 className="vr-caps">{t("verse.ranks.record.ribbons")}</h3>
        {ribbons.length > 0
          ? <div className="vr-ribbons">{ribbons.map((r) => <Ribbon key={r.rewardId} ribbon={r.rewardId as RibbonId} height={14} label={t(`verse.ranks.ribbon.${r.rewardId}`)} />)}</div>
          : <p className="vr-hint">{t("verse.ranks.record.no_ribbons")}</p>}
      </section>
      <section className="vr-section">
        <h3 className="vr-caps">{t("verse.ranks.record.log")}</h3>
        {log.length === 0 ? <p className="vr-hint">{t("verse.ranks.record.log_empty")}</p> : (
          <ul className="vr-log">
            {log.map((row) => (
              <li key={row.seq}>
                <span>{t(sourceKey(row.source))}</span>
                <span className="vr-num">{row.tsMs ? new Date(row.tsMs).toLocaleString(lang, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}</span>
                <span className="vr-num vr-xp">+{row.xp}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <label className="vr-toggle">
        <input type="checkbox" checked={sound.on} onChange={(e) => sound.set(e.target.checked)} />
        {t("verse.ranks.record.sound")}
      </label>
    </>
  );
}

function LadderPage() {
  const t = useT();
  const { view } = useCommander();
  const levelXp = useProgression((s) => s.snapshot?.levelXp);
  return (
    <>
      {RANK_TIERS.map((tier) => (
        <section key={tier} className="vr-tier" aria-label={t(`verse.ranks.tier.${tier}`)}>
          <div className="vr-tier-head">
            <span className="vr-caps" style={{ color: "var(--vr-text)" }}>{t(`verse.ranks.tier.${tier}`)}</span>
            <span className="vr-caps">{fill(t("verse.ranks.record.from_level"), { level: tierStart(tier) })}</span>
          </div>
          {RANKS.filter((rank) => rank.tier === tier).map((rank) => {
            const state = rank.id === view.rank.id ? "current" : rank.level <= view.level ? "held" : "ahead";
            const gap = state === "ahead" ? xpUntilLevel(levelXp ?? [], view.xp, rank.level) : 0;
            return (
              <div key={rank.id} className="vr-step" data-state={state} aria-current={state === "current" ? "step" : undefined}>
                <RankPlate rank={rank.id} size={18} />
                <span>
                  <span className="vr-step-name">{t(`verse.ranks.rank.${rank.id}`)}</span>
                  {state !== "ahead" && <span className="vr-caps" style={{ marginLeft: 10 }}>{t(state === "current" ? "verse.ranks.record.current" : "verse.ranks.record.held")}</span>}
                </span>
                <span className="vr-num">
                  {state === "ahead" ? fill(t("verse.ranks.record.xp_ahead"), { xp: figure(gap) }) : fill(t("verse.ranks.record.from_level"), { level: rank.level })}
                </span>
              </div>
            );
          })}
        </section>
      ))}
    </>
  );
}

function QuartermasterPage() {
  const t = useT();
  const { view, rewards } = useCommander();
  const choice = useProgression((s) => s.uniform);
  const choose = useProgression((s) => s.chooseUniform);
  const issued = issuedUniforms(rewards, view.level);
  const ribbons = rewards.filter((r) => r.slot === "ribbon");
  const options: UniformChoice[] = ["auto", ...RANK_TIERS];
  return (
    <>
      <section className="vr-section">
        <h3 className="vr-caps">{t("verse.ranks.record.uniforms")}</h3>
        <p className="vr-hint">{t("verse.ranks.record.uniforms_hint")}</p>
        <div className="vr-choices" role="radiogroup" aria-label={t("verse.ranks.record.uniforms")}>
          {options.map((option) => {
            const isAuto = option === "auto";
            const tier = (isAuto ? issued[issued.length - 1] ?? "deck" : option) as RankTier;
            const open = isAuto || issued.includes(option as UniformId);
            const opensAt = uniformLevel(rewards, tier);
            return (
              <button
                key={option}
                type="button"
                role="radio"
                aria-checked={choice === option}
                className="vr-choice"
                disabled={!open}
                onClick={() => choose(option)}
                data-uniform={option}
              >
                <span className="vr-swatch" aria-hidden><i style={{ background: UNIFORM_CLOTH[tier] }} /><i style={{ background: TIER_STYLE[tier].tile }} /></span>
                <span className="vr-choice-name">{isAuto ? t("verse.ranks.record.auto") : t(`verse.ranks.uniform.${option}`)}</span>
                <small>
                  {isAuto
                    ? t("verse.ranks.record.auto_hint")
                    : open ? t(`verse.ranks.uniform_note.${option}`) : fill(t("verse.ranks.record.opens_at"), { level: opensAt })}
                </small>
                <span className="vr-caps">{choice === option ? t("verse.ranks.record.wearing") : open && !isAuto ? t("verse.ranks.record.issued") : " "}</span>
              </button>
            );
          })}
        </div>
      </section>
      <hr className="vr-rule" />
      <section className="vr-section">
        <h3 className="vr-caps">{t("verse.ranks.record.ribbons")}</h3>
        <p className="vr-hint">{t("verse.ranks.record.ribbons_hint")}</p>
        <ul className="vr-awards">
          {ribbons.map((r) => {
            const open = (r.levels.person ?? Infinity) <= view.level;
            return (
              <li key={r.rewardId} data-open={open}>
                <Ribbon ribbon={r.rewardId as RibbonId} height={12} />
                <span>
                  <strong>{t(`verse.ranks.ribbon.${r.rewardId}`)}</strong>
                  <p>{t(`verse.ranks.ribbon_note.${r.rewardId}`)}</p>
                </span>
                <span className="vr-num">
                  {r.levels.person !== null && <>{fill(t("verse.ranks.record.for_you"), { level: r.levels.person })}<br /></>}
                  {r.levels.agent !== null && fill(t("verse.ranks.record.for_crew"), { level: r.levels.agent })}
                </span>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}

function uniformLevel(rewards: readonly RewardRow[], tier: RankTier): number {
  const row = rewards.find((r) => r.slot === "uniform" && rewardKey(r.rewardId) === tier);
  return row?.levels.person ?? tierStart(tier);
}

const EARN_KINDS: readonly SubjectKind[] = ["person", "agent", "pet"];

function EarnPage() {
  const t = useT();
  const rules = useProgression((s) => s.snapshot?.rules);
  const grouped = useMemo(() => rulesByKind(rules ?? []), [rules]);
  return (
    <>
      <p className="vr-hint">{t("verse.ranks.record.earn_hint")}</p>
      {EARN_KINDS.map((kind) => grouped[kind].length > 0 && (
        <section key={kind} className="vr-section">
          <h3 className="vr-caps">{t(`verse.ranks.record.earn_${kind}`)}</h3>
          <ul className="vr-rules">
            {grouped[kind].map((rule) => {
              const limits = [
                rule.dailyCap > 0 ? fill(t("verse.ranks.limit.per_day"), { xp: rule.dailyCap }) : "",
                rule.cooldownS > 0 ? fill(t("verse.ranks.limit.cooldown"), { time: cooldownText(rule.cooldownS) }) : "",
              ].filter(Boolean).join(" · ");
              return (
                <li key={rule.source} data-source={rule.source}>
                  <span>{t(`verse.ranks.rule.${rule.source}`)}{limits && <small>{limits}</small>}</span>
                  <span className="vr-num">+{rule.xp}</span>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </>
  );
}

function CrewPage({ crew, companionName }: Required<Pick<ServiceRecordProps, "crew">> & Pick<ServiceRecordProps, "companionName">) {
  const t = useT();
  const subjects = useProgression((s) => s.subjects);
  const levelXp = useProgression((s) => s.snapshot?.levelXp);
  const petId = useProgression((s) => s.petId);
  const rows = useMemo(() => crewRows(crew, subjects, levelXp), [crew, subjects, levelXp]);
  const drone = rankView(subjects[petSubject(petId)], levelXp);
  const droneName = companionName || t("verse.ranks.record.companion");
  return (
    <table className="vr-crew">
      <thead>
        <tr>
          <th className="vr-caps">{t("verse.ranks.kind.agent")}</th>
          <th className="vr-caps">{t("verse.ranks.record.rank")}</th>
          <th className="vr-caps" style={{ textAlign: "right" }}>{t("verse.ranks.record.level")}</th>
          <th className="vr-caps" style={{ textAlign: "right" }}>{t("verse.ranks.card.xp")}</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr><td colSpan={4} className="vr-hint">{t("verse.ranks.record.crew_empty")}</td></tr>
        )}
        {rows.map((row) => (
          <tr key={row.agentId} data-agent={row.agentId}>
            <td><span className="vr-who"><RankPlate rank={row.view.rank.id} size={14} />{row.name}</span></td>
            <td>{t(`verse.ranks.rank.${row.view.rank.id}`)}</td>
            <td className="vr-num">{row.view.level}</td>
            <td className="vr-num">{figure(row.view.xp)}</td>
          </tr>
        ))}
        <tr data-agent="companion">
          <td><span className="vr-who"><RankPlate rank={drone.rank.id} size={14} />{droneName}</span></td>
          <td>{t(`verse.ranks.rank.${drone.rank.id}`)}</td>
          <td className="vr-num">{drone.level}</td>
          <td className="vr-num">{figure(drone.xp)}</td>
        </tr>
      </tbody>
    </table>
  );
}
