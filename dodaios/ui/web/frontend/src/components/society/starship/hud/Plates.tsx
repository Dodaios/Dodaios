/**
 * Name plates over the crew: a state dot from afar, the name and rank up
 * close, for the agent under the pointer and the selected one. The DOM
 * layer renders the plates once; a driver inside the canvas moves them every
 * frame without React.
 */
import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useRef } from "react";
import { Vector3 } from "three";
import { crewPoses } from "../life/CrewLayer";
import { captain, useShip } from "../shipStore";

const elements = new Map<string, HTMLElement>();

export interface PlateView { agentId: string; name: string; state: string; rank: string; say?: string | null }

export function PlateLayer({ plates, onPick }: { plates: readonly PlateView[]; onPick: (id: string) => void }) {
  return (
    <div className="ship-plates" aria-hidden="false">
      {plates.map((p) => (
        <button key={p.agentId} type="button" className="ship-plate" data-far="true" data-plate={p.agentId}
          ref={(el) => { if (el) elements.set(p.agentId, el); else elements.delete(p.agentId); }}
          onClick={() => onPick(p.agentId)} aria-label={p.name}>
          <span className="ship-dot" data-state={p.state} />
          <span className="ship-plate-text">{p.name}{p.rank ? <span className="ship-plate-rank"> · {p.rank}</span> : null}</span>
          {p.say ? <span className="ship-plate-say">{p.say}</span> : null}
        </button>
      ))}
    </div>
  );
}

const NEAR_CAMERA = 13;
const NEAR_CAPTAIN = 5.5;

export function PlateDriver() {
  const { camera, size } = useThree();
  const v = useRef(new Vector3());
  const open = useRef(new Set<string>());
  useEffect(() => () => open.current.clear(), []);
  useFrame(() => {
    const { selection, hovered } = useShip.getState();
    for (const [id, el] of elements) {
      const pose = crewPoses.get(id);
      if (!pose) { el.style.transform = "translate(-9999px,0)"; continue; }
      v.current.set(pose.x, pose.headY + 0.32, pose.z);
      const dCam = v.current.distanceTo(camera.position);
      v.current.project(camera);
      if (v.current.z > 1 || v.current.x < -1.1 || v.current.x > 1.1 || v.current.y < -1.1 || v.current.y > 1.1) { el.style.transform = "translate(-9999px,0)"; continue; }
      const x = (v.current.x * 0.5 + 0.5) * size.width, y = (-v.current.y * 0.5 + 0.5) * size.height;
      const dCap = Math.hypot(pose.x - captain.x, pose.z - captain.z);
      const focused = (selection?.kind === "agent" && selection.id === id) || (hovered?.kind === "agent" && hovered.id === id);
      const was = open.current.has(id);
      // A little hysteresis, so a plate at the threshold does not flicker.
      const near = focused || dCam < (was ? NEAR_CAMERA + 2 : NEAR_CAMERA) || dCap < (was ? NEAR_CAPTAIN + 1 : NEAR_CAPTAIN);
      if (near) open.current.add(id); else open.current.delete(id);
      const far = near ? "false" : "true";
      if (el.dataset.far !== far) el.dataset.far = far;
      el.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px) translate(-50%, -100%)`;
      el.style.zIndex = String(10000 - Math.round(dCam * 10));
    }
  });
  return null;
}
