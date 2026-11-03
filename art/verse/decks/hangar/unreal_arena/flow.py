"""Flow analysis of the arena (WP11.11): sightlines, spawn spacing, time to contact.

Sight runs eye to eye (1.65 m above the floor) against every box that blocks
sight; glass, grating, railings and the fence do not (destruction.md 2: intact
glass and grating let sight through). Two inputs feed time to contact:

* the walker model here (seeded, deterministic): two players roam the nav
  graph at bot speed, the second spawned by the 9.2 rule; contact is the first
  moment either sees the other;
* bot runs from the harness (WP10) when they exist: a JSON lines log with one
  `{"run": id, "t_contact_s": s}` object per contact (`contacts_from_log`).

The report is plain JSON (`report`), written by unreal_arena_build.py.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path

import numpy as np

from . import layout as L
from .nav import EYE_M, NavGraph

SIGHT_CAP_M = 40.0  # A11.5: longest unbroken sightline
TTC_RANGE_S = (6.0, 15.0)  # A11.5: normal vs normal median time to contact
HIDER_CAP_S = 25.0  # A11.5 / BG12 with the hider model
BOT_SPEED_MPS = 4.8  # a normal-tier bot moving between cover (run, not sprint)
STEP_S = 0.25
PATH_SPACING_M = 20.0  # A11.2


def sight_boxes(layout: L.Layout, pad: float = 2.0) -> np.ndarray:
    """(n, 6) array x0, z0, h0, x1, z1, h1 of the boxes that block sight near the arena."""
    ax0, ax1, az0, az1 = L.ARENA
    rows = [
        (b.x0, b.z0, b.h0, b.x1, b.z1, b.h1)
        for b in layout.boxes
        if b.sight
        and b.x1 > ax0 - pad
        and b.x0 < ax1 + pad
        and b.z1 > az0 - pad
        and b.z0 < az1 + pad
        and b.h1 > -1.0
    ]
    return np.array(rows, dtype=float)


def clear(a: np.ndarray, b: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    """Vectorised segment test: True where the segment a[i] -> b[i] hits no box."""
    a = np.atleast_2d(np.asarray(a, dtype=float))
    b = np.atleast_2d(np.asarray(b, dtype=float))
    out = np.ones(a.shape[0], dtype=bool)
    if boxes.size == 0:
        return out
    lo, hi = boxes[None, :, :3], boxes[None, :, 3:]
    eps = 1e-6
    step = max(1, 4_000_000 // (boxes.shape[0] * 3))
    for s in range(0, a.shape[0], step):
        sa = a[s : s + step, None, :]
        d = b[s : s + step, None, :] - sa
        par = np.abs(d) < 1e-12
        inv = 1.0 / np.where(par, 1.0, d)
        t1 = (lo - sa) * inv
        t2 = (hi - sa) * inv
        # Axis-parallel segments: inside the slab -> (-inf, inf), outside -> empty.
        inside = (sa > lo) & (sa < hi)
        tmin = np.where(par, np.where(inside, -np.inf, np.inf), np.minimum(t1, t2))
        tmax = np.where(par, np.where(inside, np.inf, -np.inf), np.maximum(t1, t2))
        enter = tmin.max(axis=2)
        leave = tmax.min(axis=2)
        hit = (enter <= leave) & (leave > eps) & (enter < 1.0 - eps)
        out[s : s + step] = ~hit.any(axis=1)
    return out


def sample(nav: NavGraph, spacing_m: float = 2.0) -> np.ndarray:
    """Node indices on a coarser lattice (one per spacing x spacing cell and level)."""
    keys = {}
    for i in range(nav.count):
        key = (
            int(nav.xs[i] // spacing_m),
            int(nav.zs[i] // spacing_m),
            nav.level_of(float(nav.hs[i])),
        )
        keys.setdefault(key, i)
    return np.array(sorted(keys.values()))


def sightlines(nav: NavGraph, layout: L.Layout, spacing_m: float = 2.0, chunk: int = 20000) -> dict:
    """Histogram of visible eye-to-eye distances over sampled node pairs."""
    idx = sample(nav, spacing_m)
    eyes = nav.eyes()[idx]
    boxes = sight_boxes(layout)
    ia, ib = np.triu_indices(len(idx), k=1)
    dist = np.linalg.norm(eyes[ia] - eyes[ib], axis=1)
    visible = np.zeros(len(ia), dtype=bool)
    for s in range(0, len(ia), chunk):
        e = slice(s, s + chunk)
        visible[e] = clear(eyes[ia[e]], eyes[ib[e]], boxes)
    vis_d = dist[visible]
    edges = list(range(0, 70, 5))
    hist, _ = np.histogram(vis_d, bins=edges)
    longest = float(vis_d.max()) if vis_d.size else 0.0
    worst = []
    order = np.argsort(-np.where(visible, dist, -1.0))[:10]
    for k in order:
        if not visible[k] or dist[k] <= SIGHT_CAP_M:
            break
        a, b = eyes[ia[k]], eyes[ib[k]]
        worst.append(
            {
                "from": [round(v, 1) for v in a],
                "to": [round(v, 1) for v in b],
                "m": round(float(dist[k]), 1),
            }
        )
    return {
        "samples": int(len(idx)),
        "pairs": int(len(ia)),
        "visible_pairs": int(visible.sum()),
        "bins_m": edges,
        "histogram": hist.tolist(),
        "longest_m": round(longest, 2),
        "over_cap": int((vis_d > SIGHT_CAP_M).sum()),
        "worst": worst,
    }


def spawn_nodes(nav: NavGraph, layout: L.Layout) -> list[int]:
    return [nav.nearest(s.x, s.z, s.h) for s in layout.spawns]


def spawn_spacing(nav: NavGraph, layout: L.Layout) -> dict:
    nodes = spawn_nodes(nav, layout)
    d = nav.distances_from(nodes)[:, nodes]
    names = [s.id for s in layout.spawns]
    pairs = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            pairs.append((float(d[i, j]), names[i], names[j]))
    pairs.sort()
    return {
        "count": len(nodes),
        "min_path_m": round(pairs[0][0], 2) if pairs else 0.0,
        "closest": [{"a": a, "b": b, "m": round(m, 2)} for m, a, b in pairs[:5]],
    }


class _Walker:
    def __init__(self, nav: NavGraph, node: int, rng: np.random.Generator, goals: np.ndarray):
        self.nav, self.node, self.rng, self.goals = nav, node, rng, goals
        self.path: list[int] = []
        self.carry = 0.0

    def pos(self) -> np.ndarray:
        n = self.node
        return np.array([self.nav.xs[n], self.nav.zs[n], self.nav.hs[n] + EYE_M])

    def step(self, metres: float) -> None:
        budget = metres + self.carry
        while budget > 0:
            if not self.path:
                goal = int(self.rng.choice(self.goals))
                self.path = self.nav.path(self.node, goal)[1:]
                if not self.path:
                    break
            nxt = self.path[0]
            seg = math.dist(
                (self.nav.xs[self.node], self.nav.zs[self.node], self.nav.hs[self.node]),
                (self.nav.xs[nxt], self.nav.zs[nxt], self.nav.hs[nxt]),
            )
            if seg > budget:
                break
            budget -= seg
            self.node = nxt
            self.path.pop(0)
        self.carry = budget


def choose_spawn(
    nav: NavGraph, layout: L.Layout, boxes: np.ndarray, opponent: int, spawns: list[int]
) -> int:
    """The 9.2 rule on the grid: out of the opponent's sight if any is, then farthest by path."""
    eye = nav.eyes()[opponent]
    dist = nav.distances_from([opponent])[0]
    probes = []
    for n in spawns:
        base = np.array([nav.xs[n], nav.zs[n], nav.hs[n]])
        seen = clear(
            np.repeat(eye[None], 3, 0),
            base + np.array([[0, 0, 0.3], [0, 0, 1.0], [0, 0, 1.65]]),
            boxes,
        )
        probes.append(bool(seen.any()))
    pool = [n for n, seen in zip(spawns, probes, strict=True) if not seen] or list(spawns)
    return max(pool, key=lambda n: dist[n] if np.isfinite(dist[n]) else -1.0)


