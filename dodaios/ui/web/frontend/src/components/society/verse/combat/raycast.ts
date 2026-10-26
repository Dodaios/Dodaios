/**
 * Segment sweeps: P(t) = A + t·D for t in [0, 1]. Each test returns the
 * entry parameter t (0 when A starts inside) or -1 for a miss, and writes the
 * surface normal into `out`. Allocation-free; the bolts call these every tick.
 */

export interface SweepOut {
  t: number;
  nx: number;
  ny: number;
  nz: number;
}

export function sweepOut(): SweepOut {
  return { t: -1, nx: 0, ny: 0, nz: 0 };
}

/** Axis-aligned box. */
export function sweepBox(
  ax: number, ay: number, az: number, dx: number, dy: number, dz: number,
  x0: number, y0: number, z0: number, x1: number, y1: number, z1: number,
  out: SweepOut,
): number {
  let tmin = 0;
  let tmax = 1;
  let axis = -1;
  let sign = 0;
  // x slab
  if (Math.abs(dx) < 1e-12) {
    if (ax < x0 || ax > x1) return -1;
  } else {
    const inv = 1 / dx;
    let t0 = (x0 - ax) * inv;
    let t1 = (x1 - ax) * inv;
    let s = -1;
    if (t0 > t1) { const tmp = t0; t0 = t1; t1 = tmp; s = 1; }
    if (t0 > tmin) { tmin = t0; axis = 0; sign = s; }
    if (t1 < tmax) tmax = t1;
    if (tmin > tmax) return -1;
  }
  // y slab
  if (Math.abs(dy) < 1e-12) {
    if (ay < y0 || ay > y1) return -1;
  } else {
    const inv = 1 / dy;
    let t0 = (y0 - ay) * inv;
    let t1 = (y1 - ay) * inv;
    let s = -1;
    if (t0 > t1) { const tmp = t0; t0 = t1; t1 = tmp; s = 1; }
    if (t0 > tmin) { tmin = t0; axis = 1; sign = s; }
    if (t1 < tmax) tmax = t1;
    if (tmin > tmax) return -1;
  }
  // z slab
  if (Math.abs(dz) < 1e-12) {
    if (az < z0 || az > z1) return -1;
  } else {
    const inv = 1 / dz;
    let t0 = (z0 - az) * inv;
    let t1 = (z1 - az) * inv;
    let s = -1;
    if (t0 > t1) { const tmp = t0; t0 = t1; t1 = tmp; s = 1; }
    if (t0 > tmin) { tmin = t0; axis = 2; sign = s; }
    if (t1 < tmax) tmax = t1;
    if (tmin > tmax) return -1;
  }
  out.t = tmin;
  out.nx = axis === 0 ? sign : 0;
  out.ny = axis === 1 ? sign : 0;
  out.nz = axis === 2 ? sign : 0;
  if (axis === -1) {
    // Started inside: push back against the travel direction.
    const l = Math.hypot(dx, dy, dz) || 1;
    out.nx = -dx / l; out.ny = -dy / l; out.nz = -dz / l;
  }
  return tmin;
}

/** Vertical cylinder (axis along y) with caps. */
export function sweepCylinder(
  ax: number, ay: number, az: number, dx: number, dy: number, dz: number,
  cx: number, cz: number, r: number, y0: number, y1: number,
  out: SweepOut,
): number {
  const ex = ax - cx;
  const ez = az - cz;
  const c = ex * ex + ez * ez - r * r;
  if (c <= 0 && ay >= y0 && ay <= y1) {
    out.t = 0;
    const l = Math.hypot(ex, ez) || 1;
    out.nx = ex / l; out.ny = 0; out.nz = ez / l;
    return 0;
  }
  let best = -1;
  const a = dx * dx + dz * dz;
  if (a > 1e-12 && c > 0) {
    const b = 2 * (ex * dx + ez * dz);
    const disc = b * b - 4 * a * c;
    if (disc >= 0) {
      const t = (-b - Math.sqrt(disc)) / (2 * a);
      if (t >= 0 && t <= 1) {
        const y = ay + t * dy;
        if (y >= y0 && y <= y1) {
          best = t;
          out.nx = (ex + t * dx) / r; out.ny = 0; out.nz = (ez + t * dz) / r;
        }
      }
    }
  }
  if (Math.abs(dy) > 1e-12) {
    // Top cap from above, bottom cap from below.
    const capY = dy < 0 ? y1 : y0;
    const t = (capY - ay) / dy;
    if (t >= 0 && t <= 1 && (best < 0 || t < best)) {
      const px = ex + t * dx;
      const pz = ez + t * dz;
      if (px * px + pz * pz <= r * r) {
        best = t;
        out.nx = 0; out.ny = dy < 0 ? 1 : -1; out.nz = 0;
      }
    }
  }
  out.t = best;
  return best;
}

