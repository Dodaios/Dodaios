"""Draw the Dodaios orb scene on the desktop figure.

The page plays the vendored Three.js scene (MIT, cyber1443; see
``third_party/orb-web-animation/LICENSE``). This process has the same OpenGL
window the shader pets use, so it draws that scene: the icosahedron, the
inner core, the particles, the filaments and the rings. Pointer drag stays
on the page.
"""

from __future__ import annotations

import array
import math
from dataclasses import dataclass, field

from dodaios.ui.pets.states import PET_STATES

#: Sentinel the shader host forwards. The GL process draws the scene
#: instead of compiling this as a fragment.
JARVIS_ORB_SOURCE = "// scene jarvis-orb"

# Avatar preset and the compact branch (preset.px <= 120), matching the page.
_PARTICLES = 165
_FILAMENTS = 18
_RING_SEGMENTS = 128
_SCENE_SCALE = 0.82
_CORE = (0xEA / 255, 0xFF / 255, 0xFF / 255)
_PRIMARY = (0x38 / 255, 0xF4 / 255, 0xFF / 255)
_SECONDARY = (0x19 / 255, 0xA8 / 255, 0xFF / 255)
_TERTIARY = (0x7F / 255, 0xFF / 255, 0xEE / 255)

# Same targets as dodaiosOrb/mood.ts. Objects, so success and error do not snap back.
_MOODS: dict[str, dict[str, float]] = {
    "idle": {
        "energy": 0.72, "rotation_speed": 0.48, "particle_speed": 0.55,
        "shell_radius": 1.0, "ring_spread": 0.88, "filament_opacity": 0.34,
        "core_scale": 0.92, "bloom": 0.55,
    },
    "listening": {
        "energy": 1.35, "rotation_speed": 0.6, "particle_speed": 1.55,
        "shell_radius": 1.08, "ring_spread": 1.0, "filament_opacity": 0.7,
        "core_scale": 1.1, "bloom": 0.9,
    },
    "thinking": {
        "energy": 1.08, "rotation_speed": 1.35, "particle_speed": 1.24,
        "shell_radius": 1.06, "ring_spread": 1.06, "filament_opacity": 0.5,
        "core_scale": 1.05, "bloom": 0.82,
    },
    "talking": {
        "energy": 1.2, "rotation_speed": 0.9, "particle_speed": 1.45,
        "shell_radius": 1.06, "ring_spread": 1.06, "filament_opacity": 0.62,
        "core_scale": 1.05, "bloom": 0.82,
    },
    "success": {
        "energy": 1.24, "rotation_speed": 0.82, "particle_speed": 1.08,
        "shell_radius": 1.12, "ring_spread": 1.16, "filament_opacity": 0.64,
        "core_scale": 1.18, "bloom": 1.0,
    },
    "error": {
        "energy": 0.94, "rotation_speed": 0.92, "particle_speed": 0.92,
        "shell_radius": 1.04, "ring_spread": 0.98, "filament_opacity": 0.46,
        "core_scale": 1.0, "bloom": 0.74,
    },
    "sleeping": {
        "energy": 0.35, "rotation_speed": 0.16, "particle_speed": 0.22,
        "shell_radius": 0.92, "ring_spread": 0.72, "filament_opacity": 0.12,
        "core_scale": 0.78, "bloom": 0.28,
    },
    "working": {
        "energy": 0.9, "rotation_speed": 0.72, "particle_speed": 0.85,
        "shell_radius": 1.02, "ring_spread": 0.96, "filament_opacity": 0.42,
        "core_scale": 1.0, "bloom": 0.66,
    },
    "searching": {
        "energy": 1.12, "rotation_speed": 1.55, "particle_speed": 1.4,
        "shell_radius": 1.1, "ring_spread": 1.18, "filament_opacity": 0.55,
        "core_scale": 1.02, "bloom": 0.8,
    },
    "held": {
        "energy": 0.6, "rotation_speed": 0.22, "particle_speed": 0.4,
        "shell_radius": 1.14, "ring_spread": 0.8, "filament_opacity": 0.3,
        "core_scale": 1.18, "bloom": 0.5,
    },
}
_PULSE = {"idle": 0.2, "thinking": 0.62, "success": 1.25, "error": 0.88}
_FIELDS = (
    "energy", "rotation_speed", "particle_speed", "shell_radius",
    "ring_spread", "filament_opacity", "core_scale", "bloom",
)


def mood_for(state: str) -> dict[str, float]:
    return _MOODS.get(state, _MOODS["idle"])


@dataclass
class Motion:
    """Eased mood plus the spins that accumulate between frames."""

    energy: float = 0.72
    rotation_speed: float = 0.48
    particle_speed: float = 0.55
    shell_radius: float = 1.0
    ring_spread: float = 0.88
    filament_opacity: float = 0.34
    core_scale: float = 0.92
    bloom: float = 0.55
    shown_energy: float = 0.72
    root_x: float = 0.0
    root_y: float = 0.0
    particle_y: float = 0.0
    packet_x: float = 0.0
    packet_y: float = 0.0
    filament_y: float = 0.0
    core_rx: float = 0.0
    core_ry: float = 0.0
    pulse: float = 0.15
    elapsed: float = 0.0
    last_t: float | None = None
    state: str = ""


