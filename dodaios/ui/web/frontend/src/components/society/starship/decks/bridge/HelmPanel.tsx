/**
 * The helm's panel: "Set a course". Every destination is a row with its name,
 * one line about it and the captain's level that opens it; the ones the
 * captain's level has opened can be chosen, the current one is marked.
 * Choosing one closes the panel and starts the warp jump. Keyboard: the
 * arrows move between rows, Enter engages, Escape closes; focus stays in the
 * dialog while it is open and returns where it was afterwards.
 */
import { useEffect, useId, useRef, type CSSProperties, type KeyboardEvent } from "react";
import { useReducedMotion } from "framer-motion";
import { useProgression } from "../../../progression/progressionStore";
import { useShip } from "../../shipStore";
import { DESTINATIONS, destinationById, type Destination } from "../../space/destinations";
import type { DeckPanelProps } from "../registry";
import { engageWarp } from "./bridgeRuntime";
import "./bridge.css";

export function BridgePanel(props: DeckPanelProps) {
  if (props.station.kind !== "helm") return null;
  return <HelmPanel {...props} />;
}

/** A small swatch of the place: its planet's day side, or the nebula where there is none. */
function swatch(d: Destination): CSSProperties {
  if (d.singularity) return { background: `radial-gradient(circle at 50% 50%, #000 0 34%, #ffcf8a 40%, ${d.sky.nebula[1]} 62%, #05070c 76%)` };
  if (d.planet.kind === "none") return { background: `radial-gradient(circle at 40% 40%, ${d.sky.nebula[1]}, ${d.sky.nebula[0]} 58%, #05070c 80%)` };
  const [deep, mid, bright] = d.planet.colours;
  return { background: `radial-gradient(circle at 34% 30%, ${bright}, ${mid} 42%, ${deep} 72%, #05070c 74%)` };
}

function HelmPanel({ actions }: DeckPanelProps) {
  const { t } = actions;
  const reduced = useReducedMotion() ?? false;
  const level = useProgression((s) => s.subjects.person?.level ?? 1);
  const hereId = useShip((s) => s.destination);
  const warping = useShip((s) => s.warpingTo);
  const here = destinationById(hereId);
  const titleId = useId();
  const dialog = useRef<HTMLElement>(null);
  const list = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const before = document.activeElement;
    const first = list.current?.querySelector<HTMLButtonElement>("[aria-current='true']") ?? list.current?.querySelector<HTMLButtonElement>("button");
    first?.focus();
    return () => { if (before instanceof HTMLElement && before.isConnected) before.focus(); };
  }, []);

  const name = (d: Destination) => t(`ship.bridge.destination.${d.id}.name`);
  const choose = (d: Destination) => {
    if (warping) return;
    if (d.id === here.id) { actions.say(t("ship.bridge.helm.already").replace("{place}", name(d))); return; }
    if (d.level > level) { actions.say(t("ship.bridge.helm.locked_say").replace("{place}", name(d)).replace("{n}", String(d.level))); return; }
    actions.closePanel();
    if (engageWarp(d.id, reduced, actions)) actions.say(t("ship.bridge.helm.engaged").replace("{place}", name(d)));
  };

  const onKey = (e: KeyboardEvent<HTMLElement>) => {
    // The ship's own keys (walking, E, O, F) stay out while the dialog has focus.
    e.stopPropagation();
    if (e.key === "Escape") { e.preventDefault(); actions.closePanel(); return; }
    const rows = [...(list.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
    const at = rows.indexOf(document.activeElement as HTMLButtonElement);
    const go = (i: number) => { e.preventDefault(); rows[(i + rows.length) % rows.length]?.focus(); };
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at < 0 ? rows.length - 1 : at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(rows.length - 1);
    else if (e.key === "Tab") {
      const all = [...(dialog.current?.querySelectorAll<HTMLButtonElement>("button") ?? [])];
      if (all.length === 0) return;
      const first = all[0], last = all[all.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  };

  return (
    <div className="ship-scrim" onClick={() => actions.closePanel()}>
      <section ref={dialog} className="ship-panel bridge-helm" role="dialog" aria-modal="true" aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()} onKeyDown={onKey}>
        <header className="bridge-helm-head">
          <div>
            <div className="ship-eyebrow">{t("ship.bridge.helm.eyebrow")}</div>
            <h2 id={titleId}>{t("ship.bridge.helm.title")}</h2>
            <p>
              {t("ship.bridge.helm.holding").replace("{place}", name(here))}
              <span aria-hidden="true"> · </span>
              {t("ship.bridge.helm.captain_level").replace("{n}", String(level))}
            </p>
          </div>
          <button type="button" className="ship-tool bridge-helm-close" aria-label={t("ship.close")} onClick={() => actions.closePanel()}>✕</button>
        </header>
        {warping && <div className="bridge-helm-warping" role="status">{t("ship.bridge.helm.warping").replace("{place}", name(destinationById(warping)))}</div>}
        <div ref={list} className="bridge-helm-list">
          {DESTINATIONS.map((d) => {
            const current = d.id === here.id;
            const locked = d.level > level;
            const state = current ? "here" : locked ? "locked" : "open";
            return (
              <button key={d.id} type="button" className="bridge-helm-row" data-state={state} aria-current={current}
                aria-disabled={locked || !!warping || undefined} onClick={() => choose(d)}>
                <span className="bridge-helm-swatch" style={swatch(d)} aria-hidden="true" />
                <span className="bridge-helm-text">
                  <b>{name(d)}</b>
                  <small>{t(`ship.bridge.destination.${d.id}.about`)}</small>
                </span>
                <span className="bridge-helm-meta">
                  <span className="bridge-helm-chip">{t(`ship.bridge.helm.${state}`)}</span>
                  <small>{t("ship.bridge.helm.opens").replace("{n}", String(d.level))}</small>
                </span>
              </button>
            );
          })}
        </div>
        <p className="bridge-helm-hint">{t("ship.bridge.helm.hint")}</p>
      </section>
    </div>
  );
}
