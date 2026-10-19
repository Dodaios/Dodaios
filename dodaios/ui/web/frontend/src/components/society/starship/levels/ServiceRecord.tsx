/**
 * The captain's service record: one dialog for everything the level system
 * knows. Record (where you stand, what comes next, the ship's log), Ranks (the
 * whole ladder), Rewards (suits, destinations, decorations), How to earn
 * (every rule in plain words) and Crew (every android's rank).
 *
 * It replaces the office tower's Level Hall screen. One hierarchy per page,
 * hairlines instead of boxes, gold only on what the captain holds or earns.
 * Accessible: a modal dialog with a focus trap, Escape closes, tabs and
 * choices are real buttons with arrow-key navigation.
 */
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactElement } from "react";
import { Lock, Volume2, VolumeX, X } from "lucide-react";
import { useLocaleChunk } from "@/i18n";
import { useSocietyRoster } from "../../data";
import { useLevelSound } from "../../progression/levelSounds";
import { suitFor, type SuitChoice } from "../../progression/cosmetics";
import { petSubject, PERSON_SUBJECT } from "../../progression/progressionApi";
import { SERVICE_TABS, useProgression, type ServiceTab } from "../../progression/progressionStore";
import type { SuitId } from "../../progression/levelCatalog";
import { useShip } from "../shipStore";
import { DESTINATIONS } from "../space/destinations";
import { Insignia } from "./Insignia";
import { crewRanking, nextReward, rankLadder, rewardShelves, ruleGroups, shipLog, xpToReach } from "./levelModel";
import { fill, useLevelText, type LevelText } from "./levelText";
import { nextRank, rankFor } from "./ranks";
import { DestinationSwatch, RewardGlyph, SuitOutline } from "./RewardGlyph";
import "./levels.css";