def step_motion(motion: Motion, state: str, t: float, level: float) -> Motion:
    """Ease toward ``state`` and advance the spins. ``t`` is seconds from show."""
    dt = 0.0 if motion.last_t is None else min(0.05, max(0.0, t - motion.last_t))
    motion.last_t = t
    motion.elapsed = t
    if motion.state != state:
        motion.pulse = max(motion.pulse, _PULSE.get(state, 0.62))
        motion.state = state
    # The page eases 8% of the gap per frame at 60fps.
    amount = 1.0 - (0.92 ** (dt * 60.0))
    target = mood_for(state)
    for name in _FIELDS:
        current = getattr(motion, name)
        setattr(motion, name, current + (target[name] - current) * amount)
    motion.pulse *= 0.925 ** (dt * 60.0)
    motion.shown_energy = motion.energy
    if level > 0.01 and state in ("listening", "talking"):
        motion.shown_energy = target["energy"] * (0.65 + 0.7 * level)
    motion.root_y += dt * motion.rotation_speed * 0.72
    motion.root_x = math.sin(t * 0.32) * 0.055
    motion.particle_y -= dt * (0.13 + motion.rotation_speed * 0.08)
    motion.packet_y += dt * (0.16 + motion.rotation_speed * 0.1)
    motion.packet_x = math.sin(t * 0.26) * 0.07
    motion.filament_y += dt * (0.09 + motion.rotation_speed * 0.05)
    motion.core_rx += dt * (0.18 + motion.rotation_speed * 0.12)
    motion.core_ry -= dt * (0.22 + motion.rotation_speed * 0.18)
    return motion


@dataclass
class _Ring:
    kind: str
    blob: bytes
    count: int
    tilt_x: float
    tilt_y: float
    speed: float
    opacity: float
    color: tuple[float, float, float]
    z: float = 0.0
    spoke: bool = False


@dataclass
class _Filaments:
    a: list[tuple[float, float, float]]
    b: list[tuple[float, float, float]]
    seeds: list[float]


@dataclass
class Scene:
    core: bytes
    core_count: int
    inner: bytes
    inner_count: int
    particles: bytes
    particle_count: int
    packets: bytes
    packet_count: int
    filaments: _Filaments
    rings: list[_Ring] = field(default_factory=list)

    @property
    def filament_count(self) -> int:
        return len(self.filaments.seeds)

    @property
    def dashed(self) -> list[_Ring]:
        return [ring for ring in self.rings if ring.kind == "line" and not ring.spoke]

    @property
    def flat(self) -> list[_Ring]:
        return [ring for ring in self.rings if ring.kind == "flat"]

    @property
    def spoke_count(self) -> int:
        spoke = next(ring for ring in self.rings if ring.spoke)
        return spoke.count // 2


def _pack(values: list[float]) -> bytes:
    return array.array("f", values).tobytes()


def _seeded(seed: float) -> float:
    value = math.sin(seed * 12.9898) * 43758.5453
    return value - math.floor(value)


def _sphere_point(index: int, count: int, radius: float = 1.0) -> tuple[float, float, float]:
    offset = 2 / count
    increment = math.pi * (3 - math.sqrt(5))
    y = index * offset - 1 + offset / 2
    radial = math.sqrt(max(0.0, 1 - y * y))
    phi = index * increment
    return (
        math.cos(phi) * radial * radius,
        y * radius,
        math.sin(phi) * radial * radius,
    )


def _unit(x: float, y: float, z: float) -> tuple[float, float, float]:
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / length, y / length, z / length)


def _midpoint(
    verts: list[tuple[float, float, float]],
    cache: dict[tuple[int, int], int],
    i: int,
    j: int,
) -> int:
    key = (i, j) if i < j else (j, i)
    found = cache.get(key)
    if found is not None:
        return found
    ax, ay, az = verts[i]
    bx, by, bz = verts[j]
    cache[key] = len(verts)
    verts.append(_unit(ax + bx, ay + by, az + bz))
    return cache[key]


def _icosahedron(radius: float, detail: int) -> tuple[bytes, int]:
    golden = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [
        _unit(*point)
        for point in (
            (-1, golden, 0), (1, golden, 0), (-1, -golden, 0), (1, -golden, 0),
            (0, -1, golden), (0, 1, golden), (0, -1, -golden), (0, 1, -golden),
            (golden, 0, -1), (golden, 0, 1), (-golden, 0, -1), (-golden, 0, 1),
        )
    ]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    for _ in range(detail):
        cache: dict[tuple[int, int], int] = {}
        nxt: list[tuple[int, int, int]] = []
        for a, b, c in faces:
            ab = _midpoint(verts, cache, a, b)
            bc = _midpoint(verts, cache, b, c)
            ca = _midpoint(verts, cache, c, a)
            nxt.extend(((a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)))
        faces = nxt
    data: list[float] = []
    for a, b, c in faces:
        for index in (a, b, c):
            x, y, z = verts[index]
            data.extend((x * radius, y * radius, z * radius, x, y, z))
    return _pack(data), len(faces) * 3


def _sphere(radius: float, width: int, height: int) -> tuple[bytes, int]:
    verts: list[tuple[float, float, float]] = []
    for y in range(height + 1):
        theta = y / height * math.pi
        for x in range(width + 1):
            phi = x / width * math.tau
            verts.append(
                (
                    math.sin(theta) * math.cos(phi) * radius,
                    math.cos(theta) * radius,
                    math.sin(theta) * math.sin(phi) * radius,
                )
            )
    data: list[float] = []

    def at(x: int, y: int) -> int:
        return y * (width + 1) + x

    for y in range(height):
        for x in range(width):
            a, b = at(x, y), at(x + 1, y)
            c, d = at(x, y + 1), at(x + 1, y + 1)
            for index in (a, c, b, b, c, d):
                data.extend(verts[index])
    return _pack(data), len(data) // 3


def _torus(radius: float, tube: float, radial: int, tubular: int) -> tuple[bytes, int]:
    def point(i: int, j: int) -> tuple[float, float, float]:
        u = i / tubular * math.tau
        v = j / radial * math.tau
        ring = radius + tube * math.cos(v)
        return (ring * math.cos(u), ring * math.sin(u), tube * math.sin(v))

    data: list[float] = []
    for j in range(radial):
        for i in range(tubular):
            corners = (point(i, j), point(i + 1, j), point(i, j + 1), point(i + 1, j + 1))
            a, b, c, d = corners
            for item in (a, c, b, b, c, d):
                data.extend(item)
    return _pack(data), len(data) // 3


