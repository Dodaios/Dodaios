/**
 * The duel's HUD, a clean shooter HUD in the Verse's charcoal and gold:
 *
 * - top centre, the score banner: both scores, the round and its clock,
 *   round pips, and the opponent's health under it;
 * - the crosshair (spread-aware, red over the opponent, dimmed when the
 *   blaster cannot fire) inside three thin gauges: heat up the right side
 *   with the vent's gold window and sweep, shield energy up the left, the
 *   roll's readiness along the bottom; hit markers on it (headshots gold, a
 *   knockout a red cross with a ring);
 * - damage: a red glow on the screen's edge the hit came from plus an arc
 *   round the crosshair, a red flash on every hit taken and a pulse at low
 *   health;
 * - bottom left the commander's health (large) and shield, the roll; bottom
 *   right the blaster's heat and vent;
 * - call-outs (parry, perfect vent, knockout...), a cinematic countdown
 *   (letterbox bars, the round's title, big numerals), *Fight*, round
 *   banners, a short slow-motion tint on a knockout;
 * - the pause screen and the match's end with both duellists' stats.
 *
 * The model comes from the controller once per rendered frame
 * (`buildHudModel`); this component only draws it.
 */
import { useEffect, useState, type CSSProperties } from "react";
import { fill } from "@/i18n";
import { crosshairRadiusPx } from "../combat/camera";
import type { PlayerStats } from "../combat/types";
import type { DuelController, DuelPhase } from "../duel/duelController";
import { arcPath, edgePoint, gaugeAngle, GAUGES, type HudModel } from "../duel/duelHud";
import type { StageRuntime } from "../runtime";
import { DUEL_CONTROLS } from "./DuelPanel";
import "./duel.css";

interface Props {
  runtime: StageRuntime;
  controller: DuelController;
  phase: DuelPhase;
  /** The pointer is locked to the stage (mouse aim). */
  locked: boolean;
  t: (key: string) => string;
  onResume: () => void;
  onLeave: () => void;
  onRematch: () => void;
}

interface Frame {
  model: HudModel;
  radius: number;
  /** The opponent's pinged position on screen (px). */
  ping: { x: number; y: number; alpha: number } | null;
  onTarget: boolean;
  /** A knockout's slow motion is playing. */
  slow: boolean;
}

function clock(seconds: number): string {
  const s = Math.max(0, seconds);
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
}

function Bar({ value, tone, segments = 10, label }: { value: number; tone: string; segments?: number; label?: string }) {
  return (
    <div className="verse-duel-bar" data-tone={tone} role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)} aria-label={label}>
      <i style={{ transform: `scaleX(${Math.max(0, Math.min(1, value))})` }} />
      <span aria-hidden>{Array.from({ length: segments - 1 }, (_, k) => <b key={k} style={{ left: `${((k + 1) / segments) * 100}%` }} />)}</span>
    </div>
  );
}

/** The three gauges round the crosshair. */
function Gauges({ m }: { m: HudModel }) {
  const r = GAUGES.radius;
  const heatValue = m.venting ? 1 - m.ventProgress : m.heat;
  const g = GAUGES.heat;
  const windowArc = m.ventWindow ? arcPath(r, gaugeAngle(g, 1 - m.ventWindow[1]), gaugeAngle(g, 1 - m.ventWindow[0])) : null;
  const sweep = m.venting ? gaugeAngle(g, 1 - m.ventProgress) : null;
  const tick = (deg: number) => {
    const a = (deg * Math.PI) / 180;
    return { x1: (r - 5) * Math.sin(a), y1: -(r - 5) * Math.cos(a), x2: (r + 5) * Math.sin(a), y2: -(r + 5) * Math.cos(a) };
  };
  return (
    <svg className="verse-duel-gauges" viewBox="-60 -60 120 120" aria-hidden
      data-hot={m.heat > 0.75} data-overheated={m.overheated} data-venting={m.venting}
      data-shield={m.shieldBroken ? "broken" : m.shieldUp ? "up" : "idle"} data-roll={m.dodgeReady}>
      <path className="track" d={arcPath(r, g.from, g.from + g.span)} />
      {heatValue > 0.005 && <path className="heat" d={arcPath(r, g.from, gaugeAngle(g, heatValue))} />}
      {windowArc && <path className="window" data-used={m.ventAttempted} d={windowArc} />}
      {sweep !== null && <line className="sweep" {...tick(sweep)} />}
      <path className="track" d={arcPath(r, GAUGES.shield.from, GAUGES.shield.from + GAUGES.shield.span)} />
      {m.shieldFrac > 0.005 && <path className="shield" d={arcPath(r, GAUGES.shield.from, gaugeAngle(GAUGES.shield, m.shieldFrac))} />}
      <path className="track" d={arcPath(r, GAUGES.roll.from, GAUGES.roll.from + GAUGES.roll.span)} />
      <path className="roll" d={arcPath(r, GAUGES.roll.from, gaugeAngle(GAUGES.roll, 1 - m.dodgeCooldown))} />
    </svg>
  );
}

