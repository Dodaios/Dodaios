/**
 * Packets of light on the data rails: whenever a pane prints something new,
 * one packet leaves its bay along the bay's rail and runs to the Core, which
 * flares when it arrives (`coreSignal`). Real output only: the trigger is the
 * pane's `last_output_at` moving on in the shared pane poll, so a quiet floor
 * sends nothing and a busy one hums.
 *
 * All packets are two instanced meshes (the bright body and its trail); a
 * bay sends at most one packet per `GAP_S`, and at most `MAX_PACKETS` are on
 * the rails at once.
 */
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { AdditiveBlending, Color, DoubleSide, InstancedMesh, Matrix4, MeshBasicMaterial, PlaneGeometry, Quaternion, Vector3 } from "three";
import { useWorkspacePanesStore } from "@/store/workspacePanes";
import { cachedCanvasTexture } from "./canvasMaterials";
import { paneAgentId } from "./codingFloor";
import { coreSignal } from "./FoundryCore";
import { pointAlong, type FoundryFrame, type Rail } from "./foundryLayout";
import { baySignal, glowColour } from "./foundryPalette";
import { GEO } from "./OfficeFurniture";
import type { Department } from "./officeLayout";

const MAX_PACKETS = 48;
const SPEED = 7.5;
const GAP_S = 0.7;

interface Packet { rail: Rail; s: number; colour: Color }

/** Which bay each pane sits in, by the pane's office id. Pure. */
export function deptByAgent(departments: readonly Department[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const dept of departments) for (const desk of dept.desks) if (desk.agentId) map.set(desk.agentId, dept.id);
  return map;
}

/**
 * The panes whose output moved on since `seen`, updating `seen`. The first
 * reading only records (coming up to the floor fires nothing). Pure but for `seen`.
 */
export function freshOutput(
  panes: readonly { workspace_id: string; history_id: string; key: string; last_output_at: number | null }[],
  seen: Map<string, number>, first: boolean,
): string[] {
  const fresh: string[] = [];
  const present = new Set<string>();
  for (const pane of panes) {
    if (pane.last_output_at == null) continue;
    const id = paneAgentId(pane);
    present.add(id);
    const before = seen.get(id);
    seen.set(id, pane.last_output_at);
    if (!first && before !== undefined && pane.last_output_at > before) fresh.push(id);
  }
  // Forget panes that closed, so the record never outgrows the roster.
  for (const id of [...seen.keys()]) if (!present.has(id)) seen.delete(id);
  return fresh;
}

