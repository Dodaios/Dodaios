/**
 * A division's holo-table: who belongs to the team and what each is doing,
 * the team's chat, and a briefing — the free members walk to the table and
 * stand round it for a minute and a half. A briefing is a gathering on the
 * map only: nothing is posted to the team and nobody starts work.
 */
import { useEffect, useRef } from "react";
import { AgentSwatch } from "../../../AgentSwatch";
import { rankFor } from "../../levels/ranks";
import { useProgression } from "../../../progression/progressionStore";
import { useShip } from "../../shipStore";
import type { DeckPanelProps } from "../registry";
import "./quartermaster.css";

export const BRIEFING_MS = 90_000;

export function DivisionPanel({ plan, station, actions, agents }: DeckPanelProps) {
  const { t } = actions;
  const division = plan.divisions.find((d) => `division:${d.room}` === station.id);
  const subjects = useProgression((s) => s.subjects);
  const gathering = useShip((s) => s.gathering);
  const first = useRef<HTMLButtonElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  if (!division) return null;
  const name = division.teamId ? division.name : t("ship.division.pool");
  const briefing = gathering?.place === division.room;
  const free = division.members.filter((id) => agents.get(id)?.state !== "working");
  const brief = () => {
    const store = useShip.getState();
    if (briefing) { store.gather(null); actions.say(t("ship.ops.division.briefing_over")); return; }
    if (free.length === 0) { actions.say(t("ship.ops.division.nobody_free")); return; }
    store.gather({ place: division.room, agentIds: free, untilMs: Date.now() + BRIEFING_MS });
    actions.reportAction("team_briefing", division.teamId ?? "");
    actions.say(t("ship.ops.division.briefing_called").replace("{count}", String(free.length)).replace("{team}", name));
    actions.closePanel();
  };
  return (
    <aside className="ship-panel qm-panel" role="dialog" aria-label={name}
      onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); actions.closePanel(); } }}>
      <header className="qm-head">
        <div>
          <div className="ship-eyebrow" style={{ color: division.colour }}>{t("ship.ops.division.eyebrow")}</div>
          <h2>{name}</h2>
        </div>
        <button type="button" className="ship-tool" aria-label={t("ship.close")} onClick={actions.closePanel}>✕</button>
      </header>
      <ul className="div-members">
        {division.members.map((id) => {
          const agent = agents.get(id);
          if (!agent) return null;
          const lead = division.leadId === id;
          return (
            <li key={id}>
              <span className="div-face"><AgentSwatch agent={{ ...agent, state: undefined }} size={26} /></span>
              <span className="div-name">{agent.name}{lead && <small className="div-lead">{t("ship.ops.division.lead")}</small>}</span>
              <span className="div-state"><i className="ship-dot" data-state={agent.state} />{t(`ship.state.${agent.state}`)}</span>
              <small className="div-rank">{t(`ship.rank.${rankFor(subjects[`agent:${id}`]?.level ?? 1).id}`)}</small>
            </li>
          );
        })}
        {division.members.length === 0 && <li className="div-empty">{t("ship.ops.division.empty")}</li>}
      </ul>
      <div className="div-actions">
        {division.teamId
          ? <button ref={first} type="button" className="ship-btn" data-primary="true" onClick={() => { actions.closePanel(); actions.openGroup(division.teamId as string); }}>{t("ship.ops.division.open_chat")}</button>
          : <button ref={first} type="button" className="ship-btn" data-primary="true" onClick={() => { actions.closePanel(); actions.openLedger(); }}>{t("ship.ops.division.open_agents")}</button>}
        {division.members.length > 0 && (
          <button type="button" className="ship-btn" onClick={brief}>{briefing ? t("ship.ops.division.end_briefing") : t("ship.ops.division.briefing")}</button>
        )}
      </div>
      <p className="qm-note">{t("ship.ops.division.note")}</p>
    </aside>
  );
}