def _dashed_ring(radius: float, segments: int, seed: float) -> tuple[bytes, int]:
    data: list[float] = []
    for i in range(segments):
        if _seeded(i * 2.17 + seed) <= 0.34:
            continue
        start = (i / segments) * math.tau
        end = ((i + 0.64 + _seeded(i + seed) * 0.18) / segments) * math.tau
        data.extend((math.cos(start) * radius, math.sin(start) * radius, 0.0))
        data.extend((math.cos(end) * radius, math.sin(end) * radius, 0.0))
    count = len(data) // 3
    return _pack(data), count


def _flat_ring(
    radius: float,
    radial: float,
    depth: float,
    segments: int,
    gap: float,
    dashes: int,
    seed: float,
) -> tuple[bytes, int]:
    outer = radius + radial / 2
    inner = radius - radial / 2
    top, bottom = depth / 2, -depth / 2

    def active(index: int) -> bool:
        if gap <= 0 or dashes <= 0:
            return True
        local = ((index / segments) * dashes + seed) % 1
        return local > gap

    data: list[float] = []

    def quad(
        a: tuple[float, float, float],
        b: tuple[float, float, float],
        c: tuple[float, float, float],
        d: tuple[float, float, float],
        normal: tuple[float, float, float],
    ) -> None:
        for point in (a, b, c, a, c, d):
            data.extend(point)
            data.extend(normal)

    for i in range(segments):
        if not active(i):
            continue
        a0 = (i / segments) * math.tau
        a1 = ((i + 1) / segments) * math.tau
        x, y = math.cos(a0), math.sin(a0)
        nx, ny = math.cos(a1), math.sin(a1)
        outer_top = (x * outer, y * outer, top)
        outer_top_n = (nx * outer, ny * outer, top)
        inner_top = (x * inner, y * inner, top)
        inner_top_n = (nx * inner, ny * inner, top)
        outer_bot = (x * outer, y * outer, bottom)
        outer_bot_n = (nx * outer, ny * outer, bottom)
        inner_bot = (x * inner, y * inner, bottom)
        inner_bot_n = (nx * inner, ny * inner, bottom)
        quad(outer_top, outer_top_n, inner_top_n, inner_top, (0.0, 0.0, 1.0))
        quad(outer_bot, inner_bot, inner_bot_n, outer_bot_n, (0.0, 0.0, -1.0))
        quad(outer_top, outer_bot, outer_bot_n, outer_top_n, _unit(x + nx, y + ny, 0.0))
        quad(inner_top, inner_top_n, inner_bot_n, inner_bot, _unit(-(x + nx), -(y + ny), 0.0))
        if not active((i - 1 + segments) % segments):
            quad(outer_top, inner_top, inner_bot, outer_bot, _unit(-y, x, 0.0))
        if not active((i + 1) % segments):
            quad(outer_top_n, outer_bot_n, inner_bot_n, inner_top_n, _unit(ny, -nx, 0.0))
    return _pack(data), len(data) // 6


def _spokes(count: int) -> tuple[bytes, int]:
    data: list[float] = []
    for i in range(count):
        if _seeded(i + 9.2) < 0.22:
            continue
        angle = (i / count) * math.tau + _seeded(i + 81) * 0.04
        inner = 0.18 + _seeded(i + 22) * 0.12
        outer = 0.7 + _seeded(i + 41) * 0.48
        data.extend((math.cos(angle) * inner, math.sin(angle) * inner * 0.72, 0.0))
        data.extend((math.cos(angle) * outer, math.sin(angle) * outer * 0.72, 0.0))
    return _pack(data), len(data) // 3


def _particles(count: int) -> tuple[bytes, int]:
    data: list[float] = []
    for i in range(count):
        base = _sphere_point(i, count, 1.05 * (0.88 + _seeded(i + 2.1) * 0.26))
        jitter = 0.965 + _seeded(i + 11.4) * 0.075
        data.extend((base[0] * jitter, base[1] * jitter, base[2] * jitter, _seeded(i + 41.2)))
    return _pack(data), count


def _packets(count: int) -> tuple[bytes, int]:
    data: list[float] = []
    for i in range(count):
        direction = _sphere_point(math.floor(_seeded(i + 71.2) * 1200), 1200, 1.0)
        data.extend(direction)
        data.append(_seeded(i + 95.4))
        data.append(1.0 if _seeded(i + 18.1) > 0.48 else -1.0)
    return _pack(data), count


def _make_filaments(count: int) -> _Filaments:
    a: list[tuple[float, float, float]] = []
    b: list[tuple[float, float, float]] = []
    seeds: list[float] = []
    for i in range(count):
        seed = _seeded(i + 12.7)
        p1 = _sphere_point(math.floor(_seeded(i + 4.1) * 900), 900, 0.34 + _seeded(i + 8.2) * 0.42)
        if seed > 0.62:
            p2 = _sphere_point(
                math.floor(_seeded(i + 44.1) * 900), 900, 0.86 + _seeded(i + 32.3) * 0.32
            )
        else:
            length = math.sqrt(p1[0] ** 2 + p1[1] ** 2 + p1[2] ** 2) or 1.0
            reach = 0.86 + _seeded(i + 32.3) * 0.32
            p2 = (p1[0] / length * reach, p1[1] / length * reach, p1[2] / length * reach)
        a.append(p1)
        b.append(p2)
        seeds.append(seed)
    return _Filaments(a, b, seeds)


