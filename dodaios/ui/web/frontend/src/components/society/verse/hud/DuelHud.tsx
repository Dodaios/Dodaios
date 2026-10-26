/**
 * The duel's HUD, in the Verse's own look (thin lines, mono numerals,
 * amber and red on near-black): the score and round clock top centre with
 * the opponent's health under them, a spread-aware crosshair that kicks
 * with the recoil and marks hits (headshots gold, the knockout red), arcs
 * showing where hits came from, the commander's health, shield and roll top
 * of the bottom left, the blaster's heat with the vent's gold window bottom
 * right, call-outs (parry, perfect vent), the countdown and round banners,
 * and the pause and result screens.
 *
 * The model comes from the controller once per rendered frame
 * (`buildHudModel`); this component only draws it.
 */
import { useEffect, useState, type CSSProperties } from "react";
import { fill } from "@/i18n";
import { crosshairRadiusPx } from "../combat/camera";
import type { DuelController, DuelPhase } from "../duel/duelController";
import type { HudModel } from "../duel/duelHud";
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
  /** Crosshair offset by the recoil the view has not followed, px. */
  ping: { x: number; y: number; alpha: number } | null;
  onTarget: boolean;
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
      setFrame({ model, radius, ping, onTarget: controller.aimTarget === "player" });
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
  return (
    <div className="verse-duel" data-phase={phase} aria-live="off">
      {m && (
        <>
          <div className="verse-duel-hurt" style={{ opacity: Math.max(m.hurt * 0.9, m.lowHealth ? 0.35 : 0) }} data-low={m.lowHealth} aria-hidden />
          <div className="verse-duel-top">
            <div className="verse-duel-score">
              <span className="verse-duel-side" data-side="own"><span className="verse-label">{t("verse.duel.hud.you")}</span><b className="verse-num">{m.myScore}</b></span>
              <span className="verse-duel-round">
                <span className="verse-label">{fill(t("verse.duel.hud.round"), { n: m.round })}</span>
                <b className="verse-num">{m.timeLeft !== null ? clock(m.timeLeft) : "--:--"}</b>
                <span className="verse-duel-pips" aria-hidden>
                  {Array.from({ length: m.roundsToWin }, (_, k) => <i key={`a${k}`} data-on={k < m.myScore} data-side="own" />)}
                  <em />
                  {Array.from({ length: m.roundsToWin }, (_, k) => <i key={`b${k}`} data-on={k < m.theirScore} data-side="foe" />)}
                </span>
              </span>
              <span className="verse-duel-side" data-side="foe"><b className="verse-num">{m.theirScore}</b><span className="verse-label">{t("verse.duel.hud.bot")}</span></span>
            </div>
            <Bar value={m.enemyHealthFrac} tone="foe" label={t("verse.duel.hud.bot")} />
            {m.surge && <div className="verse-duel-surge verse-label">{t("verse.duel.hud.surge")}</div>}
          </div>

          {/* Crosshair: four ticks at the spread, a centre dot; red over the opponent. */}
          {phase === "running" && (
            <div className="verse-duel-cross" data-target={frame!.onTarget} data-ads={m.ads > 0.5} data-blocked={!m.canFire}
              style={{ "--r": `${Math.max(4, frame!.radius)}px` } as CSSProperties} aria-hidden>
              <i data-d="u" /><i data-d="d" /><i data-d="l" /><i data-d="r" /><b />
              {m.hitMarker && <span className="verse-duel-hit" data-kind={m.hitMarker.kind} style={{ opacity: m.hitMarker.alpha }}><s /><s /><s /><s /></span>}
            </div>
          )}
          {m.damageArcs.map((a, k) => (
            <div key={k} className="verse-duel-arc" style={{ transform: `translate(-50%, -50%) rotate(${a.angleDeg}deg)`, opacity: a.alpha }} aria-hidden><i /></div>
          ))}
          {m.callout && <div className="verse-duel-callout" data-key={m.callout.key} style={{ opacity: Math.min(1, m.callout.alpha * 1.6) }}>{t(`verse.duel.callout.${m.callout.key}`)}</div>}
          {frame!.ping && <div className="verse-duel-ping" style={{ transform: `translate(${frame!.ping.x}px, ${frame!.ping.y}px)`, opacity: frame!.ping.alpha }} aria-hidden />}

          {m.banner && phase !== "result" && (
            <div className="verse-duel-banner" data-kind={m.banner.kind} data-outcome={m.banner.kind === "round" ? m.banner.outcome : undefined} role="status">
              {m.banner.kind === "countdown" && <b className="verse-num" key={m.banner.value}>{m.banner.value}</b>}
              {m.banner.kind === "fight" && <b>{t("verse.duel.hud.fight")}</b>}
              {m.banner.kind === "round" && (
                <>
                  <b>{t(`verse.duel.round.${m.banner.outcome}`)}</b>
                  <span className="verse-label">{t(`verse.duel.round.${m.banner.reason}`)}</span>
                </>
              )}
            </div>
          )}

          <div className="verse-duel-vitals verse-panel">
            <div className="verse-duel-row">
              <span className="verse-label">{t("verse.duel.hud.health")}</span>
              <b className="verse-num" data-low={m.lowHealth}>{m.health}</b>
            </div>
            <Bar value={m.healthFrac} tone={m.lowHealth ? "low" : "own"} label={t("verse.duel.hud.health")} />
            <div className="verse-duel-row">
              <span className="verse-label">{t("verse.duel.hud.shield")}</span>
              <span className="verse-label" data-tone={m.shieldBroken ? "bad" : m.parryReady ? "good" : "dim"}>
                {m.shieldBroken ? fill(t("verse.duel.hud.shield_down"), { s: m.shieldBrokenLeft.toFixed(1) }) : m.parryReady ? t("verse.duel.hud.parry_ready") : t("verse.duel.hud.parry_locked")}
              </span>
            </div>
            <Bar value={m.shieldFrac} tone={m.shieldBroken ? "bad" : m.shieldUp ? "shield-up" : "shield"} label={t("verse.duel.hud.shield")} />
            <div className="verse-duel-row verse-duel-roll" data-ready={m.dodgeReady}>
              <span className="verse-label">{t("verse.duel.hud.roll")}</span>
              <span className="verse-duel-cool"><i style={{ transform: `scaleX(${1 - m.dodgeCooldown})` }} /></span>
              <kbd className="verse-key">{t("verse.duel.controls.space")}</kbd>
            </div>
          </div>

          <div className="verse-duel-gun verse-panel" data-overheated={m.overheated} data-venting={m.venting}>
            <div className="verse-duel-row">
              <span className="verse-label">{t("verse.duel.hud.heat")}</span>
              <span className="verse-label" data-tone={m.overheated ? "bad" : m.venting ? "gold" : "dim"}>
                {m.overheated ? t("verse.duel.hud.overheated") : m.venting ? t("verse.duel.hud.venting") : `${Math.round(m.heat * 100)}%`}
              </span>
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
        <div className="verse-duel-overlay" role="dialog" aria-label={t(`verse.duel.result.${result.outcome}`)}>
          <div className="verse-duel-card verse-panel" data-outcome={result.outcome}>
            <div className="verse-duel-outcome">{t(`verse.duel.result.${result.outcome}`)}</div>
            <div className="verse-label">
              {fill(t("verse.duel.result.rounds"), { me: result.rounds[0], them: result.rounds[1] })}
              {" · "}
              {fill(t("verse.duel.result.against"), { tier: t(`verse.duel.difficulty.${controller.difficulty}`) })}
            </div>
            {result.stats && (
              <dl className="verse-duel-stats">
                <div><dt className="verse-label">{t("verse.duel.result.accuracy")}</dt><dd className="verse-num">{result.stats.player.shots ? Math.round((100 * result.stats.player.hits) / result.stats.player.shots) : 0}%</dd></div>
                <div><dt className="verse-label">{t("verse.duel.result.damage")}</dt><dd className="verse-num">{Math.round(result.stats.player.damageDealt)}</dd></div>
                <div><dt className="verse-label">{t("verse.duel.result.headshots")}</dt><dd className="verse-num">{result.stats.player.headshots}</dd></div>
                <div><dt className="verse-label">{t("verse.duel.result.parries")}</dt><dd className="verse-num">{result.stats.player.parries}</dd></div>
                <div><dt className="verse-label">{t("verse.duel.result.blocks")}</dt><dd className="verse-num">{result.stats.player.blocks}</dd></div>
                <div><dt className="verse-label">{t("verse.duel.result.perfect_vents")}</dt><dd className="verse-num">{result.stats.player.perfectVents}</dd></div>
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