export function sweepSphere(
  ax: number, ay: number, az: number, dx: number, dy: number, dz: number,
  cx: number, cy: number, cz: number, r: number,
  out: SweepOut,
): number {
  const ex = ax - cx;
  const ey = ay - cy;
  const ez = az - cz;
  const c = ex * ex + ey * ey + ez * ez - r * r;
  if (c <= 0) {
    const l = Math.hypot(ex, ey, ez) || 1;
    out.t = 0; out.nx = ex / l; out.ny = ey / l; out.nz = ez / l;
    return 0;
  }
  const a = dx * dx + dy * dy + dz * dz;
  if (a < 1e-12) return -1;
  const b = 2 * (ex * dx + ey * dy + ez * dz);
  const disc = b * b - 4 * a * c;
  if (disc < 0) return -1;
  const t = (-b - Math.sqrt(disc)) / (2 * a);
  if (t < 0 || t > 1) return -1;
  out.t = t;
  out.nx = (ex + t * dx) / r; out.ny = (ey + t * dy) / r; out.nz = (ez + t * dz) / r;
  return t;
}

const tmp = sweepOut();

/** Vertical capsule: the segment (cx, yb, cz)–(cx, yt, cz) inflated by r. */
export function sweepCapsule(
  ax: number, ay: number, az: number, dx: number, dy: number, dz: number,
  cx: number, cz: number, yb: number, yt: number, r: number,
  out: SweepOut,
): number {
  let best = -1;
  // The open cylinder between the two sphere centres.
  const ex = ax - cx;
  const ez = az - cz;
  const c = ex * ex + ez * ez - r * r;
  const a = dx * dx + dz * dz;
  if (c <= 0 && ay >= yb && ay <= yt) {
    const l = Math.hypot(ex, ez) || 1;
    out.t = 0; out.nx = ex / l; out.ny = 0; out.nz = ez / l;
    return 0;
  }
  if (a > 1e-12 && c > 0) {
    const b = 2 * (ex * dx + ez * dz);
    const disc = b * b - 4 * a * c;
    if (disc >= 0) {
      const t = (-b - Math.sqrt(disc)) / (2 * a);
      if (t >= 0 && t <= 1) {
        const y = ay + t * dy;
        if (y >= yb && y <= yt) {
          best = t;
          out.nx = (ex + t * dx) / r; out.ny = 0; out.nz = (ez + t * dz) / r;
        }
      }
    }
  }
  for (let k = 0; k < 2; k++) {
    const t = sweepSphere(ax, ay, az, dx, dy, dz, cx, k === 0 ? yb : yt, cz, r, tmp);
    if (t >= 0 && (best < 0 || t < best)) {
      best = t;
      out.nx = tmp.nx; out.ny = tmp.ny; out.nz = tmp.nz;
    }
  }
  out.t = best;
  return best;
}

/** Closest approach of a moving point to a vertical axis, for "will this bolt pass near me". */
export function closestApproachXZ(px: number, pz: number, vx: number, vz: number, cx: number, cz: number): { t: number; dist: number } {
  const ex = cx - px;
  const ez = cz - pz;
  const vv = vx * vx + vz * vz;
  const t = vv > 1e-12 ? (ex * vx + ez * vz) / vv : 0;
  const qx = px + vx * t - cx;
  const qz = pz + vz * t - cz;
  return { t, dist: Math.hypot(qx, qz) };
}