def filament_bytes(filaments: _Filaments, time: float, shell: float, pulse: float) -> bytes:
    data: list[float] = []
    for i, seed in enumerate(filaments.seeds):
        wave = math.sin(time * (0.72 + seed * 1.8) + seed * 17.0)
        scale_a = 0.9 + wave * 0.025 + pulse * 0.025
        scale_b = shell + wave * 0.035 + pulse * 0.055
        ax, ay, az = filaments.a[i]
        bx, by, bz = filaments.b[i]
        data.extend((ax * scale_a, ay * scale_a, az * scale_a))
        data.extend((bx * scale_b, by * scale_b, bz * scale_b))
    return _pack(data)


def build_scene() -> Scene:
    """The avatar-sized scene the page builds. Geometry does not depend on GL."""
    core, core_count = _icosahedron(0.3, 3)
    inner, inner_count = _sphere(0.095, 24, 12)
    particles, particle_count = _particles(_PARTICLES)
    packets, packet_count = _packets(max(34, round(_PARTICLES * 0.11)))
    rings: list[_Ring] = []
    dashed = (
        (0.5, 0.96, -0.18, 0.36, 0.82, 2.4),
        (0.72, -0.58, 0.32, -0.54, 0.9, 8.8),
        (0.91, 0.25, 1.0, 0.44, 0.82, 15.5),
        (1.12, -0.14, -0.7, -0.22, 0.68, 24.1),
    )
    for radius, tilt_x, tilt_y, speed, opacity, seed in dashed:
        blob, count = _dashed_ring(radius, _RING_SEGMENTS, seed)
        rings.append(_Ring("line", blob, count, tilt_x, tilt_y, speed, opacity, _SECONDARY))
        tube = 0.0045 + radius * 0.0025
        band, band_count = _torus(radius, tube, 6, _RING_SEGMENTS)
        rings.append(
            _Ring(
                "band", band, band_count, tilt_x, tilt_y, speed * 0.72,
                opacity * 0.16, _PRIMARY,
            )
        )
    flats = (
        (0.56, 0.038, 0.048, 0.0, 0, 0.0, 0.72, -0.34, -0.34, 0.12),
        (0.69, 0.088, 0.032, 0.32, 1, 0.11, 0.2, 0.72, 0.34, 0.11),
        (0.84, 0.054, 0.076, 0.36, 4, 0.43, -0.34, 0.92, 0.26, 0.1),
        (1.02, 0.112, 0.028, 0.46, 1, 0.27, -0.92, -0.18, -0.2, 0.09),
        (1.17, 0.03, 0.09, 0.22, 3, 0.62, -0.2, -0.86, -0.28, 0.08),
    )
    for radius, radial, depth, gap, dashes, seed, tilt_x, tilt_y, speed, opacity in flats:
        blob, count = _flat_ring(radius, radial, depth, _RING_SEGMENTS, gap, dashes, seed)
        rings.append(_Ring("flat", blob, count, tilt_x, tilt_y, speed, opacity, _PRIMARY))
    spoke_blob, spoke_count = _spokes(max(26, round(_RING_SEGMENTS * 0.44)))
    rings.append(
        _Ring(
            "line", spoke_blob, spoke_count, 1.16, 0.0, -0.18, 0.12, _TERTIARY, spoke=True,
        )
    )
    # The spokes also carry a fixed tilt on Z. Stored as the starting spin.
    rings[-1].z = 0.2
    return Scene(
        core, core_count, inner, inner_count, particles, particle_count,
        packets, packet_count, _make_filaments(_FILAMENTS), rings,
    )


def _advance_rings(motion: Motion, rings: list[_Ring], dt: float) -> None:
    for ring in rings:
        ring.z += dt * ring.speed * motion.rotation_speed
        if ring.spoke:
            ring.z -= dt * (0.12 + motion.rotation_speed * 0.18)


# -- matrices, column-major ----------------------------------------------

def _mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return out


def _scale(s: float) -> list[float]:
    return [s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1]


def _euler(x: float, y: float, z: float) -> list[float]:
    """Three.js XYZ euler, column-major."""
    a, b = math.cos(x), math.sin(x)
    c, d = math.cos(y), math.sin(y)
    e, f = math.cos(z), math.sin(z)
    ae, af, be, bf = a * e, a * f, b * e, b * f
    return [
        c * e, af + be * d, bf - ae * d, 0.0,
        -c * f, ae - bf * d, be + af * d, 0.0,
        d, -b * c, a * c, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _perspective(fov_deg: float, aspect: float) -> list[float]:
    near, far = 0.1, 100.0
    focal = 1.0 / math.tan(math.radians(fov_deg) / 2)
    return [
        focal / aspect, 0, 0, 0,
        0, focal, 0, 0,
        0, 0, (far + near) / (near - far), -1,
        0, 0, (2 * far * near) / (near - far), 0,
    ]


def _view() -> list[float]:
    # Camera at (0, 0, 4.1) looking at the origin. Up is +Y.
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -4.1, 1]


def _qmat(column_major: list[float]) -> object:
    from PySide6.QtGui import QMatrix4x4

    values = [column_major[col * 4 + row] for row in range(4) for col in range(4)]
    return QMatrix4x4(*values)


_CORE_VERT = """#version 150
uniform mat4 uMvp;
uniform mat4 uModelView;
in vec3 aPos;
in vec3 aNrm;
out vec3 vNormal;
out vec3 vView;
void main() {
  vec4 mv = uModelView * vec4(aPos, 1.0);
  vNormal = mat3(uModelView) * aNrm;
  vView = normalize(-mv.xyz);
  gl_Position = uMvp * vec4(aPos, 1.0);
}
"""

