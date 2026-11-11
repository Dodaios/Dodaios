"""Draw a GLB pet on the desktop figure.

The page plays the same file. This process has the OpenGL window the shader
pets use, so it draws the meshes and the clip the pet's ``pet.json`` names.
There is no skeleton: each piece is a node, and the clip moves that node.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dodaios.ui.pets.states import PET_STATES

_COMPONENT = {
    5120: (1, "b"),
    5121: (1, "B"),
    5122: (2, "h"),
    5123: (2, "H"),
    5125: (4, "I"),
    5126: (4, "f"),
}
_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


@dataclass
class _Mesh:
    node: int
    positions: list[tuple[float, float, float]]
    interleaved: bytes
    count: int


@dataclass
class _Clip:
    duration: float
    # node -> path -> (times, values, components)
    tracks: dict[int, dict[str, tuple[list[float], list[float], int]]]


# translation, rotation (xyzw), scale
_Vec3 = tuple[float, float, float]
_Quat = tuple[float, float, float, float]
_TRS = tuple[_Vec3, _Quat, _Vec3]


@dataclass
class CubeCat:
    meshes: list[_Mesh]
    parents: list[int]
    base: list[_TRS]
    clips: dict[str, _Clip]
    texture: bytes
    texture_size: tuple[int, int]
    # Bind-pose fit: scale, then the point subtracted before scaling.
    scale: float
    origin: tuple[float, float, float]
    eye: tuple[float, float, float]
    aim_y: float


def load_cube_cat(
    path: Path,
    *,
    height: float,
    eye: tuple[float, float, float],
    aim_y: float,
) -> CubeCat:
    """Read a GLB. Positions stay in node space. ``height`` is metres."""
    data = path.read_bytes()
    blob, gltf = _chunks(data)
    views = gltf["bufferViews"]
    accessors = gltf["accessors"]

    def read(index: int) -> list[float]:
        acc = accessors[index]
        view = views[acc["bufferView"]]
        size, code = _COMPONENT[acc["componentType"]]
        n = _COUNT[acc["type"]]
        stride = int(view.get("byteStride") or size * n)
        start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        out: list[float] = []
        for i in range(int(acc["count"])):
            base = start + i * stride
            out.extend(struct.unpack_from("<" + code * n, blob, base))
        return out

    nodes = gltf["nodes"]
    parents = [-1] * len(nodes)
    for index, node in enumerate(nodes):
        for child in node.get("children") or []:
            parents[int(child)] = index
    base = [_node_trs(node) for node in nodes]

    meshes: list[_Mesh] = []
    for index, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        prim = gltf["meshes"][node["mesh"]]["primitives"][0]
        attrs = prim["attributes"]
        pos = read(attrs["POSITION"])
        nrm = read(attrs["NORMAL"])
        uv = read(attrs["TEXCOORD_0"])
        idx = read(prim["indices"])
        verts = len(pos) // 3
        corners: list[tuple[float, ...]] = []
        positions: list[tuple[float, float, float]] = []
        for v in range(verts):
            xyz = (pos[v * 3], pos[v * 3 + 1], pos[v * 3 + 2])
            positions.append(xyz)
            corners.append(
                (
                    *xyz,
                    nrm[v * 3],
                    nrm[v * 3 + 1],
                    nrm[v * 3 + 2],
                    uv[v * 2],
                    uv[v * 2 + 1],
                )
            )
        # Drawn without an index buffer: this Qt binding rejects a zero offset.
        packed = bytearray()
        for pointer in idx:
            packed += struct.pack("<8f", *corners[int(pointer)])
        meshes.append(
            _Mesh(node=index, positions=positions, interleaved=bytes(packed), count=len(idx))
        )

    clips: dict[str, _Clip] = {}
    for anim in gltf["animations"]:
        tracks: dict[int, dict[str, tuple[list[float], list[float], int]]] = {}
        duration = 0.0
        for channel in anim["channels"]:
            sampler = anim["samplers"][channel["sampler"]]
            times = read(sampler["input"])
            values = read(sampler["output"])
            duration = max(duration, times[-1] if times else 0.0)
            node = int(channel["target"]["node"])
            path = str(channel["target"]["path"])
            comps = {"translation": 3, "scale": 3, "rotation": 4}[path]
            tracks.setdefault(node, {})[path] = (times, values, comps)
        clips[str(anim["name"])] = _Clip(duration=duration, tracks=tracks)

    image = gltf["images"][0]
    view = views[image["bufferView"]]
    start = int(view.get("byteOffset", 0))
    png = blob[start : start + int(view["byteLength"])]
    texture, texture_size = _png(png)
    scale, origin = _fit(meshes, parents, base, height)
    return CubeCat(
        meshes=meshes,
        parents=parents,
        base=base,
        clips=clips,
        texture=texture,
        texture_size=texture_size,
        scale=scale,
        origin=origin,
        eye=eye,
        aim_y=aim_y,
    )


def pose(cat: CubeCat, clip_name: str, t: float) -> list[list[float]]:
    """World matrix of every node, column-major, at ``t`` seconds in the clip."""
    clip = cat.clips.get(clip_name) or cat.clips["idle"]
    local: list[list[float]] = []
    for index, trs in enumerate(cat.base):
        translation, rotation, scale = trs
        track = clip.tracks.get(index) or {}
        if "translation" in track:
            translation = _sample(track["translation"], t, clip.duration)
        if "rotation" in track:
            rotation = _slerp_sample(track["rotation"], t, clip.duration)
        if "scale" in track:
            scale = _sample(track["scale"], t, clip.duration)
        local.append(_trs(translation, rotation, scale))
    world = [local[0]]
    for index in range(1, len(local)):
        parent = cat.parents[index]
        world.append(_mul(world[parent] if parent >= 0 else _ID, local[index]))
    root = _mul(_scale(cat.scale), _translate(-cat.origin[0], -cat.origin[1], -cat.origin[2]))
    return [_mul(root, item) for item in world]


def draw_model(
    host: Any, width: int, height: int, t: float, blend: dict[str, float], pet_id: str
) -> Any:
    """Paint the model named by ``pet_id``. The GL context is current."""
    from dodaios.ui.pets.loader import find_pet_dir, read_manifest

    slot = getattr(host, "_model_gpu", None)
    if slot is None or slot[0] != pet_id:
        found = find_pet_dir(pet_id)
        if found is None:
            raise RuntimeError(f"model pet {pet_id!r} is not installed")
        folder, builtin = found
        manifest = read_manifest(folder, builtin=builtin)
        if manifest.kind != "model" or not manifest.model:
            raise RuntimeError(f"pet {pet_id!r} is not a model")
        options = manifest.options
        model = load_cube_cat(
            folder / manifest.model,
            height=options.height,
            eye=options.eye,
            aim_y=options.aim * options.height,
        )
        slot = (pet_id, _Gpu(model), manifest)
        host._model_gpu = slot  # type: ignore[attr-defined]
    _loaded_id, gpu, manifest = slot
    state_index = int(blend.get("to") or 0)
    state = PET_STATES[state_index] if 0 <= state_index < len(PET_STATES) else "idle"
    return gpu.frame(width, height, t, manifest.clip_for(state))


# -- glTF ----------------------------------------------------------------


def _chunks(data: bytes) -> tuple[bytes, dict[str, Any]]:
    if data[:4] != b"glTF":
        raise ValueError("model file is not a glTF binary")
    length = struct.unpack_from("<I", data, 8)[0]
    off = 12
    blob = b""
    gltf: dict[str, Any] | None = None
    while off + 8 <= length:
        size, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8 : off + 8 + size]
        off += 8 + size
        if kind == 0x4E4F534A:
            gltf = json.loads(chunk)
        elif kind == 0x004E4942:
            blob = chunk
    if gltf is None:
        raise ValueError("cube cat file has no JSON chunk")
    return blob, gltf


def _node_trs(node: dict[str, Any]) -> _TRS:
    translation = tuple(float(v) for v in node.get("translation") or (0, 0, 0))
    rotation = tuple(float(v) for v in node.get("rotation") or (0, 0, 0, 1))
    scale = tuple(float(v) for v in node.get("scale") or (1, 1, 1))
    return translation, rotation, scale  # type: ignore[return-value]


def _png(blob: bytes) -> tuple[bytes, tuple[int, int]]:
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(blob)).convert("RGBA")
    image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image.tobytes(), image.size


def _fit(
    meshes: list[_Mesh], parents: list[int], base: list[_TRS], height_m: float
) -> tuple[float, _Vec3]:
    local = [_trs(*trs) for trs in base]
    world = [local[0]]
    for index in range(1, len(local)):
        parent = parents[index]
        world.append(_mul(world[parent] if parent >= 0 else _ID, local[index]))
    lo = [math.inf, math.inf, math.inf]
    hi = [-math.inf, -math.inf, -math.inf]
    for mesh in meshes:
        for point in mesh.positions:
            placed = _point(world[mesh.node], point)
            for axis in range(3):
                lo[axis] = min(lo[axis], placed[axis])
                hi[axis] = max(hi[axis], placed[axis])
    height = max(hi[1] - lo[1], 1e-6)
    origin = ((lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2)
    return height_m / height, origin


def _sample(
    track: tuple[list[float], list[float], int], t: float, duration: float
) -> tuple[float, ...]:
    times, values, comps = track
    frame = _frame_at(times, t, duration)
    i, u = frame
    return tuple(
        values[i * comps + c] * (1 - u) + values[(i + 1) * comps + c] * u for c in range(comps)
    )


def _slerp_sample(
    track: tuple[list[float], list[float], int], t: float, duration: float
) -> tuple[float, float, float, float]:
    times, values, comps = track
    i, u = _frame_at(times, t, duration)
    a = tuple(values[i * comps : (i + 1) * comps])
    b = tuple(values[(i + 1) * comps : (i + 2) * comps])
    return _slerp(a, b, u)  # type: ignore[arg-type]


def _frame_at(times: list[float], t: float, duration: float) -> tuple[int, float]:
    if len(times) < 2 or duration <= 0:
        return 0, 0.0
    t = t % duration
    i = 0
    while i + 1 < len(times) and times[i + 1] < t:
        i += 1
    if i + 1 >= len(times):
        return len(times) - 2, 1.0
    span = times[i + 1] - times[i]
    return i, 0.0 if span <= 0 else (t - times[i]) / span


def _slerp(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    u: float,
) -> tuple[float, float, float, float]:
    dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3]
    if dot < 0:
        b = (-b[0], -b[1], -b[2], -b[3])
        dot = -dot
    if dot > 0.9995:
        mixed = tuple(a[i] + (b[i] - a[i]) * u for i in range(4))
        return _norm(mixed)  # type: ignore[arg-type]
    theta = math.acos(min(1.0, dot))
    scale = math.sin(theta)
    w1 = math.sin((1 - u) * theta) / scale
    w2 = math.sin(u * theta) / scale
    return (
        a[0] * w1 + b[0] * w2,
        a[1] * w1 + b[1] * w2,
        a[2] * w1 + b[2] * w2,
        a[3] * w1 + b[3] * w2,
    )


def _norm(q: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    length = math.sqrt(sum(v * v for v in q)) or 1.0
    return (q[0] / length, q[1] / length, q[2] / length, q[3] / length)


# -- matrices, column-major ----------------------------------------------

_ID = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def _mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return out


def _translate(x: float, y: float, z: float) -> list[float]:
    m = _ID.copy()
    m[12], m[13], m[14] = x, y, z
    return m


def _scale(s: float) -> list[float]:
    return [s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, 0, 0, 0, 1]


def _trs(
    translation: tuple[float, ...],
    rotation: tuple[float, ...],
    scale: tuple[float, ...],
) -> list[float]:
    x, y, z, w = rotation
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    sx, sy, sz = scale
    return [
        (1 - 2 * (yy + zz)) * sx,
        (2 * (xy + wz)) * sx,
        (2 * (xz - wy)) * sx,
        0.0,
        (2 * (xy - wz)) * sy,
        (1 - 2 * (xx + zz)) * sy,
        (2 * (yz + wx)) * sy,
        0.0,
        (2 * (xz + wy)) * sz,
        (2 * (yz - wx)) * sz,
        (1 - 2 * (xx + yy)) * sz,
        0.0,
        translation[0],
        translation[1],
        translation[2],
        1.0,
    ]


def _point(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


def _perspective(fov_deg: float, aspect: float) -> list[float]:
    near, far = 0.05, 20.0
    f = 1.0 / math.tan(math.radians(fov_deg) / 2)
    return [
        f / aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (far + near) / (near - far), -1,
        0, 0, (2 * far * near) / (near - far), 0,
    ]


def _look(eye: tuple[float, float, float], aim: tuple[float, float, float]) -> list[float]:
    fx, fy, fz = (aim[0] - eye[0], aim[1] - eye[1], aim[2] - eye[2])
    fl = math.sqrt(fx * fx + fy * fy + fz * fz) or 1.0
    fx, fy, fz = fx / fl, fy / fl, fz / fl
    # right = forward × up
    sx, sy, sz = fy * 0 - fz * 1, fz * 0 - fx * 0, fx * 1 - fy * 0
    sl = math.sqrt(sx * sx + sy * sy + sz * sz) or 1.0
    sx, sy, sz = sx / sl, sy / sl, sz / sl
    ux, uy, uz = sy * fz - sz * fy, sz * fx - sx * fz, sx * fy - sy * fx
    return [
        sx, ux, -fx, 0,
        sy, uy, -fy, 0,
        sz, uz, -fz, 0,
        -(sx * eye[0] + sy * eye[1] + sz * eye[2]),
        -(ux * eye[0] + uy * eye[1] + uz * eye[2]),
        fx * eye[0] + fy * eye[1] + fz * eye[2],
        1,
    ]


# -- GL -------------------------------------------------------------------

_VERT = """#version 150
uniform mat4 uMvp;
uniform mat4 uModel;
in vec3 aPos;
in vec3 aNrm;
in vec2 aUv;
out vec3 vNrm;
out vec2 vUv;
void main() {
  gl_Position = uMvp * vec4(aPos, 1.0);
  vNrm = mat3(uModel) * aNrm;
  vUv = aUv;
}
"""

_FRAG = """#version 150
uniform sampler2D uTex;
in vec3 vNrm;
in vec2 vUv;
out vec4 fragColor;
void main() {
  vec3 n = normalize(vNrm);
  float light = abs(dot(n, normalize(vec3(2.2, 3.4, 2.0))));
  vec3 tex = texture(uTex, vUv).rgb;
  fragColor = vec4(tex * (0.55 + 0.7 * light), 1.0);
}
"""


class _Gpu:
    def __init__(self, cat: CubeCat) -> None:
        self.cat = cat
        self._ready = False
        self._program: Any = None
        self._meshes: list[tuple[Any, Any, _Mesh]] = []
        self._tex: Any = None
        self._fbo: Any = None
        self._size = (0, 0)

    def frame(self, width: int, height: int, t: float, clip: str) -> Any:
        self._prepare()
        self._ensure_fbo(width, height)
        gl = self._gl()
        self._fbo.bind()
        gl.glViewport(0, 0, width, height)
        gl.glEnable(0x0B71)  # GL_DEPTH_TEST
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(0x00004100)  # COLOR | DEPTH
        program = self._program
        program.bind()
        program.setUniformValue1i("uTex", 0)
        self._tex.bind(0)
        proj = _perspective(30.0, width / max(1, height))
        view = _look(self.cat.eye, (0.0, self.cat.aim_y, 0.0))
        camera = _mul(proj, view)
        nodes = pose(self.cat, clip, t)
        for vao, _vbo, mesh in self._meshes:
            mvp = _mul(camera, nodes[mesh.node])
            program.setUniformValue("uMvp", _qmat(mvp))
            program.setUniformValue("uModel", _qmat(nodes[mesh.node]))
            vao.bind()
            gl.glDrawArrays(0x0004, 0, mesh.count)  # GL_TRIANGLES
            vao.release()
        image = self._fbo.toImage()
        self._fbo.release()
        gl.glDisable(0x0B71)
        return image

    def _prepare(self) -> None:
        if self._ready:
            return
        from PySide6.QtOpenGL import (
            QOpenGLBuffer,
            QOpenGLShader,
            QOpenGLShaderProgram,
            QOpenGLVertexArrayObject,
        )

        program = QOpenGLShaderProgram()
        kinds = getattr(QOpenGLShader, "ShaderTypeBit", None) or QOpenGLShader.Type
        if not program.addShaderFromSourceCode(kinds.Vertex, _VERT):
            raise RuntimeError(program.log())
        if not program.addShaderFromSourceCode(kinds.Fragment, _FRAG):
            raise RuntimeError(program.log())
        program.bindAttributeLocation("aPos", 0)
        program.bindAttributeLocation("aNrm", 1)
        program.bindAttributeLocation("aUv", 2)
        if not program.link():
            raise RuntimeError(program.log())
        uploaded: list[tuple[Any, Any, _Mesh]] = []
        for mesh in self.cat.meshes:
            vao = QOpenGLVertexArrayObject()
            vao.create()
            vao.bind()
            vbo = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
            vbo.create()
            vbo.bind()
            vbo.allocate(mesh.interleaved, len(mesh.interleaved))
            program.bind()
            program.enableAttributeArray(0)
            program.enableAttributeArray(1)
            program.enableAttributeArray(2)
            program.setAttributeBuffer(0, 0x1406, 0, 3, 32)
            program.setAttributeBuffer(1, 0x1406, 12, 3, 32)
            program.setAttributeBuffer(2, 0x1406, 24, 2, 32)
            vao.release()
            uploaded.append((vao, vbo, mesh))
        from PySide6.QtGui import QImage
        from PySide6.QtOpenGL import QOpenGLTexture

        w, h = self.cat.texture_size
        # The bytes are already bottom-up. QImage is top-down, and
        # QOpenGLTexture mirrors once, so mirror here to land upright.
        qimg = QImage(self.cat.texture, w, h, QImage.Format.Format_RGBA8888).copy().mirrored(
            False, True
        )
        texture = QOpenGLTexture(QOpenGLTexture.Target.Target2D)
        texture.setData(qimg)
        texture.setMinificationFilter(QOpenGLTexture.Filter.Linear)
        texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
        texture.setWrapMode(QOpenGLTexture.WrapMode.ClampToEdge)
        self._program = program
        self._meshes = uploaded
        self._tex = texture
        self._ready = True

    def _ensure_fbo(self, width: int, height: int) -> None:
        if self._fbo is not None and self._size == (width, height):
            return
        from PySide6.QtOpenGL import QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat

        spec = QOpenGLFramebufferObjectFormat()
        spec.setAttachment(QOpenGLFramebufferObject.Attachment.Depth)
        spec.setInternalTextureFormat(0x8058)  # GL_RGBA8
        spec.setSamples(4)
        self._fbo = QOpenGLFramebufferObject(width, height, spec)
        self._size = (width, height)
        if not self._fbo.isValid():
            raise RuntimeError("cube cat framebuffer was not created")

    def _gl(self) -> Any:
        from PySide6.QtGui import QOpenGLContext

        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            raise RuntimeError("cube cat draw has no GL context")
        return ctx.functions()


def _qmat(column_major: list[float]) -> Any:
    from PySide6.QtGui import QMatrix4x4

    # The constructor reads row by row.
    values = [column_major[col * 4 + row] for row in range(4) for col in range(4)]
    return QMatrix4x4(*values)