/** A packet's glow trail: brightest at its head, fading backwards (white; tinted per instance). */
function drawTrail(ctx: CanvasRenderingContext2D, w: number, h: number): void {
  const g = ctx.createLinearGradient(0, 0, w, 0);
  g.addColorStop(0, "rgba(255,255,255,0)");
  g.addColorStop(0.85, "rgba(255,255,255,0.7)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.globalCompositeOperation = "destination-in";
  const v = ctx.createLinearGradient(0, 0, 0, h);
  v.addColorStop(0, "rgba(0,0,0,0)");
  v.addColorStop(0.5, "rgba(0,0,0,1)");
  v.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = v;
  ctx.fillRect(0, 0, w, h);
}

const TRAIL_GEOMETRY = new PlaneGeometry(1, 1);

export function FoundryPulses({ frame, departments, animate }: { frame: FoundryFrame; departments: readonly Department[]; animate: boolean }) {
  const panes = useWorkspacePanesStore((s) => s.panes);
  const rails = useMemo(() => new Map(frame.rails.map((r) => [r.deptId, r])), [frame]);
  const bays = useMemo(() => deptByAgent(departments), [departments]);
  const seen = useRef(new Map<string, number>());
  const primed = useRef(false);
  const packets = useRef<Packet[]>([]);
  const lastSent = useRef(new Map<string, number>());
  const clock = useRef(0);

  useEffect(() => {
    const fresh = freshOutput(panes, seen.current, !primed.current);
    primed.current = true;
    if (!animate) return;
    for (const id of fresh) {
      const deptId = bays.get(id);
      const rail = deptId ? rails.get(deptId) : undefined;
      if (!rail || rail.points.length < 2) continue;
      if (clock.current - (lastSent.current.get(rail.deptId) ?? -Infinity) < GAP_S) continue;
      if (packets.current.length >= MAX_PACKETS) break;
      lastSent.current.set(rail.deptId, clock.current);
      packets.current.push({ rail, s: 0, colour: glowColour(baySignal(rail.tint), 2) });
    }
  }, [panes, bays, rails, animate]);

  const materials = useMemo(() => ({
    body: new MeshBasicMaterial({ color: "#ffffff", toneMapped: false }),
    trail: new MeshBasicMaterial({
      map: cachedCanvasTexture("foundry:trail", 128, 16, drawTrail), color: "#ffffff", transparent: true, depthWrite: false,
      blending: AdditiveBlending, toneMapped: false, side: DoubleSide,
    }),
  }), []);
  useEffect(() => () => { materials.body.dispose(); materials.trail.dispose(); }, [materials]);
  const body = useRef<InstancedMesh>(null);
  const trail = useRef<InstancedMesh>(null);
  const tmp = useMemo(() => ({
    m: new Matrix4(), q: new Quaternion(), p: new Vector3(), s: new Vector3(), up: new Vector3(0, 1, 0),
    // The trail's plane lies flat: a quarter turn about x, applied before the packet's heading.
    flat: new Quaternion().setFromAxisAngle(new Vector3(1, 0, 0), -Math.PI / 2),
  }), []);
  const shown = useRef(0);
  useLayoutEffect(() => {
    for (const mesh of [body.current, trail.current]) if (mesh) mesh.count = 0;
  }, []);

  useFrame((_, delta) => {
    const step = Math.min(delta, 0.1);
    clock.current += step;
    const list = packets.current;
    for (let i = list.length - 1; i >= 0; i -= 1) {
      const packet = list[i];
      packet.s += SPEED * step;
      if (packet.s >= packet.rail.lengths[packet.rail.lengths.length - 1]) {
        coreSignal.flash += 0.55;
        list.splice(i, 1);
      }
    }
    const b = body.current, tr = trail.current;
    if (!b || !tr) return;
    // Nothing on the rails and nothing drawn last frame: no upload.
    if (list.length === 0 && shown.current === 0) return;
    shown.current = list.length;
    for (let i = 0; i < list.length; i += 1) {
      const packet = list[i];
      const at = pointAlong(packet.rail, packet.s);
      const yaw = Math.atan2(-at.dz, at.dx);
      tmp.q.setFromAxisAngle(tmp.up, yaw);
      b.setMatrixAt(i, tmp.m.compose(tmp.p.set(at.x, 0.05, at.z), tmp.q, tmp.s.set(0.32, 0.05, 0.08)));
      b.setColorAt(i, packet.colour);
      // The trail lies flat on the floor behind the packet.
      const back = 1.1;
      tmp.q.setFromAxisAngle(tmp.up, yaw).multiply(tmp.flat);
      tr.setMatrixAt(i, tmp.m.compose(tmp.p.set(at.x - at.dx * back / 2, 0.02, at.z - at.dz * back / 2), tmp.q, tmp.s.set(back + 0.3, 0.32, 1)));
      tr.setColorAt(i, packet.colour);
    }
    b.count = list.length;
    tr.count = list.length;
    b.instanceMatrix.needsUpdate = true;
    tr.instanceMatrix.needsUpdate = true;
    if (b.instanceColor) b.instanceColor.needsUpdate = true;
    if (tr.instanceColor) tr.instanceColor.needsUpdate = true;
  });

  return (
    <group>
      <instancedMesh ref={body} args={[GEO.box, materials.body, MAX_PACKETS]} frustumCulled={false} />
      <instancedMesh ref={trail} args={[TRAIL_GEOMETRY, materials.trail, MAX_PACKETS]} frustumCulled={false} renderOrder={3} />
    </group>
  );
}