_CORE_FRAG = """#version 150
uniform vec3 uCore;
uniform vec3 uPrimary;
uniform float uEnergy;
uniform float uPulse;
uniform float uTime;
in vec3 vNormal;
in vec3 vView;
out vec4 fragColor;
void main() {
  vec3 n = normalize(vNormal);
  float fresnel = pow(1.0 - max(dot(n, normalize(vView)), 0.0), 2.35);
  // The page's spatial shimmer is a faint additive glow. Here it draws gray bars.
  float shimmer = 0.92 + 0.08 * sin(uTime * 3.2);
  float alpha = 0.17 + fresnel * (0.72 + uEnergy * 0.16) + uPulse * 0.16;
  vec3 color = mix(uPrimary, uCore, 0.58 + fresnel * 0.38);
  color *= shimmer * (0.8 + uEnergy * 0.34 + uPulse * 0.4);
  alpha = clamp(alpha, 0.0, 1.0);
  fragColor = vec4(min(color, vec3(1.0)) * alpha, alpha);
}
"""

_FLAT_VERT = """#version 150
uniform mat4 uMvp;
uniform mat4 uModelView;
in vec3 aPos;
in vec3 aNrm;
out vec3 vObjectNormal;
out vec3 vViewNormal;
out vec3 vView;
void main() {
  vec4 mv = uModelView * vec4(aPos, 1.0);
  vObjectNormal = normalize(aNrm);
  vViewNormal = normalize(mat3(uModelView) * aNrm);
  vView = normalize(-mv.xyz);
  gl_Position = uMvp * vec4(aPos, 1.0);
}
"""

_FLAT_FRAG = """#version 150
uniform vec3 uColor;
uniform float uOpacity;
uniform float uPulse;
uniform float uTime;
in vec3 vObjectNormal;
in vec3 vViewNormal;
in vec3 vView;
out vec4 fragColor;
void main() {
  float cap = smoothstep(0.58, 0.96, abs(vObjectNormal.z));
  float side = 1.0 - cap;
  float fresnel = pow(1.0 - max(dot(normalize(vViewNormal), normalize(vView)), 0.0), 2.2);
  float shimmer = 0.86 + 0.14 * sin(uTime * 2.0 + vObjectNormal.x * 18.0 + vObjectNormal.y * 9.0);
  vec3 sideColor = uColor * vec3(0.38, 0.72, 0.86);
  vec3 color = mix(sideColor, uColor * 1.34, cap) * shimmer;
  float alpha = uOpacity * (0.54 + cap * 0.48 + side * 0.18 + fresnel * 0.34 + uPulse * 0.22);
  alpha = clamp(alpha, 0.0, 1.0);
  fragColor = vec4(min(color, vec3(1.0)) * alpha, alpha);
}
"""

_POINT_VERT = """#version 150
in vec3 aPos;
in float aSeed;
uniform mat4 uMvp;
uniform mat4 uModelView;
uniform float uTime;
uniform float uEnergy;
uniform float uPulse;
uniform float uPointScale;
uniform float uPixelRatio;
out float vAlpha;
out float vMix;
void main() {
  float wobble = sin(uTime * (0.22 + aSeed * 0.24) + aSeed * 31.0) * 0.025;
  vec3 p = aPos * (1.0 + wobble * uEnergy + uPulse * 0.035);
  vec4 mv = uModelView * vec4(p, 1.0);
  gl_Position = uMvp * vec4(p, 1.0);
  float twinkle = 0.5 + 0.5 * sin(uTime * (1.3 + aSeed * 2.2) + aSeed * 64.0);
  vAlpha = (0.24 + twinkle * 0.82) * (0.58 + uEnergy * 0.34 + uPulse * 0.32);
  vMix = twinkle;
  gl_PointSize = uPixelRatio * uPointScale * (1.08 + twinkle * 1.38 + uPulse * 0.48)
      * (3.0 / max(0.7, -mv.z));
}
"""

_POINT_FRAG = """#version 150
in float vAlpha;
in float vMix;
uniform vec3 uPrimary;
uniform vec3 uAccent;
out vec4 fragColor;
void main() {
  vec2 p = gl_PointCoord.xy - 0.5;
  float alpha = clamp(smoothstep(0.5, 0.0, length(p)) * vAlpha, 0.0, 1.0);
  vec3 color = min(mix(uPrimary, uAccent, vMix * 0.5), vec3(1.0));
  fragColor = vec4(color * alpha, alpha);
}
"""

_PACKET_VERT = """#version 150
in vec3 aPos;
in float aSeed;
in float aDirection;
uniform mat4 uMvp;
uniform mat4 uModelView;
uniform float uTime;
uniform float uEnergy;
uniform float uPulse;
uniform float uPointScale;
uniform float uPixelRatio;
out float vAlpha;
out float vMix;
mat2 rot(float a) {
  float c = cos(a);
  float s = sin(a);
  return mat2(c, -s, s, c);
}
void main() {
  vec3 dir = normalize(aPos);
  float speed = 0.17 + aSeed * 0.15;
  float phase = fract(uTime * speed + aSeed * 1.73);
  float travel = aDirection > 0.0 ? phase : 1.0 - phase;
  float radius = mix(0.14, 1.2 + uPulse * 0.04, travel);
  dir.xz = rot(uTime * (0.07 + aSeed * 0.08) + travel * 0.34) * dir.xz;
  dir.xy = rot(sin(uTime * 0.22 + aSeed * 8.0) * 0.06) * dir.xy;
  vec3 p = dir * radius;
  vec4 mv = uModelView * vec4(p, 1.0);
  gl_Position = uMvp * vec4(p, 1.0);
  float head = smoothstep(0.0, 0.14, phase) * (1.0 - smoothstep(0.84, 1.0, phase));
  float coreBoost = 1.0 - smoothstep(0.0, 0.42, abs(travel - 0.5));
  vAlpha = head * (0.46 + coreBoost * 0.24) * (0.74 + uEnergy * 0.28 + uPulse * 0.34);
  vMix = travel;
  gl_PointSize = uPixelRatio * uPointScale * (1.0 + coreBoost * 0.7 + uPulse * 0.36)
      * (3.0 / max(0.72, -mv.z));
}
"""