function StatRow({ label, me, them, format = (v: number) => String(Math.round(v)) }: { label: string; me: number; them: number; format?: (v: number) => string }) {
  return (
    <div className="verse-duel-statrow" data-lead={me > them ? "me" : me < them ? "them" : "even"}>
      <dd className="verse-num" data-side="own">{format(me)}</dd>
      <dt className="verse-label">{label}</dt>
      <dd className="verse-num" data-side="foe">{format(them)}</dd>
    </div>
  );
}

const accuracy = (s: PlayerStats) => (s.shots ? (100 * s.hits) / s.shots : 0);

export function DuelHud({ runtime, controller, phase, locked, t, onResume, onLeave, onRematch }: Props) {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [hints, setHints] = useState(true);

  useEffect(() => {
    const refresh = () => {
      const model = controller.hud();
      if (!model) { setFrame(null); return; }
      const vh = runtime.view.vp.height || 1;
      const radius = crosshairRadiusPx(model.spreadDeg, controller.pose.fovDeg, vh);
      let ping: Frame["ping"] = null;
      if (model.ping) {
        const at = runtime.toScreen(model.ping.x, controller.floorY + 1.3, model.ping.z);
        if (at) ping = { x: at.x, y: at.y, alpha: model.ping.alpha };
      }
      setFrame({ model, radius, ping, onTarget: controller.aimTarget === "player", slow: controller.timeScale < 0.98 });
    };
    refresh();
    runtime.afterFrame.add(refresh);
    return () => { runtime.afterFrame.delete(refresh); };
  }, [runtime, controller]);

  // The key hints stay for the first seconds of a match.
  useEffect(() => {
    if (phase !== "running") return;
    setHints(true);
    const timer = setTimeout(() => setHints(false), 9000);
    return () => clearTimeout(timer);
  }, [phase, controller.result]);

  const m = frame?.model;
  const result = controller.result;
  const cinematic = !!m && phase !== "result" && (m.phase === "countdown" || m.banner?.kind === "round");
  return (
    <div className="verse-duel" data-phase={phase} data-slow={frame?.slow ?? false} aria-live="off">
      <div className="verse-duel-letterbox" data-on={cinematic} aria-hidden><i /><i /></div>
      {frame?.slow && <div className="verse-duel-slowmo" aria-hidden />}
      {m && (
        <>
          <div className="verse-duel-hurt" style={{ opacity: Math.max(m.hurt * 0.9, m.lowHealth ? 0.35 : 0) }} data-low={m.lowHealth} aria-hidden />
          {m.damageArcs.map((a, k) => {
            const at = edgePoint(a.angleDeg);
            return <div key={`e${k}`} className="verse-duel-edge" style={{ "--x": `${at.x}%`, "--y": `${at.y}%`, opacity: a.alpha } as CSSProperties} aria-hidden />;
          })}

          <div className="verse-duel-top">
            <div className="verse-duel-score">
              <span className="verse-duel-side" data-side="own">
                <span className="verse-label">{t("verse.duel.hud.you")}</span>
                <b className="verse-num">{m.myScore}</b>
              </span>
              <span className="verse-duel-round">
                <span className="verse-label">{fill(t("verse.duel.hud.round"), { n: m.round })}</span>
                <b className="verse-num" data-urgent={m.timeLeft !== null && m.timeLeft <= 10}>{m.timeLeft !== null ? clock(m.timeLeft) : "--:--"}</b>
                <span className="verse-duel-pips" aria-hidden>
                  {Array.from({ length: m.roundsToWin }, (_, k) => <i key={`a${k}`} data-on={k < m.myScore} data-side="own" />)}
                  <em />
                  {Array.from({ length: m.roundsToWin }, (_, k) => <i key={`b${k}`} data-on={k < m.theirScore} data-side="foe" />)}
                </span>
              </span>
              <span className="verse-duel-side" data-side="foe">
                <b className="verse-num">{m.theirScore}</b>
                <span className="verse-label">{t("verse.duel.hud.bot")}</span>
              </span>
            </div>
            <div className="verse-duel-foe">
              <Bar value={m.enemyHealthFrac} tone="foe" label={t("verse.duel.hud.bot")} />
            </div>
            {m.surge && <div className="verse-duel-surge verse-label">{t("verse.duel.hud.surge")}</div>}
          </div>

          {phase === "running" && (
            <div className="verse-duel-reticle" aria-hidden>
              <Gauges m={m} />
              <div className="verse-duel-cross" data-target={frame!.onTarget} data-ads={m.ads > 0.5} data-blocked={!m.canFire}
                style={{ "--r": `${Math.max(4, frame!.radius)}px` } as CSSProperties}>
                <i data-d="u" /><i data-d="d" /><i data-d="l" /><i data-d="r" /><b />
                {m.hitMarker && (
                  <span className="verse-duel-hit" data-kind={m.hitMarker.kind} style={{ opacity: m.hitMarker.alpha }} key={m.hitMarker.kind}>
                    <s /><s /><s /><s />
                    {m.hitMarker.kind === "kill" && <u />}
                  </span>
                )}
              </div>
            </div>
          )}
          {m.damageArcs.map((a, k) => (
            <div key={k} className="verse-duel-arc" style={{ transform: `translate(-50%, -50%) rotate(${a.angleDeg}deg)`, opacity: a.alpha }} aria-hidden><i /></div>
          ))}
          {m.callout && (
            <div className="verse-duel-callout" data-key={m.callout.key} style={{ opacity: Math.min(1, m.callout.alpha * 1.6) }}>
              {t(`verse.duel.callout.${m.callout.key}`)}
            </div>
          )}
          {frame!.ping && <div className="verse-duel-ping" style={{ transform: `translate(${frame!.ping.x}px, ${frame!.ping.y}px)`, opacity: frame!.ping.alpha }} aria-hidden />}

          {m.banner && phase !== "result" && (
            <div className="verse-duel-banner" data-kind={m.banner.kind} data-outcome={m.banner.kind === "round" ? m.banner.outcome : undefined} role="status">
              {m.banner.kind === "countdown" && (
                <>
                  <span className="verse-duel-kicker">
                    {fill(t("verse.duel.hud.round"), { n: m.banner.round })}
                    {m.banner.matchPoint && <em>{t("verse.duel.hud.match_point")}</em>}
                  </span>
                  <b className="verse-num" key={m.banner.value}>{m.banner.value}</b>
                  <span className="verse-duel-rule" key={`r${m.banner.value}`} />
                </>
              )}
              {m.banner.kind === "fight" && <b>{t("verse.duel.hud.fight")}</b>}
              {m.banner.kind === "round" && (
                <>
                  <span className="verse-duel-kicker">{t(`verse.duel.round.${m.banner.reason}`)}</span>
                  <b>{t(`verse.duel.round.${m.banner.outcome}`)}</b>
                  <span className="verse-duel-rule" />
                </>
              )}
            </div>
          )}

          <div className="verse-duel-vitals" data-low={m.lowHealth}>
            <div className="verse-duel-row">
              <span className="verse-label">{t("verse.duel.hud.health")}</span>
              <b className="verse-num verse-duel-health" data-low={m.lowHealth}>{m.health}</b>
            </div>
            <Bar value={m.healthFrac} tone={m.lowHealth ? "low" : "own"} label={t("verse.duel.hud.health")} />
            <div className="verse-duel-row">
              <span className="verse-label">{t("verse.duel.hud.shield")}</span>
              <span className="verse-label" data-tone={m.shieldBroken ? "bad" : m.parryReady ? "good" : "dim"}>
                {m.shieldBroken ? fill(t("verse.duel.hud.shield_down"), { s: m.shieldBrokenLeft.toFixed(1) }) : m.parryReady ? t("verse.duel.hud.parry_ready") : t("verse.duel.hud.parry_locked")}
              </span>
            </div>
            <Bar value={m.shieldFrac} segments={5} tone={m.shieldBroken ? "bad" : m.shieldUp ? "shield-up" : "shield"} label={t("verse.duel.hud.shield")} />
            <div className="verse-duel-row verse-duel-roll" data-ready={m.dodgeReady}>
              <span className="verse-label">{t("verse.duel.hud.roll")}</span>
              <span className="verse-duel-cool"><i style={{ transform: `scaleX(${1 - m.dodgeCooldown})` }} /></span>
              <kbd className="verse-key">{t("verse.duel.controls.space")}</kbd>
            </div>
          </div>

          <div className="verse-duel-gun" data-overheated={m.overheated} data-venting={m.venting}>
            <div className="verse-duel-row">
              <span className="verse-label">{t("verse.duel.hud.heat")}</span>
              <b className="verse-num verse-duel-heatnum" data-tone={m.overheated ? "bad" : m.venting ? "gold" : m.heat > 0.75 ? "warm" : "dim"}>
                {m.overheated ? t("verse.duel.hud.overheated") : m.venting ? t("verse.duel.hud.venting") : `${Math.round(m.heat * 100)}%`}
              </b>
            </div>
            <div className="verse-duel-heat" aria-hidden>
              <i style={{ transform: `scaleX(${m.venting ? 1 - m.ventProgress : m.heat})` }} data-hot={m.heat > 0.75} />
              {m.ventWindow && (
                <span className="verse-duel-window" data-used={m.ventAttempted}
                  style={{ left: `${(1 - m.ventWindow[1]) * 100}%`, width: `${(m.ventWindow[1] - m.ventWindow[0]) * 100}%` }} />
              )}
              {m.venting && <em style={{ left: `${(1 - m.ventProgress) * 100}%` }} />}
            </div>
            <div className="verse-duel-row">
              <span className="verse-label" data-tone={m.venting && !m.ventAttempted ? "gold" : "dim"}>
                {m.venting && !m.ventAttempted ? t("verse.duel.hud.vent_hint") : t("verse.duel.hud.vent")}
              </span>
              <kbd className="verse-key">R</kbd>
            </div>
          </div>

          {hints && phase === "running" && (
            <div className="verse-duel-hints" aria-hidden>
              {DUEL_CONTROLS.map(([key, action]) => (
                <span key={action}><kbd className="verse-key">{key.startsWith("verse.") ? t(key) : key}</kbd>{t(action)}</span>
              ))}
            </div>
          )}
          {phase === "running" && !locked && (
            <button type="button" className="verse-duel-aim verse-label" onClick={onResume}>{t("verse.duel.hud.click_to_aim")}</button>
          )}
        </>
      )}

      {phase === "paused" && (
        <div className="verse-duel-overlay" role="dialog" aria-label={t("verse.duel.pause.title")}>
          <div className="verse-duel-card verse-panel">
            <div className="verse-dialog-title">{t("verse.duel.pause.title")}</div>
            <p>{t("verse.duel.pause.hint")}</p>
            <div className="verse-duel-actions">
              <button type="button" className="verse-tool" data-primary onClick={onResume} autoFocus>{t("verse.duel.pause.resume")}</button>
              <button type="button" className="verse-tool" onClick={onLeave}>{t("verse.duel.pause.leave")}</button>
            </div>
          </div>
        </div>
      )}

      {phase === "result" && result && (
        <div className="verse-duel-overlay verse-duel-end" role="dialog" aria-label={t(`verse.duel.result.${result.outcome}`)}>
          <div className="verse-duel-card verse-duel-result" data-outcome={result.outcome}>
            <span className="verse-duel-kicker">{fill(t("verse.duel.result.against"), { tier: t(`verse.duel.difficulty.${controller.difficulty}`) })}</span>
            <div className="verse-duel-outcome">{t(`verse.duel.result.${result.outcome}`)}</div>
            <div className="verse-duel-final" aria-label={fill(t("verse.duel.result.rounds"), { me: result.rounds[0], them: result.rounds[1] })}>
              <span data-side="own"><span className="verse-label">{t("verse.duel.hud.you")}</span><b className="verse-num">{result.rounds[0]}</b></span>
              <i aria-hidden>:</i>
              <span data-side="foe"><b className="verse-num">{result.rounds[1]}</b><span className="verse-label">{t("verse.duel.hud.bot")}</span></span>
            </div>
            {result.stats && (
              <dl className="verse-duel-stats">
                <StatRow label={t("verse.duel.result.accuracy")} me={accuracy(result.stats.player)} them={accuracy(result.stats.bot)} format={(v) => `${Math.round(v)}%`} />
                <StatRow label={t("verse.duel.result.damage")} me={result.stats.player.damageDealt} them={result.stats.bot.damageDealt} />
                <StatRow label={t("verse.duel.result.headshots")} me={result.stats.player.headshots} them={result.stats.bot.headshots} />
                <StatRow label={t("verse.duel.result.parries")} me={result.stats.player.parries} them={result.stats.bot.parries} />
                <StatRow label={t("verse.duel.result.blocks")} me={result.stats.player.blocks} them={result.stats.bot.blocks} />
                <StatRow label={t("verse.duel.result.perfect_vents")} me={result.stats.player.perfectVents} them={result.stats.bot.perfectVents} />
              </dl>
            )}
            <div className="verse-duel-actions">
              <button type="button" className="verse-tool" data-primary onClick={onRematch} autoFocus>{t("verse.duel.result.rematch")}</button>
              <button type="button" className="verse-tool" onClick={onLeave}>{t("verse.duel.result.leave")}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
