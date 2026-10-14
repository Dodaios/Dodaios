/**
 * One instanced mesh for every placement of a part: the floors' dressing
 * (campus ground and fittings, the agents floor's ambience, the building
 * shell, the Foundry deck) draws its repeated pieces through it, a draw call
 * per part instead of one per piece.
 */
import { useLayoutEffect, useRef } from "react";
import { Color, Euler, InstancedMesh, Matrix4, Quaternion, Vector3, type BufferGeometry, type Material } from "three";

export interface Placement {
  position: [number, number, number];
  scale: [number, number, number];
  /** Rotation (x, y, z) in radians; absent = none. */
  rotation?: [number, number, number];
  color?: string;
}

const _m = new Matrix4(), _q = new Quaternion(), _e = new Euler(), _p = new Vector3(), _s = new Vector3(), _c = new Color();

export function Instances({ geometry, material, items, cast = true }: {
  geometry: BufferGeometry; material: Material; items: readonly Placement[]; cast?: boolean;
}) {
  const ref = useRef<InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    items.forEach((item, i) => {
      _e.set(...(item.rotation ?? [0, 0, 0]));
      _m.compose(_p.set(...item.position), _q.setFromEuler(_e), _s.set(...item.scale));
      mesh.setMatrixAt(i, _m);
      if (item.color) mesh.setColorAt(i, _c.set(item.color));
    });
    mesh.count = items.length;
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  }, [items]);
  if (items.length === 0) return null;
  return <instancedMesh key={items.length} ref={ref} args={[geometry, material, items.length]} castShadow={cast} receiveShadow frustumCulled={false} />;
}