_PACKET_FRAG = """#version 150
in float vAlpha;
in float vMix;
uniform vec3 uCore;
uniform vec3 uPrimary;
out vec4 fragColor;
void main() {
  vec2 p = gl_PointCoord.xy - 0.5;
  float alpha = clamp(smoothstep(0.5, 0.0, length(p)) * vAlpha, 0.0, 1.0);
  vec3 color = min(mix(uCore, uPrimary, 0.42 + vMix * 0.4), vec3(1.0));
  fragColor = vec4(color * alpha, alpha);
}
"""

_BASIC_VERT = """#version 150
uniform mat4 uMvp;
in vec3 aPos;
void main() { gl_Position = uMvp * vec4(aPos, 1.0); }
"""

_BASIC_FRAG = """#version 150
uniform vec3 uColor;
uniform float uOpacity;
out vec4 fragColor;
void main() {
  float alpha = clamp(uOpacity, 0.0, 1.0);
  fragColor = vec4(min(uColor, vec3(1.0)) * alpha, alpha);
}
"""

_HALO_VERT = """#version 150
uniform mat4 uView;
uniform mat4 uModel;
uniform mat4 uProj;
uniform float uSize;
in vec2 aPos;
out vec2 vCorner;
void main() {
  vec4 center = uView * uModel * vec4(0.0, 0.0, 0.0, 1.0);
  vCorner = aPos;
  gl_Position = uProj * vec4(center.xy + aPos * uSize, center.z, 1.0);
}
"""

_HALO_FRAG = """#version 150
uniform vec3 uColor;
uniform float uOpacity;
in vec2 vCorner;
out vec4 fragColor;
void main() {
  float r = length(vCorner);
  float alpha = 0.0;
  vec3 col = vec3(1.0);
  if (r < 0.18) {
    float u = r / 0.18;
    alpha = mix(0.92, 0.62, u);
    col = mix(vec3(1.0), uColor, u);
  } else if (r < 0.48) {
    float u = (r - 0.18) / 0.30;
    alpha = mix(0.62, 0.18, u);
    col = uColor;
  } else if (r < 1.0) {
    float u = (r - 0.48) / 0.52;
    alpha = mix(0.18, 0.0, u);
    col = uColor;
  }
  col = min(col * uColor, vec3(1.0));
  alpha = clamp(alpha * uOpacity, 0.0, 1.0);
  fragColor = vec4(col * alpha, alpha);
}
"""