def time_to_contact(
    nav: NavGraph, layout: L.Layout, runs: int = 120, seed: int = 11, cap_s: float = 90.0
) -> dict:
    boxes = sight_boxes(layout)
    spawns = spawn_nodes(nav, layout)
    goals = sample(nav, 3.0)
    rng = np.random.default_rng(seed)
    times = []
    for _ in range(runs):
        a_node = int(rng.choice(goals))
        b_node = choose_spawn(nav, layout, boxes, a_node, spawns)
        a, b = _Walker(nav, a_node, rng, goals), _Walker(nav, b_node, rng, goals)
        t = 0.0
        while t < cap_s:
            if clear(a.pos(), b.pos(), boxes)[0] and math.dist(a.pos(), b.pos()) <= 60.0:
                break
            a.step(BOT_SPEED_MPS * STEP_S)
            b.step(BOT_SPEED_MPS * STEP_S)
            t += STEP_S
        times.append(t)
    arr = np.array(times)
    return {
        "model": "walker",
        "runs": runs,
        "seed": seed,
        "speed_mps": BOT_SPEED_MPS,
        "median_s": round(float(np.median(arr)), 2),
        "p10_s": round(float(np.percentile(arr, 10)), 2),
        "p90_s": round(float(np.percentile(arr, 90)), 2),
    }