export interface ServiceRecordProps {
  onClose: () => void;
  initialTab?: ServiceTab;
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

export function ServiceRecord({ onClose, initialTab = "record" }: ServiceRecordProps) {
  useLocaleChunk("ship");
  const text = useLevelText();
  const { t } = text;
  const [tab, setTab] = useState<ServiceTab>(initialTab);
  const dialogRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<Partial<Record<ServiceTab, HTMLButtonElement | null>>>({});
  const ids = useId();
  const sound = useLevelSound();

  // Focus the open tab; give focus back to whatever opened the record.
  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    tabRefs.current[initialTab]?.focus();
    return () => { opener?.focus?.(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // Keys typed in the record never steer the captain.
    event.stopPropagation();
    if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
    if (event.key !== "Tab" || !dialogRef.current) return;
    const nodes = [...dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
    if (nodes.length === 0) return;
    const first = nodes[0], last = nodes[nodes.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };

  const onTabKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const at = SERVICE_TABS.indexOf(tab);
    const to = event.key === "ArrowRight" ? (at + 1) % SERVICE_TABS.length
      : event.key === "ArrowLeft" ? (at - 1 + SERVICE_TABS.length) % SERVICE_TABS.length
      : event.key === "Home" ? 0 : event.key === "End" ? SERVICE_TABS.length - 1 : -1;
    if (to < 0) return;
    event.preventDefault();
    setTab(SERVICE_TABS[to]);
    tabRefs.current[SERVICE_TABS[to]]?.focus();
  };

  return (
    <div className="svc-scrim" onKeyDown={onKeyDown} onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialogRef} className="svc" role="dialog" aria-modal="true" aria-labelledby={`${ids}-title`}>
        <header className="svc-head">
          <h2 id={`${ids}-title`} className="svc-title">{t("ship.levels.record")}</h2>
          <div className="svc-head-tools">
            <button type="button" className="svc-icon" aria-pressed={sound.on} aria-label={t("ship.levels.sound")} title={t("ship.levels.sound")} onClick={() => sound.set(!sound.on)}>
              {sound.on ? <Volume2 size={16} /> : <VolumeX size={16} />}
            </button>
            <button type="button" className="svc-icon" aria-label={t("ship.levels.close")} title={t("ship.levels.close")} onClick={onClose}><X size={17} /></button>
          </div>
        </header>
        <div className="svc-tabs" role="tablist" aria-label={t("ship.levels.tabs.label")}>
          {SERVICE_TABS.map((id) => (
            <button key={id} ref={(el) => { tabRefs.current[id] = el; }} type="button" role="tab" className="svc-tab"
              id={`${ids}-tab-${id}`} aria-selected={tab === id} aria-controls={`${ids}-panel`} tabIndex={tab === id ? 0 : -1}
              onClick={() => setTab(id)} onKeyDown={onTabKey}>
              {t(`ship.levels.tabs.${id}`)}
            </button>
          ))}
        </div>
        <div className="svc-body" role="tabpanel" id={`${ids}-panel`} aria-labelledby={`${ids}-tab-${tab}`} tabIndex={0}>
          {tab === "record" && <RecordPage text={text} />}
          {tab === "ranks" && <RanksPage text={text} />}
          {tab === "rewards" && <RewardsPage text={text} />}
          {tab === "earn" && <EarnPage text={text} />}
          {tab === "crew" && <CrewPage text={text} />}
        </div>
      </div>
    </div>
  );
}

/** The captain's level and the curve; level 1 with no XP until the first read. */
function useCaptain() {
  const person = useProgression((s) => s.subjects[PERSON_SUBJECT]);
  const snapshot = useProgression((s) => s.snapshot);
  return { level: person?.level ?? 1, xp: person?.xp ?? 0, person, snapshot, levelXp: snapshot?.levelXp ?? [] };
}

/** The companion's name: the lead on the roster (the pet IS Jarvis aboard). */
function useCompanionName(): string {
  const roster = useSocietyRoster();
  return roster.data?.agents.find((a) => a.tier === "lead")?.name ?? "Jarvis";
}

// ------------------------------------------------------------------ Record

function RecordPage({ text }: { text: LevelText }) {
  const { t, num } = text;
  const { level, xp, person, snapshot, levelXp } = useCaptain();
  const petId = useProgression((s) => s.petId);
  const companion = useCompanionName();
  const rank = rankFor(level);
  const next = nextRank(level);
  const reward = snapshot ? nextReward(snapshot.rewards, "person", level) : null;
  const atCap = !!person && person.xpForNext <= 0 && level > 1;
  const share = person && person.xpForNext > 0 ? Math.min(1, person.xpIntoLevel / person.xpForNext) : atCap ? 1 : 0;
  const log = useMemo(() => (snapshot ? shipLog(snapshot.recent, new Set([PERSON_SUBJECT, petSubject(petId)])) : []), [snapshot, petId]);
  const toNext = next ? xpToReach(levelXp, xp, next.level) : null;
  const toReward = reward ? xpToReach(levelXp, xp, reward.level) : null;

  return (
    <div className="svc-record">
      <section className="svc-plate" aria-label={t("ship.levels.who.captain")}>
        <div className="svc-plate-insignia"><Insignia rank={rank.id} size={84} title={text.rank(rank.id)} /></div>
        <span className="lv-eyebrow">{t("ship.levels.who.captain")} · {t(`ship.levels.tier.${rank.tier}`)}</span>
        <div className="svc-rank">{text.rank(rank.id)}</div>
        <div className="svc-level"><b>{text.level(level)}</b>{person ? <> · {fill(t("ship.levels.xp"), { n: num(person.xp) })}</> : null}</div>
        <div className="lv-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)} aria-label={text.level(level)}>
          <i style={{ width: `${Math.round(share * 100)}%` }} />
        </div>
        <div className="lv-bar-legend">
          {atCap ? <span>{t("ship.levels.at_cap")}</span> : (
            <>
              <span>{fill(t("ship.levels.xp_progress"), { have: num(person?.xpIntoLevel ?? 0), need: num(person?.xpForNext ?? 0) })}</span>
              {person && <span>{fill(t("ship.levels.xp_missing"), { n: num(Math.max(0, person.xpForNext - person.xpIntoLevel)), level: level + 1 })}</span>}
            </>
          )}
        </div>
        <div className="svc-next">
          <div className="svc-next-row">
            <span className="lv-eyebrow">{t("ship.levels.next_promotion")}</span>
            {next ? (
              <>
                <Insignia rank={next.id} size={30} tone="muted" />
                <div>
                  <strong>{fill(t("ship.levels.next_promotion_line"), { rank: text.rank(next.id), level: next.level })}</strong>
                  {toNext !== null && <span>{text.xpToGo(toNext)}</span>}
                </div>
              </>
            ) : <div style={{ gridColumn: "1 / -1" }}><span>{t("ship.levels.top_rank")}</span></div>}
          </div>
          <div className="svc-next-row">
            <span className="lv-eyebrow">{t("ship.levels.next_reward")}</span>
            {reward ? (
              <>
                <RewardGlyph reward={reward.reward.rewardId} size={30} />
                <div>
                  <strong>{fill(t("ship.levels.next_reward_line"), { reward: text.reward(reward.reward.rewardId), level: reward.level })}</strong>
                  {toReward !== null && <span>{text.xpToGo(toReward)}</span>}
                </div>
              </>
            ) : <div style={{ gridColumn: "1 / -1" }}><span>{snapshot ? t("ship.levels.all_open") : t("ship.levels.unavailable")}</span></div>}
          </div>
        </div>
      </section>
      <section className="svc-log" aria-labelledby="svc-log-title">
        <h3 id="svc-log-title" className="lv-eyebrow">{t("ship.levels.log")}</h3>
        {!snapshot ? <p className="svc-empty">{t("ship.levels.unavailable")}</p>
          : log.length === 0 ? <p className="svc-empty">{t("ship.levels.log_empty")}</p> : (
            <ol>
              {log.map((entry) => {
                const mark = entry.line.kind === "promoted" || entry.line.kind === "level";
                return (
                  <li key={entry.seq} data-mark={mark}>
                    <time dateTime={new Date(entry.tsMs).toISOString()}>{text.when(entry.tsMs)}</time>
                    <span>
                      {entry.subjectId !== PERSON_SUBJECT && <span className="who">{companion}</span>}
                      <span className="what">
                        {entry.line.kind === "promoted" && <Insignia rank={entry.line.rank} size={18} />}
                        {text.logLine(entry.line)}
                      </span>
                    </span>
                    <span className="xp">+{num(entry.xp)}</span>
                  </li>
                );
              })}
            </ol>
          )}
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ Ranks

function RanksPage({ text }: { text: LevelText }) {
  const { t } = text;
  const { level, xp, levelXp } = useCaptain();
  const groups = useMemo(() => rankLadder(level, xp, levelXp), [level, xp, levelXp]);
  return (
    <div>
      {groups.map((group) => (
        <section key={group.tier} className="svc-tier" aria-labelledby={`svc-tier-${group.tier}`}>
          <div className="svc-tier-head">
            <h3 id={`svc-tier-${group.tier}`} className="lv-eyebrow">{t(`ship.levels.tier.${group.tier}`)}</h3>
            <p>{t(`ship.levels.tier_about.${group.tier}`)}</p>
          </div>
          <ol className="svc-rungs">
            {group.rungs.map(({ rank, state, xpToGo }) => (
              <li key={rank.id} className="svc-rung" data-state={state} aria-current={state === "current" ? "true" : undefined}>
                <span className="svc-node" aria-hidden="true" />
                <Insignia rank={rank.id} size={40} tone={state === "ahead" ? "muted" : "metal"} />
                <span className="svc-rung-name">{text.rank(rank.id)}<small>{text.level(rank.level)}</small></span>
                <span className="svc-rung-state">
                  {state === "current" ? <span className="svc-tag">{t("ship.levels.rank_current")}</span>
                    : state === "held" ? t("ship.levels.rank_held")
                    : xpToGo !== null ? text.xpToGo(xpToGo) : ""}
                </span>
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ Rewards

function RewardsPage({ text }: { text: LevelText }) {
  const { t } = text;
  const { level, xp, snapshot, levelXp } = useCaptain();
  const choice = useProgression((s) => s.suit);
  const course = useShip((s) => s.destination);
  const shelves = useMemo(() => (snapshot ? rewardShelves(snapshot.rewards, level, xp, levelXp) : []), [snapshot, level, xp, levelXp]);
  if (!snapshot) return <p className="svc-empty">{t("ship.levels.unavailable")}</p>;
  const worn = suitFor(snapshot.rewards, level, choice);
  const state = (open: boolean, at: number, toGo: number | null) => (open ? t("ship.levels.open_state")
    : `${fill(t("ship.levels.opens_at"), { n: at })}${toGo !== null ? ` · ${text.xpToGo(toGo)}` : ""}`);

  return (
    <div>
      {shelves.map((shelf) => (
        <section key={shelf.slot} className="svc-section" aria-labelledby={`svc-shelf-${shelf.slot}`}>
          <h3 id={`svc-shelf-${shelf.slot}`} className="lv-eyebrow">{t(`ship.levels.rewards.${shelf.slot}`)}</h3>
          <p>{t(`ship.levels.rewards.${shelf.slot}_about`)}</p>
          {shelf.slot === "suit" ? (
            <SuitChoices text={text} choice={choice} worn={worn}
              suits={shelf.items.map((item) => ({ id: item.reward.rewardId as SuitId, open: item.open, state: state(item.open, item.level, item.xpToGo) }))} />
          ) : (
            <ul className="svc-list">
              {shelf.slot === "destination" && (
                <li className="svc-item" data-open="true">
                  <DestinationSwatch destination={DESTINATIONS[0]} />
                  <span className="svc-item-name">{t("ship.levels.home")}<small>{text.level(1)}</small></span>
                  <span className="svc-item-state">{course === "home" ? <span className="svc-tag" data-tone="info">{t("ship.levels.current_course")}</span> : t("ship.levels.open_state")}</span>
                </li>
              )}
              {shelf.items.map((item) => {
                const isCourse = shelf.slot === "destination" && `destination_${course}` === item.reward.rewardId;
                return (
                  <li key={item.reward.rewardId} className="svc-item" data-open={item.open}>
                    <RewardGlyph reward={item.reward.rewardId} />
                    <span className="svc-item-name">{text.reward(item.reward.rewardId)}<small>{text.level(item.level)}</small></span>
                    <span className="svc-item-state">
                      {isCourse ? <span className="svc-tag" data-tone="info">{t("ship.levels.current_course")}</span> : state(item.open, item.level, item.xpToGo)}
                      {!item.open && <Lock size={12} style={{ marginLeft: 6, verticalAlign: -1 }} aria-hidden="true" />}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      ))}
    </div>
  );
}

function SuitChoices({ text, choice, worn, suits }: {
  text: LevelText; choice: SuitChoice; worn: SuitId | null; suits: { id: SuitId; open: boolean; state: string }[];
}) {
  const { t } = text;
  const chooseSuit = useProgression((s) => s.chooseSuit);
  const options: { value: SuitChoice; open: boolean; name: string; sub: string; state: string; glyph: ReactElement }[] = [
    { value: "auto", open: true, name: t("ship.levels.auto"), sub: t("ship.levels.auto_about"), state: "", glyph: <SuitOutline starred /> },
    { value: "none", open: true, name: t("ship.levels.own"), sub: t("ship.levels.own_about"), state: "", glyph: <SuitOutline starred={false} /> },
    ...suits.map((s) => ({ value: s.id as SuitChoice, open: s.open, name: text.reward(s.id), sub: s.state, state: s.id === worn ? t("ship.levels.wearing") : "", glyph: <RewardGlyph reward={s.id} /> })),
  ];
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : event.key === "ArrowUp" || event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    for (let i = 1; i <= options.length; i += 1) {
      const at = (index + step * i + options.length) % options.length;
      if (options[at].open) { chooseSuit(options[at].value); refs.current[at]?.focus(); return; }
    }
  };
  const checkedIndex = Math.max(0, options.findIndex((o) => o.value === choice));
  return (
    <div role="radiogroup" aria-label={t("ship.levels.suit_choice")}>
      {options.map((o, i) => (
        <button key={o.value} ref={(el) => { refs.current[i] = el; }} type="button" role="radio" className="svc-item svc-choice"
          aria-checked={o.value === choice} aria-disabled={!o.open} data-open={o.open} tabIndex={i === checkedIndex ? 0 : -1}
          onClick={() => { if (o.open) chooseSuit(o.value); }} onKeyDown={(e) => onKey(e, i)}>
          {o.glyph}
          <span className="svc-item-name"><span className="svc-radio" aria-hidden="true" />{o.name}<small>{o.sub}</small></span>
          <span className="svc-item-state">{o.state ? <span className="svc-tag">{o.state}</span> : !o.open ? <Lock size={12} aria-hidden="true" /> : null}</span>
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ How to earn

function EarnPage({ text }: { text: LevelText }) {
  const { t, num } = text;
  const snapshot = useProgression((s) => s.snapshot);
  const groups = useMemo(() => ruleGroups(snapshot?.rules ?? []), [snapshot]);
  if (groups.length === 0) return <p className="svc-empty">{t("ship.levels.unavailable")}</p>;
  return (
    <div>
      <p className="svc-lead">{t("ship.levels.earn.lead")}</p>
      {groups.map((group) => (
        <section key={group.kind} className="svc-section" aria-labelledby={`svc-earn-${group.kind}`}>
          <h3 id={`svc-earn-${group.kind}`} className="lv-eyebrow">{t(`ship.levels.earn.${group.kind}`)}</h3>
          <table className="svc-rules">
            <tbody>
              {group.rules.map(({ rule, limit }) => (
                <tr key={rule.source}>
                  <td>{t(`ship.levels.rule.${rule.source}`)}</td>
                  <td className="limit">{text.limit(limit)}</td>
                  <td className="amount">+{num(rule.xp)} XP</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ Crew

function CrewPage({ text }: { text: LevelText }) {
  const { t } = text;
  const roster = useSocietyRoster();
  const subjects = useProgression((s) => s.subjects);
  const petId = useProgression((s) => s.petId);
  const crew = useMemo(() => crewRanking(roster.data?.agents ?? [], subjects), [roster.data, subjects]);
  const lead = roster.data?.agents.find((a) => a.tier === "lead");
  const petLevel = subjects[petSubject(petId)]?.level ?? 1;
  const petRank = rankFor(petLevel);
  return (
    <div>
      <section className="svc-section" aria-label={t("ship.levels.who.companion")}>
        <h3 className="lv-eyebrow">{t("ship.levels.who.companion")}</h3>
        <ul className="svc-list svc-crew">
          <li className="svc-item">
            <span className="pos" aria-hidden="true" />
            <Insignia rank={petRank.id} size={32} />
            <span className="svc-item-name">{lead?.name ?? "Jarvis"}<small>{text.rank(petRank.id)}</small></span>
            <span className="svc-item-state">{text.level(petLevel)}</span>
          </li>
        </ul>
      </section>
      <section className="svc-section" aria-label={t("ship.levels.who.crew")}>
        <h3 className="lv-eyebrow">{t("ship.levels.who.crew")}</h3>
        <p>{t("ship.levels.crew.about")}</p>
        {crew.length === 0 ? <p className="svc-empty">{t("ship.levels.crew.empty")}</p> : (
          <ol className="svc-list svc-crew">
            {crew.map((row, i) => (
              <li key={row.agentId} className="svc-item">
                <span className="pos">{i + 1}</span>
                <Insignia rank={row.rank.id} size={32} />
                <span className="svc-item-name">{row.name}<small>{text.rank(row.rank.id)}</small></span>
                <span className="svc-item-state">{text.level(row.level)}</span>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}