class _Gpu:
    def __init__(self, scene: Scene) -> None:
        self.scene = scene
        self.motion = Motion()
        self._ready = False
        self._programs: dict[str, object] = {}
        self._buffers: list[tuple[object, object, int]] = []
        self._filament: tuple[object, object] | None = None
        self._fbo: object = None
        self._size = (0, 0)

    def frame(
        self,
        width: int,
        height: int,
        t: float,
        state: str,
        level: float,
    ) -> object:
        self._prepare()
        self._ensure_fbo(width, height)
        before = self.motion.last_t
        step_motion(self.motion, state, t, level)
        dt = 0.0 if before is None else min(0.05, max(0.0, t - before))
        _advance_rings(self.motion, self.scene.rings, dt)
        gl = self._gl()
        fbo = self._fbo
        assert fbo is not None
        fbo.bind()
        gl.glViewport(0, 0, width, height)
        gl.glDisable(0x0B71)  # GL_DEPTH_TEST
        gl.glDisable(0x0B44)  # GL_CULL_FACE
        gl.glEnable(0x0BE2)  # GL_BLEND
        # shortcut: the page adds the glow, which disappears on a light wallpaper.
        # Coverage keeps the same parts visible through the desktop window.
        gl.glBlendFuncSeparate(1, 0x0303, 1, 0x0303)  # ONE, ONE_MINUS_SRC_ALPHA
        gl.glEnable(0x8642)  # GL_PROGRAM_POINT_SIZE
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(0x00004000)
        proj = _perspective(35.0, width / max(1, height))
        view = _view()
        self._draw(gl, proj, view, width)
        image = fbo.toImage()
        fbo.release()
        gl.glDisable(0x0BE2)
        gl.glDisable(0x8642)
        return image

    def _draw(self, gl: object, proj: list[float], view: list[float], width: int) -> None:
        motion = self.motion
        root = _mul(_euler(motion.root_x, motion.root_y, 0.0), _scale(_SCENE_SCALE))
        # shortcut: draw order is fixed. The page sorts transparent objects by depth.
        self._halo(root, view, proj, motion)
        spread = motion.ring_spread + motion.pulse * 0.035
        opacity_scale = 0.92 + motion.bloom * 0.48 + motion.pulse * 0.42
        for ring in reversed(self.scene.rings):
            local = _mul(_scale(spread), _euler(ring.tilt_x, ring.tilt_y, ring.z))
            self._mesh(
                "flat" if ring.kind == "flat" else "basic",
                ring,
                _mul(root, local),
                view,
                proj,
                gl,
                ring.opacity * opacity_scale,
                motion,
            )
        self._points(root, view, proj, gl, width, motion)
        shell = motion.shell_radius + motion.pulse * 0.025
        blob = filament_bytes(
            self.scene.filaments,
            motion.elapsed * motion.particle_speed,
            shell,
            motion.pulse,
        )
        self._write_filament(blob)
        filament_model = _mul(root, _euler(0.0, motion.filament_y, 0.0))
        filament_alpha = (
            0.035 + motion.filament_opacity * 0.14 + motion.pulse * 0.025
        ) * max(0.0, min(1.0, motion.shown_energy))
        self._draw_basic(
            self._filament, self.scene.filament_count * 2, 0x0001,
            filament_model, view, proj, gl, _PRIMARY, filament_alpha,
        )
        core_scale = motion.core_scale + motion.pulse * 0.08
        core_spin = _euler(motion.core_rx, motion.core_ry, 0.0)
        core_model = _mul(_mul(root, _scale(core_scale)), core_spin)
        # The inside of the shell faces the camera at full fresnel and paints
        # a solid disc. The page draws the outside only.
        gl.glEnable(0x0B44)  # GL_CULL_FACE
        self._draw_core(core_model, view, proj, gl, motion)
        inner_alpha = 0.34 + motion.bloom * 0.08 + motion.pulse * 0.06
        self._draw_basic(
            self._inner, self.scene.inner_count, 0x0004,
            _mul(root, _scale(core_scale)), view, proj, gl, _CORE, inner_alpha,
        )
        gl.glDisable(0x0B44)

    def _prepare(self) -> None:
        if self._ready:
            return
        self._programs = {
            "core": _link(_CORE_VERT, _CORE_FRAG, ("aPos", "aNrm")),
            "flat": _link(_FLAT_VERT, _FLAT_FRAG, ("aPos", "aNrm")),
            "point": _link(_POINT_VERT, _POINT_FRAG, ("aPos", "aSeed")),
            "packet": _link(_PACKET_VERT, _PACKET_FRAG, ("aPos", "aSeed", "aDirection")),
            "basic": _link(_BASIC_VERT, _BASIC_FRAG, ("aPos",)),
            "halo": _link(_HALO_VERT, _HALO_FRAG, ("aPos",)),
        }
        scene = self.scene
        self._core = _buffer(self._programs["core"], scene.core, ((0, 3, 0, 24), (1, 3, 12, 24)))
        self._inner = _buffer(self._programs["basic"], scene.inner, ((0, 3, 0, 12),))
        self._particle = _buffer(
            self._programs["point"], scene.particles, ((0, 3, 0, 16), (1, 1, 12, 16))
        )
        self._packet = _buffer(
            self._programs["packet"], scene.packets,
            ((0, 3, 0, 20), (1, 1, 12, 20), (2, 1, 16, 20)),
        )
        self._rings = [
            _buffer(
                self._programs["flat" if ring.kind == "flat" else "basic"],
                ring.blob,
                ((0, 3, 0, 24), (1, 3, 12, 24)) if ring.kind == "flat" else ((0, 3, 0, 12),),
            )
            for ring in scene.rings
        ]
        blank = filament_bytes(scene.filaments, 0.0, 1.0, 0.0)
        self._filament = _buffer(self._programs["basic"], blank, ((0, 3, 0, 12),))
        halo = _pack([-1, -1, 1, -1, -1, 1, 1, 1])
        self._halo_mesh = _buffer(self._programs["halo"], halo, ((0, 2, 0, 8),))
        self._ready = True

    def _write_filament(self, blob: bytes) -> None:
        vbo = self._filament[1]
        vbo.bind()
        vbo.allocate(blob, len(blob))

    def _halo(
        self, root: list[float], view: list[float], proj: list[float], motion: Motion
    ) -> None:
        program = self._programs["halo"]
        program.bind()
        program.setUniformValue("uView", _qmat(view))
        program.setUniformValue("uModel", _qmat(root))
        program.setUniformValue("uProj", _qmat(proj))
        size = 1.75 + motion.bloom * 0.32 + motion.pulse * 0.16
        program.setUniformValue1f("uSize", _SCENE_SCALE * size * 0.5)
        _color(program, "uColor", _PRIMARY)
        opacity = 0.12 + motion.bloom * 0.08 + motion.pulse * 0.04
        program.setUniformValue1f("uOpacity", opacity)
        self._halo_mesh[0].bind()
        self._gl().glDrawArrays(0x0005, 0, 4)  # GL_TRIANGLE_STRIP
        self._halo_mesh[0].release()

    def _points(
        self,
        root: list[float],
        view: list[float],
        proj: list[float],
        gl: object,
        width: int,
        motion: Motion,
    ) -> None:
        # shortcut: the figure is 180px, so the ratio is the physical width over that.
        ratio = max(1.0, width / 180.0)
        particle = _mul(root, _euler(0.0, motion.particle_y, 0.0))
        self._draw_points(
            "point", self._particle, self.scene.particle_count, particle, view, proj, gl,
            motion, ratio, 1.55, _PRIMARY, _TERTIARY,
        )
        packet = _mul(root, _euler(motion.packet_x, motion.packet_y, 0.0))
        self._draw_points(
            "packet", self._packet, self.scene.packet_count, packet, view, proj, gl,
            motion, ratio, 1.9, _CORE, _PRIMARY,
        )

    def _draw_points(
        self,
        name: str,
        buf: tuple[object, object],
        count: int,
        model: list[float],
        view: list[float],
        proj: list[float],
        gl: object,
        motion: Motion,
        ratio: float,
        point_scale: float,
        primary: tuple[float, float, float],
        accent: tuple[float, float, float],
    ) -> None:
        program = self._programs[name]
        program.bind()
        model_view = _mul(view, model)
        program.setUniformValue("uMvp", _qmat(_mul(proj, model_view)))
        program.setUniformValue("uModelView", _qmat(model_view))
        program.setUniformValue1f("uTime", motion.elapsed * motion.particle_speed)
        program.setUniformValue1f("uEnergy", motion.shown_energy)
        program.setUniformValue1f("uPulse", min(1.7, motion.pulse))
        program.setUniformValue1f("uPointScale", point_scale)
        program.setUniformValue1f("uPixelRatio", ratio)
        if name == "point":
            _color(program, "uPrimary", primary)
            _color(program, "uAccent", accent)
        else:
            _color(program, "uCore", primary)
            _color(program, "uPrimary", accent)
        buf[0].bind()
        gl.glDrawArrays(0x0000, 0, count)  # GL_POINTS
        buf[0].release()

    def _mesh(
        self,
        program_name: str,
        ring: _Ring,
        model: list[float],
        view: list[float],
        proj: list[float],
        gl: object,
        opacity: float,
        motion: Motion,
    ) -> None:
        index = self.scene.rings.index(ring)
        buf = self._rings[index]
        if program_name == "flat":
            program = self._programs["flat"]
            program.bind()
            model_view = _mul(view, model)
            program.setUniformValue("uMvp", _qmat(_mul(proj, model_view)))
            program.setUniformValue("uModelView", _qmat(model_view))
            _color(program, "uColor", ring.color)
            program.setUniformValue1f("uOpacity", opacity)
            program.setUniformValue1f("uPulse", min(1.7, motion.pulse))
            program.setUniformValue1f("uTime", motion.elapsed)
            buf[0].bind()
            gl.glDrawArrays(0x0004, 0, ring.count)
            buf[0].release()
            return
        mode = 0x0001 if ring.kind == "line" else 0x0004  # LINES or TRIANGLES
        self._draw_basic(buf, ring.count, mode, model, view, proj, gl, ring.color, opacity)

    def _draw_core(
        self,
        model: list[float],
        view: list[float],
        proj: list[float],
        gl: object,
        motion: Motion,
    ) -> None:
        program = self._programs["core"]
        program.bind()
        model_view = _mul(view, model)
        program.setUniformValue("uMvp", _qmat(_mul(proj, model_view)))
        program.setUniformValue("uModelView", _qmat(model_view))
        _color(program, "uCore", _CORE)
        _color(program, "uPrimary", _PRIMARY)
        program.setUniformValue1f("uEnergy", motion.shown_energy)
        program.setUniformValue1f("uPulse", min(1.7, motion.pulse))
        program.setUniformValue1f("uTime", motion.elapsed)
        self._core[0].bind()
        gl.glDrawArrays(0x0004, 0, self.scene.core_count)
        self._core[0].release()

    def _draw_basic(
        self,
        buf: tuple[object, object] | None,
        count: int,
        mode: int,
        model: list[float],
        view: list[float],
        proj: list[float],
        gl: object,
        color: tuple[float, float, float],
        opacity: float,
    ) -> None:
        if buf is None or count <= 0:
            return
        program = self._programs["basic"]
        program.bind()
        program.setUniformValue("uMvp", _qmat(_mul(proj, _mul(view, model))))
        _color(program, "uColor", color)
        program.setUniformValue1f("uOpacity", opacity)
        buf[0].bind()
        gl.glDrawArrays(mode, 0, count)
        buf[0].release()

    def _ensure_fbo(self, width: int, height: int) -> None:
        if self._fbo is not None and self._size == (width, height):
            return
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

        spec = QOpenGLFramebufferObjectFormat()
        spec.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
        spec.setInternalTextureFormat(0x8058)  # GL_RGBA8
        spec.setSamples(4)
        self._fbo = QOpenGLFramebufferObject(width, height, spec)
        self._size = (width, height)
        if not self._fbo.isValid():
            raise RuntimeError("jarvis orb framebuffer was not created")

    def _gl(self) -> object:
        from PySide6.QtGui import QOpenGLContext

        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            raise RuntimeError("jarvis orb draw has no GL context")
        return ctx.functions()