class _Explorer(_Walker):
    """A seeker that clears the map: its next goal is the nearest sample it has not seen yet."""

    def __init__(self, nav: NavGraph, node: int, rng, samples: np.ndarray, boxes: np.ndarray):
        super().__init__(nav, node, rng, samples)
        self.samples = samples
        self.sample_eyes = nav.eyes()[samples]
        self.unseen = np.ones(len(samples), dtype=bool)
        self.boxes = boxes

    def look(self) -> None:
        todo = np.where(self.unseen)[0]
        if todo.size:
            eye = np.repeat(self.pos()[None], todo.size, 0)
            self.unseen[todo[clear(eye, self.sample_eyes[todo], self.boxes)]] = False

    def step(self, metres: float) -> None:
        if not self.path:
            todo = np.where(self.unseen)[0]
            if todo.size:
                d = np.linalg.norm(self.sample_eyes[todo] - self.pos(), axis=1)
                goal = int(self.samples[todo[int(np.argmin(d))]])
                self.path = self.nav.path(self.node, goal)[1:]
                if not self.path:
                    self.unseen[todo[int(np.argmin(d))]] = False
        super().step(metres)


def hider(
    nav: NavGraph, layout: L.Layout, runs: int = 60, seed: int = 12, cap_s: float = 120.0
) -> dict:
    """BG12 stand-in: the hider camps on one of the least-seen spots, the seeker clears the map."""
    boxes = sight_boxes(layout)
    idx = sample(nav, 3.0)
    eyes = nav.eyes()[idx]
    seen_count = np.zeros(len(idx), dtype=int)
    for i in range(len(idx)):
        seen_count[i] = int(clear(np.repeat(eyes[i][None], len(idx), 0), eyes, boxes).sum())
    hide_spots = idx[np.argsort(seen_count)[:8]]
    rng = np.random.default_rng(seed)
    spawns = spawn_nodes(nav, layout)
    times = []
    for r in range(runs):
        hide = int(hide_spots[r % len(hide_spots)])
        start = choose_spawn(nav, layout, boxes, hide, spawns)
        seeker = _Explorer(nav, start, rng, idx, boxes)
        target = nav.eyes()[hide]
        t = 0.0
        while t < cap_s and not clear(seeker.pos(), target, boxes)[0]:
            seeker.look()
            seeker.step(BOT_SPEED_MPS * STEP_S)
            t += STEP_S
        times.append(t)
    arr = np.array(times)
    return {
        "model": "explorer_vs_camper",
        "runs": runs,
        "hide_spots": [
            [round(float(nav.xs[n]), 2), round(float(nav.zs[n]), 2), round(float(nav.hs[n]), 2)]
            for n in hide_spots
        ],
        "median_s": round(float(np.median(arr)), 2),
        "p90_s": round(float(np.percentile(arr, 90)), 2),
    }


def contacts_from_log(path: Path) -> list[float]:
    """Time-to-contact samples from a harness bot run log (JSON lines)."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(float(json.loads(line)["t_contact_s"]))
    return out


def summarize_contacts(samples: Iterable[float]) -> dict:
    arr = np.array(list(samples), dtype=float)
    if arr.size == 0:
        return {"runs": 0}
    return {"runs": int(arr.size), "median_s": round(float(np.median(arr)), 2)}


def report(
    nav: NavGraph, layout: L.Layout, *, quick: bool = False, bot_log: Path | None = None
) -> dict:
    out = {
        "schema": "verse.arena_flow/1",
        "arena_m": list(L.ARENA),
        "nav": {
            "nodes": nav.count,
            "area_m2": round(nav.area_m2(), 1),
            "extent_m": [round(v, 2) for v in nav.extent()],
            "islands": nav.islands()[:5],
            "level_shares": {k: round(v, 3) for k, v in nav.level_shares().items()},
        },
        "spawns": spawn_spacing(nav, layout),
        "sightlines": sightlines(nav, layout, spacing_m=3.0 if quick else 2.0),
        "time_to_contact": time_to_contact(nav, layout, runs=30 if quick else 120),
        "hider": hider(nav, layout, runs=16 if quick else 60),
    }
    if bot_log is not None and bot_log.is_file():
        out["bot_runs"] = summarize_contacts(contacts_from_log(bot_log))
    return out
