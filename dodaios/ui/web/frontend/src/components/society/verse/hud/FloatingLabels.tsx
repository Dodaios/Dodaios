/**
 * Labels that ride on the scene: the name plate of the crew member under the
 * pointer (or selected), and the label of the station under the pointer (or
 * within the commander's reach). React renders their text; their position is
 * written straight into the DOM after every frame, so a walking officer's
 * plate never lags behind them. They project through the view on screen
 * (`runtime.toScreen`: the plate, or the eye-level camera); at eye level a
 * label whose anchor is behind a wall, or behind the camera, is hidden, and
 * the station within reach is offered as a prompt below the middle of the
 * view, as games do.
 */
import { useEffect, useRef, type CSSProperties } from "react";
import type { StageRuntime } from "../runtime";
import type { Deck, Station } from "../content/deck";
import type { ArenaDef } from "../combat/arena";
import { DUEL_ICON } from "./DeckBar";
import { duelBeacon } from "./duelBeacon";

/** The duel arena on this deck: a marker near its consoles, an icon over it in the bird's-eye view. */
export interface DuelSpot {
  arena: ArenaDef;
  /** The arena room's floor height. */
  floorY: number;
  /** Whose position decides whether the marker shows. */
  commanderId: string;
  /** "Duel": the marker's and the icon's text. */
  label: string;
}

export interface PlateInfo {
  id: string;
  name: string;
  rank: string;
  status: string;
  statusKey: string;
  accent: string | null;
}

interface Props {
  runtime: StageRuntime;
  plates: readonly PlateInfo[];
  /** `key`: the key that works the station from where the commander stands (third person). */
  station: { station: Station; name: string; action: string; key?: string | null } | null;
  deck: Deck | null;
  /** The duel arena, on the deck that has one. */
  duel?: DuelSpot | null;
}

/** Where a label element was put last (CSS px, rounded), so an unmoved label is not written again. */
interface Placed { x: number; y: number; shown: boolean }

const OFF = "translate(-9999px, -9999px)";

/** Move a label to (x, y), or off screen when `shown` is false; writes the DOM only when that changes. */
function put(el: HTMLElement, placed: WeakMap<HTMLElement, Placed>, shown: boolean, x: number, y: number): void {
  let last = placed.get(el);
  if (!last) { last = { x: NaN, y: NaN, shown: false }; placed.set(el, last); el.style.transform = OFF; }
  const rx = Math.round(x);
  const ry = Math.round(y);
  if (shown === last.shown && (!shown || (rx === last.x && ry === last.y))) return;
  last.shown = shown;
  last.x = rx;
  last.y = ry;
  el.style.transform = shown ? `translate(${rx}px, ${ry}px)` : OFF;
}

/** Height of a station label above the point the commander stands at to use it, metres. */
const STATION_LABEL_M = 1.2;
/**
 * At eye level the station within reach is offered as a prompt under the
 * middle of the view (its spot is where the commander stands, so a label
 * there would sit on their back): its anchor, as a fraction of the height.
 */
export const PROMPT_AT = 0.8;

/** The station label is a duel console's own prompt (the marker would repeat it). */
const isDuelConsole = (s: Station | null) => !!s && s.id.startsWith("duel:");

export function FloatingLabels({ runtime, plates, station, deck, duel }: Props) {
  const duelRef = useRef<HTMLDivElement>(null);
  const duelIconRef = useRef<HTMLDivElement>(null);
  const duelAt = useRef<DuelSpot | null>(null);
  duelAt.current = duel ?? null;
  const plateRefs = useRef(new Map<string, HTMLDivElement>());
  const stationRef = useRef<HTMLDivElement>(null);
  const stationAt = useRef<Station | null>(null);
  stationAt.current = station?.station ?? null;
  /** The station is offered with its key (within the commander's reach), not pointed at. */
  const keyed = useRef(false);
  keyed.current = !!station?.key;

  useEffect(() => {
    const placed = new WeakMap<HTMLElement, Placed>();
    const at = { x: 0, y: 0 };
    // Projected through the view on screen; at eye level a label whose anchor a wall hides goes too.
    const place = () => {
      for (const [id, el] of plateRefs.current) {
        const pose = runtime.poses.get(id);
        const y = pose ? pose.y + pose.height + 0.12 : 0;
        const shown = !!pose && !!runtime.toScreen(pose.x, y, pose.z, at) && runtime.inSight(pose.x, y, pose.z);
        put(el, placed, shown, at.x, at.y);
      }
      const s = stationAt.current;
      const el = stationRef.current;
      if (el && s && runtime.eye && keyed.current) {
        put(el, placed, true, runtime.view.vp.width / 2, runtime.view.vp.height * PROMPT_AT);
      } else if (el) {
        const y = s ? s.y + STATION_LABEL_M : 0;
        const shown = !!s && !!runtime.toScreen(s.x, y, s.z, at) && runtime.inSight(s.x, y, s.z);
        put(el, placed, shown, at.x, at.y);
      }
      // The duel arena: a marker over the nearest ring console near the reactor, an icon over the shaft from above.
      const spot = duelAt.current;
      const label = duelRef.current;
      const icon = duelIconRef.current;
      if (label || icon) {
        const pose = spot ? runtime.poses.get(spot.commanderId) : undefined;
        const b = spot && !(keyed.current && isDuelConsole(s)) ? duelBeacon(spot.arena, spot.floorY, runtime.control.mode, pose ?? null) : null;
        const shown = !!b && !!runtime.toScreen(b.x, b.y, b.z, at) && (b.kind === "icon" || runtime.inSight(b.x, b.y, b.z));
        if (label) put(label, placed, shown && b?.kind === "label", at.x, at.y);
        if (icon) put(icon, placed, shown && b?.kind === "icon", at.x, at.y);
      }
    };
    runtime.afterFrame.add(place);
    return () => { runtime.afterFrame.delete(place); };
  }, [runtime, deck]);

  return (
    <div className="verse-plates" aria-hidden>
      {plates.map((p) => (
        <div key={p.id} className="verse-plate" ref={(el) => { if (el) plateRefs.current.set(p.id, el); else plateRefs.current.delete(p.id); }}>
          <div className="verse-plate-box" style={p.accent ? ({ "--verse-plate-accent": p.accent } as CSSProperties) : undefined}>
            <span className="verse-plate-name">{p.name}</span>
            <span className="verse-plate-meta">
              <span className="verse-label">{p.rank}</span>
              <i className="verse-dot" data-state={p.statusKey} />
              <span className="verse-label">{p.status}</span>
            </span>
          </div>
        </div>
      ))}
      {duel && (
        <div className="verse-plate" ref={duelRef} data-testid="verse-duel-marker">
          <div className="verse-station-label verse-duel-marker">
            <b>{duel.label}<kbd className="verse-key">E</kbd></b>
          </div>
        </div>
      )}
      {duel && (
        <div className="verse-plate" ref={duelIconRef} data-testid="verse-duel-icon">
          <div className="verse-duel-arena-icon">
            <svg width="13" height="13" viewBox="0 0 13 13" fill="none" stroke="currentColor" strokeWidth="1.2"><path d={DUEL_ICON} /></svg>
            <span className="verse-label">{duel.label}</span>
          </div>
        </div>
      )}
      {station && (
        <div className="verse-plate" ref={stationRef}>
          <div className="verse-station-label">
            <span className="verse-label">{station.name}</span>
            <b>{station.action}{station.key && <kbd className="verse-key">{station.key}</kbd>}</b>
          </div>
        </div>
      )}
    </div>
  );
}
