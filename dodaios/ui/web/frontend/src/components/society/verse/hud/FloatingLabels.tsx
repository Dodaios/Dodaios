/**
 * Labels that ride on the scene: the name plate of the crew member under the
 * pointer (or selected), and the label of the station under the pointer.
 * React renders their text; their position is written straight into the DOM
 * after every frame, so a walking officer's plate never lags behind them.
 */
import { useEffect, useRef, type CSSProperties } from "react";
import type { StageRuntime } from "../runtime";
import type { Deck, Station } from "../content/deck";

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
}

export function FloatingLabels({ runtime, plates, station, deck }: Props) {
  const plateRefs = useRef(new Map<string, HTMLDivElement>());
  const stationRef = useRef<HTMLDivElement>(null);
  const stationAt = useRef<Station | null>(null);
  stationAt.current = station?.station ?? null;

  useEffect(() => {
    const place = () => {
      for (const [id, el] of plateRefs.current) {
        const pose = runtime.poses.get(id);
        const at = pose ? runtime.toScreen(pose.x, pose.y + pose.height + 0.12, pose.z) : null;
        el.style.transform = at ? `translate(${Math.round(at.x)}px, ${Math.round(at.y)}px)` : "translate(-9999px, -9999px)";
      }
      const s = stationAt.current;
      const el = stationRef.current;
      if (el) {
        const at = s ? runtime.toScreen(s.x, s.y + 1.2, s.z) : null;
        el.style.transform = at ? `translate(${Math.round(at.x)}px, ${Math.round(at.y)}px)` : "translate(-9999px, -9999px)";
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