def _color(program: object, name: str, color: tuple[float, float, float]) -> None:
    from PySide6.QtGui import QVector3D

    program.setUniformValue(name, QVector3D(*color))


def _link(vertex: str, fragment: str, names: tuple[str, ...]) -> object:
    from PySide6.QtOpenGL import QOpenGLShader, QOpenGLShaderProgram

    program = QOpenGLShaderProgram()
    kinds = getattr(QOpenGLShader, "ShaderTypeBit", None) or QOpenGLShader.Type
    if not program.addShaderFromSourceCode(kinds.Vertex, vertex):
        raise RuntimeError(program.log())
    if not program.addShaderFromSourceCode(kinds.Fragment, fragment):
        raise RuntimeError(program.log())
    for index, name in enumerate(names):
        program.bindAttributeLocation(name, index)
    if not program.link():
        raise RuntimeError(program.log())
    return program


def _buffer(
    program: object,
    blob: bytes,
    attribs: tuple[tuple[int, int, int, int], ...],
) -> tuple[object, object]:
    from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLVertexArrayObject

    vao = QOpenGLVertexArrayObject()
    vao.create()
    vao.bind()
    vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
    vbo.create()
    vbo.bind()
    vbo.allocate(blob, len(blob))
    program.bind()
    for location, size, offset, stride in attribs:
        program.enableAttributeArray(location)
        program.setAttributeBuffer(location, 0x1406, offset, size, stride)  # GL_FLOAT
    vao.release()
    return vao, vbo


def draw_jarvis_orb(
    host: object,
    width: int,
    height: int,
    t: float,
    blend: dict[str, float],
    level: float,
    _level_from: float,
) -> object:
    """Paint the scene into a transparent image. The GL context is current."""
    gpu = getattr(host, "_orb_gpu", None)
    if gpu is None:
        gpu = _Gpu(build_scene())
        host._orb_gpu = gpu  # type: ignore[attr-defined]
    state_index = int(blend.get("to") or 0)
    state = PET_STATES[state_index] if 0 <= state_index < len(PET_STATES) else "idle"
    return gpu.frame(width, height, t, state, float(level))
