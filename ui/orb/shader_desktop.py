"""Desktop figure for a ``jarvis-shader-pet/1`` pet.

The Tk overlay cannot show real alpha: on macOS Tk 9 leaves an opaque box,
and on Windows its colour key is fully on or fully off. This process owns the
figure instead. macOS (and Linux, where the colour key works) paints a Qt
window the way the Jarvis Bar does — clear the backing, then draw the orb.
Windows blits the same image through ``UpdateLayeredWindow``. Clear pixels
are the desktop and do not take clicks.

The parent is :mod:`ui.orb.shader_host`. It writes one JSON object per line
on stdin (``show``, ``place``, ``state``, ``level``, ``hide``, ``quit``). This process
writes ``move``, ``drop``, ``hover``, ``menu`` and ``mute`` on stdout.

Run: ``python -m ui.orb.shader_desktop``.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import struct
import sys
import time
from typing import Any

from dodaios.ui.pets.states import PET_STATES

log = logging.getLogger("jarvis.shader_pet")

#: Same mix duration as the web wrapper (``shaderPet.ts``).
SHADER_BLEND_S = 0.33

#: Sprite-sheet row indexes whose pass may carry a voice level.
_VOICE_STATE_INDEXES = frozenset(
    index for index, name in enumerate(PET_STATES) if name in ("listening", "talking")
)

_VERTEX = """#version 150
in vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
"""

_DRAG_THRESHOLD_PX = 16


def _unit(value: object) -> float:
    """A loudness clamped to 0..1. Anything unusable is silence."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    level = float(value)
    if level != level or level < 0.0:
        return 0.0
    return 1.0 if level > 1.0 else level


def step_shader_blend(blend: dict[str, float], state: int, dt: float, reduced: bool) -> None:
    """Advance the mix. A new state restarts it from the one on screen."""
    if state != int(blend["to"]):
        blend["from"] = blend["to"]
        blend["to"] = float(state)
        blend["value"] = 1.0 if reduced else 0.0
    if reduced or blend["value"] >= 1.0:
        blend["value"] = 1.0
        return
    blend["value"] = min(1.0, blend["value"] + max(0.0, dt) / SHADER_BLEND_S)


def shader_pass_levels(
    blend: dict[str, float], level: float, level_from: float
) -> tuple[float, float]:
    """``(uLevelFrom, uLevel)`` for the two passes.

    ``level`` is the loudness of the state on screen now (``blend['to']``).
    ``level_from`` is the loudness captured when that state was left. A pass
    whose state is not talking or listening is silent.
    """
    outgoing = _unit(level_from) if int(blend["from"]) in _VOICE_STATE_INDEXES else 0.0
    incoming = _unit(level) if int(blend["to"]) in _VOICE_STATE_INDEXES else 0.0
    return outgoing, incoming


def wrap_desktop_fragment(source: str) -> str:
    """User ``main`` plus a generated sphere, compiled as desktop GLSL 1.50.

    WebGL 1 keeps ``gl_FragColor``. Desktop core profile does not, so that
    name is rewritten. ``vLocal``, ``vNormal`` and ``vView`` are computed
    from the pixel, not interpolated: a fullscreen quad has no sphere.
    A source that starts with ``// full-frame`` owns the whole window and
    its own alpha; the sphere mask is skipped.
    """
    body = re.sub(r"\bgl_FragColor\b", "fragColor", source)
    body = re.sub(r"\bvoid\s+main\s*\(", "void petMain(", body, count=1)
    full_frame = source.startswith("// full-frame")
    if full_frame:
        return (
            "#version 150\n"
            "uniform float uTime;\n"
            "uniform float uState;\n"
            "uniform float uStateFrom;\n"
            "uniform float uBlend;\n"
            "uniform float uLevel;\n"
            "uniform float uLevelFrom;\n"
            "uniform vec2 uSize;\n"
            "out vec4 fragColor;\n"
            "vec3 vLocal;\n"
            "vec3 vNormal;\n"
            "vec3 vView;\n"
            "float petState;\n"
            "float petLevel;\n"
            "#define uState petState\n"
            "#define uLevel petLevel\n"
            f"{body}\n"
            "#undef uLevel\n"
            "#undef uState\n"
            "void main() {\n"
            "  petLevel = uLevelFrom;\n"
            "  petState = uStateFrom;\n"
            "  petMain();\n"
            "  vec4 petFrom = fragColor;\n"
            "  petLevel = uLevel;\n"
            "  petState = uState;\n"
            "  petMain();\n"
            "  fragColor = mix(petFrom, fragColor, clamp(uBlend, 0.0, 1.0));\n"
            "}\n"
        )
    return (
        "#version 150\n"
        "uniform float uTime;\n"
        "uniform float uState;\n"
        "uniform float uStateFrom;\n"
        "uniform float uBlend;\n"
        "uniform float uLevel;\n"
        "uniform float uLevelFrom;\n"
        "uniform vec2 uSize;\n"
        "out vec4 fragColor;\n"
        "vec3 vLocal;\n"
        "vec3 vNormal;\n"
        "vec3 vView;\n"
        "float petState;\n"
        "float petLevel;\n"
        "#define uState petState\n"
        "#define uLevel petLevel\n"
        f"{body}\n"
        "#undef uLevel\n"
        "#undef uState\n"
        "void main() {\n"
        "  vec2 p = gl_FragCoord.xy / uSize * 2.0 - 1.0;\n"
        "  float r2 = dot(p, p);\n"
        "  if (r2 > 1.0) {\n"
        "    fragColor = vec4(0.0);\n"
        "    return;\n"
        "  }\n"
        "  float z = sqrt(max(0.0, 1.0 - r2));\n"
        "  vLocal = vec3(p, z) * 0.5;\n"
        "  vNormal = normalize(vec3(p, z));\n"
        "  vView = vec3(0.0, 0.0, 1.0);\n"
        "  petLevel = uLevelFrom;\n"
        "  petState = uStateFrom;\n"
        "  petMain();\n"
        "  vec4 petFrom = fragColor;\n"
        "  petLevel = uLevel;\n"
        "  petState = uState;\n"
        "  petMain();\n"
        "  fragColor = mix(petFrom, fragColor, clamp(uBlend, 0.0, 1.0));\n"
        "}\n"
    )


def figure_clips_to_disc(source: str) -> bool:
    """A generated sphere is a disc. A model or a full-frame scene is not."""
    return not source.startswith("// ")


# The orb's glow reaches about 0.70 of the way from the centre to the frame
# (fov 35 at z 4.1, scene scale 0.82, halo 2.2). The disc used to run to the
# frame; 60% of that gap is what is left.
_JARVIS_PET_RADIUS = 0.70
_DISC_OUTSET = 0.6
_JARVIS_DISC_RADIUS = _JARVIS_PET_RADIUS + _DISC_OUTSET * (1.0 - _JARVIS_PET_RADIUS)


def disc_backdrop_straight(
    rgba: bytes, width: int, height: int, opacity: float, radius: float = 1.0
) -> bytes:
    """Black disc behind premultiplied pixels. Corners outside it stay clear.

    ``opacity`` 0 returns the same bytes. Black adds no colour, so a pixel the
    shader painted keeps its RGB and only its alpha rises — that rise is the
    gap behind it turning black. Treating these bytes as straight and scaling
    RGB by alpha crushed a shader pet. ``radius`` is the disc in frame units
    (1 fills the old full-frame disc). A model is not passed here.
    """
    shade = _unit(opacity)
    count = width * height * 4
    limit = max(0.0, radius) ** 2
    if shade <= 0.0 or width < 1 or height < 1 or len(rgba) != count or limit <= 0.0:
        return rgba
    import numpy as np

    pix = np.frombuffer(rgba, dtype=np.uint8).reshape(height, width, 4).astype(np.float32)
    ys, xs = np.ogrid[:height, :width]
    nx = (xs + 0.5) / width * 2.0 - 1.0
    ny = (ys + 0.5) / height * 2.0 - 1.0
    inside = (nx * nx + ny * ny) <= limit
    pet_a = pix[..., 3] / 255.0
    out_a = np.where(inside, pet_a + shade * (1.0 - pet_a), pet_a)
    out = pix.copy()
    out[..., 3] = np.clip(np.rint(out_a * 255.0), 0, 255)
    out[~inside] = pix[~inside]
    return out.astype(np.uint8).tobytes()


def apply_disc_backdrop(image: Any, opacity: float, radius: float = 1.0) -> Any:
    """The same disc, on the premultiplied image the window paints."""
    if _unit(opacity) <= 0.0 or image is None:
        return image
    from PySide6.QtGui import QImage

    raw, width, height = _qimage_premul_rgba(image)
    painted = disc_backdrop_straight(raw, width, height, opacity, radius)
    if painted is raw:
        return image
    out = QImage(
        painted, width, height, width * 4, QImage.Format.Format_RGBA8888_Premultiplied
    )
    return out.copy()


def _png_image(payload: Any) -> Any:
    """A PNG sent as base64, or ``None`` when it will not decode."""
    import base64

    from PySide6.QtGui import QImage

    try:
        raw = base64.b64decode(payload or b"", validate=False)
    except (ValueError, TypeError):
        return None
    image = QImage()
    if not raw or not image.loadFromData(raw, "PNG") or image.isNull():
        return None
    return image


def strip_frame(payload: Any, premul: bool) -> Any:
    """The image the strip window paints. A fade is already premultiplied."""
    from PySide6.QtGui import QImage

    image = _png_image(payload)
    if image is not None and premul:
        # PNG bytes are straight unless we say otherwise. Tagging skips a
        # second multiply, which would fade the strip twice.
        image.reinterpretAsFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return image


def shader_source_for_id(pet_id: str) -> str | None:
    """The fragment text when ``pet_id`` is a shader pet, else ``None``.

    A folder that claims to be a shader but fails its checks raises
    :class:`~dodaios.ui.pets.manifest.PetManifestError`. The caller must not
    then load a sprite: that path substitutes the default pixel pet.
    """
    import json as _json
    from pathlib import Path

    from dodaios.ui.pets.loader import find_pet_dir, read_manifest
    from dodaios.ui.pets.states import MODEL_PET_FORMAT, SHADER_PET_FORMAT

    # The page plays the Three.js scene. This process draws the same parts.
    if pet_id == "jarvis-orb":
        from ui.orb.dodaios_orb_desktop import JARVIS_ORB_SOURCE

        return JARVIS_ORB_SOURCE
    found = find_pet_dir(pet_id)
    if found is None:
        return None
    folder, builtin = found
    try:
        data = _json.loads((Path(folder) / "pet.json").read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, _json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("format") == MODEL_PET_FORMAT:
        read_manifest(folder, builtin=builtin)
        return f"// model {pet_id}"
    if data.get("format") != SHADER_PET_FORMAT:
        return None
    manifest = read_manifest(folder, builtin=builtin)
    name = manifest.shader or "shader.frag"
    return (Path(folder) / name).read_text(encoding="utf-8")


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


class _Gl:
    """One offscreen context. Recompiled when the source changes."""

    def __init__(self) -> None:
        self._source: str | None = None
        self._program: Any = None
        self._ctx: Any = None
        self._surface: Any = None
        self._fbo: Any = None
        self._fbo_size = (0, 0)
        self._vao: Any = None
        self._buf: Any = None
        self._warned = False
        # A source that failed to compile. Kept so the next tick does not
        # make the context current, fail, and leak it again.
        self._rejected: str | None = None

    def frame(
        self,
        source: str,
        width: int,
        height: int,
        t: float,
        blend: dict[str, float],
        level: float,
        level_from: float = 0.0,
    ) -> Any:
        try:
            return self._frame(
                source, max(1, width), max(1, height), t, blend, level, level_from
            )
        except Exception:
            if not self._warned:
                self._warned = True
                log.exception("shader figure render failed")
            return None

    def _frame(
        self,
        source: str,
        width: int,
        height: int,
        t: float,
        blend: dict[str, float],
        level: float,
        level_from: float,
    ) -> Any:
        from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat

        if self._ctx is None:
            fmt = QSurfaceFormat()
            fmt.setVersion(3, 2)
            fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
            fmt.setAlphaBufferSize(8)
            self._ctx = QOpenGLContext()
            self._ctx.setFormat(fmt)
            if not self._ctx.create():
                raise RuntimeError("OpenGL context was not created")
            self._surface = QOffscreenSurface()
            self._surface.setFormat(self._ctx.format())
            self._surface.create()
        if not self._ctx.makeCurrent(self._surface):
            raise RuntimeError("OpenGL context could not be made current")
        try:
            return self._draw_current(source, width, height, t, blend, level, level_from)
        finally:
            # A failed compile used to raise before this, so the context stayed
            # current and the next tick compiled the same source again.
            self._ctx.doneCurrent()

    def _draw_current(
        self,
        source: str,
        width: int,
        height: int,
        t: float,
        blend: dict[str, float],
        level: float,
        level_from: float,
    ) -> Any:
        from PySide6.QtOpenGL import (
            QOpenGLBuffer,
            QOpenGLFramebufferObject,
            QOpenGLFramebufferObjectFormat,
            QOpenGLShader,
            QOpenGLShaderProgram,
            QOpenGLVertexArrayObject,
        )

        if source.startswith("// scene "):
            from ui.orb.dodaios_orb_desktop import draw_jarvis_orb

            return draw_jarvis_orb(self, width, height, t, blend, level, level_from)
        if source.startswith("// model "):
            from ui.orb.cube_cat_desktop import draw_model

            pet_id = source.removeprefix("// model ").strip()
            return draw_model(self, width, height, t, blend, pet_id)
        if source == self._rejected:
            if self._program is None:
                return None
        elif self._program is None or source != self._source:
            program = QOpenGLShaderProgram()
            kinds = getattr(QOpenGLShader, "ShaderTypeBit", None) or QOpenGLShader.Type
            fragment = wrap_desktop_fragment(source)
            vertex_ok = program.addShaderFromSourceCode(kinds.Vertex, _VERTEX)
            fragment_ok = vertex_ok and program.addShaderFromSourceCode(kinds.Fragment, fragment)
            if vertex_ok and fragment_ok:
                program.bindAttributeLocation("aPos", 0)
            if not vertex_ok or not fragment_ok or not program.link():
                self._rejected = source
                raise RuntimeError(f"shader compile: {program.log()}")
            self._program = program
            self._source = source
            self._rejected = None
            if self._buf is None:
                data = struct.pack("<8f", -1.0, -1.0, 1.0, -1.0, -1.0, 1.0, 1.0, 1.0)
                self._vao = QOpenGLVertexArrayObject()
                self._vao.create()
                self._vao.bind()
                self._buf = QOpenGLBuffer(QOpenGLBuffer.Type.VertexBuffer)
                self._buf.create()
                self._buf.bind()
                self._buf.allocate(data, len(data))
                program.bind()
                program.enableAttributeArray(0)
                program.setAttributeBuffer(0, 0x1406, 0, 2, 0)  # GL_FLOAT
                self._vao.release()
        if self._program is None:
            return None
        if self._fbo is None or self._fbo_size != (width, height):
            spec = QOpenGLFramebufferObjectFormat()
            spec.setAttachment(QOpenGLFramebufferObject.Attachment.NoAttachment)
            spec.setInternalTextureFormat(0x8058)  # GL_RGBA8
            self._fbo = QOpenGLFramebufferObject(width, height, spec)
            self._fbo_size = (width, height)
        if self._fbo is None or not self._fbo.isValid():
            raise RuntimeError("framebuffer was not created")
        self._fbo.bind()
        gl = self._ctx.functions()
        gl.glViewport(0, 0, width, height)
        gl.glDisable(0x0BE2)  # GL_BLEND — store the shader's alpha as written
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(0x00004000)  # GL_COLOR_BUFFER_BIT
        program = self._program
        program.bind()
        outgoing, incoming = shader_pass_levels(blend, level, level_from)
        # setUniformValue(name, float) binds the int overload, so the clock
        # and the voice level stay on whole numbers.
        program.setUniformValue1f("uTime", float(t))
        program.setUniformValue1f("uState", float(blend["to"]))
        program.setUniformValue1f("uStateFrom", float(blend["from"]))
        program.setUniformValue1f("uBlend", float(blend["value"]))
        program.setUniformValue1f("uLevel", float(incoming))
        program.setUniformValue1f("uLevelFrom", float(outgoing))
        program.setUniformValue("uSize", float(width), float(height))
        self._vao.bind()
        gl.glDrawArrays(0x0005, 0, 4)  # GL_TRIANGLE_STRIP
        self._vao.release()
        image = self._fbo.toImage()
        self._fbo.release()
        return image


def _qimage_premul_rgba(image: Any) -> tuple[bytes, int, int]:
    """Premultiplied RGBA bytes, top row first. Does not divide RGB by alpha."""
    from PySide6.QtGui import QImage

    return _qimage_packed(image, QImage.Format.Format_RGBA8888_Premultiplied)


def _qimage_rgba(image: Any) -> tuple[bytes, int, int]:
    """Straight RGBA bytes, top row first."""
    from PySide6.QtGui import QImage

    return _qimage_packed(image, QImage.Format.Format_RGBA8888)


def _qimage_packed(image: Any, fmt: Any) -> tuple[bytes, int, int]:
    converted = image.convertToFormat(fmt)
    width, height = converted.width(), converted.height()
    stride = int(converted.bytesPerLine())
    raw = bytes(converted.constBits())
    row = width * 4
    if stride == row:
        return raw[: row * height], width, height
    return b"".join(raw[y * stride : y * stride + row] for y in range(height)), width, height


def main() -> int:
    """Show the figure until stdin sends ``quit`` or closes."""
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "darwin":
        # A command-line QApplication activates itself and takes a Dock icon.
        # This process is only the figure. Set before QApplication is built.
        import os

        os.environ["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] = "1"
    if sys.platform == "win32":
        from dodaios.core.win32_dpi import ensure_dpi_awareness

        ensure_dpi_awareness()
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QColor, QRegion, QSurfaceFormat
        from PySide6.QtWidgets import QApplication
    except Exception as exc:  # noqa: BLE001 — the parent logs the exit and keeps the strip
        log.error("PySide6 is not available (%s); the shader figure cannot be shown", exc)
        return 1

    fmt = QSurfaceFormat()
    fmt.setVersion(3, 2)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv[:1] or ["dodaios-shader-pet"])
    app.setQuitOnLastWindowClosed(False)
    # After QApplication has created NSApp. Earlier, pyobjc owns it and Qt
    # puts the Python rocket back in the Dock.
    from dodaios.platform.qt_sidecar import hide_from_dock

    hide_from_dock()

    commands: queue.Queue[dict[str, Any]] = queue.Queue()

    def _read_stdin() -> None:
        for line in sys.stdin:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                commands.put(message)
        commands.put({"op": "quit"})

    import threading

    threading.Thread(target=_read_stdin, name="shader-pet-stdin", daemon=True).start()

    strip: Any = None
    if sys.platform == "win32":
        figure: Any = _WinFigure()
    else:
        figure = _QtFigure(QColor, QRegion)
        # The control strip is a second window. Tk paints its clear pixels
        # black, so the gaps between the bell, the pill and the phone vanish.
        strip = _QtFigure(QColor, QRegion, who="strip")
        strip._disc = False
    session = _Session()
    gl = _Gl()

    def _tick() -> None:
        while True:
            try:
                message = commands.get_nowait()
            except queue.Empty:
                break
            op = message.get("op")
            if op == "quit":
                app.quit()
                return
            if op == "hide":
                session.shown = False
                session.sprite = None
                figure.hide()
            elif op == "strip-hide" and strip is not None:
                strip.hide()
            elif op == "strip" and strip is not None:
                # The strip's clear pixels are the desktop, same as a sprite.
                # ``w``/``h`` are logical points. A retina PNG is larger; its
                # device ratio keeps those pixels from being scaled up.
                # A fade is a premultiplied frame, not a window-opacity change:
                # setWindowOpacity does nothing on this translucent window.
                image = strip_frame(message.get("png"), bool(message.get("premul")))
                width = int(message.get("w") or 1)
                height = int(message.get("h") or 1)
                strip.place(
                    int(message.get("x") or 0),
                    int(message.get("y") or 0),
                    width,
                    height,
                )
                strip.show()
                if image is not None:
                    if width > 0 and image.width() > width:
                        image.setDevicePixelRatio(image.width() / width)
                    strip.present(image)
            elif op == "sprite":
                # A pixel pet. Tk's window paints its clear pixels black on
                # macOS, so this window shows the frame with real alpha.
                session.source = ""
                session.sprite = _png_image(message.get("png"))
                session.shown = True
                if hasattr(figure, "_disc"):
                    figure._disc = False
                figure.place(
                    int(message.get("x") or 0),
                    int(message.get("y") or 0),
                    int(message.get("w") or 1),
                    int(message.get("h") or 1),
                )
                figure.show()
                if session.sprite is not None:
                    figure.present(session.sprite)
            elif op == "show":
                session.sprite = None
                session.source = str(message.get("source") or "")
                if hasattr(figure, "_disc"):
                    figure._disc = figure_clips_to_disc(session.source)
                session.state = int(message.get("state") or 0)
                session.level = _unit(message.get("level"))
                session.level_from = 0.0
                session.backdrop = _unit(message.get("backdrop"))
                session.blend = {
                    "from": float(session.state),
                    "to": float(session.state),
                    "value": 1.0,
                }
                figure.place(
                    int(message.get("x") or 0),
                    int(message.get("y") or 0),
                    int(message.get("w") or 1),
                    int(message.get("h") or 1),
                )
                session.shown = True
                figure.show()
            elif op == "place" and not figure.dragging:
                figure.place(
                    int(message.get("x") or 0),
                    int(message.get("y") or 0),
                    int(message.get("w") or 1),
                    int(message.get("h") or 1),
                )
            elif op == "state":
                leaving = int(session.blend["to"])
                session.level_from = (
                    session.level if leaving in _VOICE_STATE_INDEXES else 0.0
                )
                session.state = int(message.get("state") or 0)
            elif op == "level":
                session.level = _unit(message.get("level"))
            elif op == "backdrop":
                session.backdrop = _unit(message.get("backdrop"))
        if session.sprite is not None or not session.shown or not session.source:
            return
        now = time.monotonic()
        # shortcut: the desktop has no reduced-motion signal yet, so the mix always eases
        step_shader_blend(session.blend, session.state, now - session.last, False)
        session.last = now
        width, height = figure.pixel_size()
        image = gl.frame(
            session.source,
            width,
            height,
            now - session.t0,
            session.blend,
            session.level,
            session.level_from,
        )
        if image is not None:
            # A model fills the frame. A shader and the orb get a disc behind
            # them; the corners of that image stay clear. Not setMask.
            if session.backdrop > 0.0 and not session.source.startswith("// model "):
                # A shader sphere already meets the frame. The orb sits inside
                # it, so its disc keeps 60% of the old overflow.
                radius = _JARVIS_DISC_RADIUS if session.source.startswith("// scene ") else 1.0
                image = apply_disc_backdrop(image, session.backdrop, radius)
            figure.present(image)

    timer = QTimer()
    timer.timeout.connect(_tick)
    timer.start(33)
    _emit({"op": "ready"})
    return app.exec()


class _Session:
    def __init__(self) -> None:
        self.source = ""
        self.state = 0
        self.blend = {"from": 0.0, "to": 0.0, "value": 1.0}
        self.shown = False
        self.level = 0.0
        self.level_from = 0.0
        self.backdrop = 0.0
        self.sprite: Any = None
        now = time.monotonic()
        self.t0 = now
        self.last = now


class _QtFigure:
    """Translucent, non-activating window. The disc takes clicks; the corners do not."""

    def __init__(self, qcolor: Any, qregion: Any, who: str = "") -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QPainter
        from PySide6.QtWidgets import QWidget

        self._qcolor = qcolor
        self._qregion = qregion
        self._native: Any = None
        self.dragging = False
        self._inside = False
        self._disc = True
        self._who = who
        owner = self

        class _Window(QWidget):
            def __init__(self) -> None:
                super().__init__(None)
                flags = (
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.Tool
                    | Qt.WindowType.NoDropShadowWindowHint
                    | Qt.WindowType.WindowDoesNotAcceptFocus
                )
                self.setWindowFlags(flags)
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
                always = getattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow", None)
                if always is not None:
                    self.setAttribute(always)
                self.setMouseTracking(True)
                self._image: Any = None
                self._press: Any = None
                self._origin: Any = None
                self._dragged = False

            def paintEvent(self, _event: Any) -> None:  # noqa: N802 - Qt override
                painter = QPainter(self)
                try:
                    # Source replaces the backing, including alpha. SourceOver
                    # would leave the previous frame's pixels in place.
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                    painter.fillRect(self.rect(), owner._qcolor(0, 0, 0, 0))
                    if self._image is not None:
                        painter.setCompositionMode(
                            QPainter.CompositionMode.CompositionMode_SourceOver
                        )
                        painter.drawImage(self.rect(), self._image)
                finally:
                    painter.end()

            def enterEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
                owner._hover(True)
                super().enterEvent(event)

            def leaveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
                owner._hover(False)
                super().leaveEvent(event)

            def _at(self, event: Any) -> tuple[int, int]:
                pos = event.position()
                return int(pos.x()), int(pos.y())

            def mousePressEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
                if event.button() == Qt.MouseButton.RightButton:
                    point = event.globalPosition().toPoint()
                    owner._emit_event({"op": "menu", "x": int(point.x()), "y": int(point.y())})
                    event.accept()
                    return
                if event.button() == Qt.MouseButton.LeftButton:
                    self._press = event.globalPosition().toPoint()
                    self._origin = self.pos()
                    self._dragged = False
                    if owner._who == "strip":
                        local_x, local_y = self._at(event)
                        owner._emit_event({"op": "press", "x": local_x, "y": local_y})
                    event.accept()
                    return
                super().mousePressEvent(event)

            def mouseMoveEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
                owner._hover(True)
                if self._press is None:
                    if owner._who == "strip":
                        local_x, local_y = self._at(event)
                        owner._emit_event({"op": "point", "x": local_x, "y": local_y})
                    super().mouseMoveEvent(event)
                    return
                delta = event.globalPosition().toPoint() - self._press
                if not self._dragged and abs(delta.x()) + abs(delta.y()) < _DRAG_THRESHOLD_PX:
                    return
                self._dragged = True
                owner.dragging = True
                self.move(self._origin + delta)
                owner._emit_event({"op": "move", "x": int(self.x()), "y": int(self.y())})

            def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
                dragged = self._dragged
                self._press = None
                self._dragged = False
                owner.dragging = False
                if dragged:
                    owner._emit_event({"op": "drop", "x": int(self.x()), "y": int(self.y())})
                elif owner._who == "strip":
                    local_x, local_y = self._at(event)
                    owner._emit_event({"op": "release", "x": local_x, "y": local_y})
                super().mouseReleaseEvent(event)

            def mouseDoubleClickEvent(self, event: Any) -> None:  # noqa: N802 - Qt override
                if owner._who == "strip":
                    super().mouseDoubleClickEvent(event)
                    return
                if event.button() == Qt.MouseButton.LeftButton:
                    owner._emit_event({"op": "mute"})
                    event.accept()
                    return
                super().mouseDoubleClickEvent(event)

        self._window = _Window()

    def _emit_event(self, payload: dict[str, Any]) -> None:
        if self._who:
            payload["who"] = self._who
        _emit(payload)

    def _hover(self, inside: bool) -> None:
        if inside == self._inside:
            return
        self._inside = inside
        self._emit_event({"op": "hover", "inside": inside})

    def place(self, x: int, y: int, w: int, h: int) -> None:
        self._window.setGeometry(int(x), int(y), max(1, int(w)), max(1, int(h)))
        if self._disc:
            # The sphere is the inscribed disc. Corners stay outside the window,
            # so they neither paint nor take the click.
            self._window.setMask(
                self._qregion(
                    0, 0, max(1, int(w)), max(1, int(h)), self._qregion.RegionType.Ellipse
                )
            )
        else:
            self._window.clearMask()

    def show(self) -> None:
        self._window.show()
        self._macos_panel()
        self._raise()

    def hide(self) -> None:
        self._window.hide()

    def pixel_size(self) -> tuple[int, int]:
        ratio = float(self._window.devicePixelRatio() or 1.0)
        return (
            max(1, int(round(self._window.width() * ratio))),
            max(1, int(round(self._window.height() * ratio))),
        )

    def present(self, image: Any) -> None:
        self._window._image = image
        self._window.update()
        self._raise()

    def _raise(self) -> None:
        native = self._native
        if native is not None:
            native.orderFrontRegardless()
            return
        if sys.platform != "darwin":
            self._window.raise_()

    def _macos_panel(self) -> None:
        if sys.platform != "darwin" or self._native is not None:
            return
        try:
            from ctypes import c_void_p

            import objc  # type: ignore[import-not-found]
            from AppKit import NSWindowStyleMaskNonactivatingPanel  # type: ignore[import-not-found]

            view = objc.objc_object(c_void_p=c_void_p(int(self._window.winId())))
            native = view.window()
            if native is None:
                return
            native.setStyleMask_(int(native.styleMask()) | int(NSWindowStyleMaskNonactivatingPanel))
            native.setBecomesKeyOnlyIfNeeded_(True)
            native.setHidesOnDeactivate_(False)
            native.setAcceptsMouseMovedEvents_(True)
            self._native = native
        except Exception:
            log.debug("shader figure could not become a non-activating panel", exc_info=True)


class _WinFigure:
    """A layered popup. Qt draws offscreen; Windows shows the bitmap."""

    def __init__(self) -> None:
        self.dragging = False
        self._hwnd: int | None = None
        self._x = 0
        self._y = 0
        self._w = 1
        self._h = 1
        self._proc: Any = None
        self._press: tuple[int, int] | None = None
        self._origin: tuple[int, int] | None = None
        self._hovering = False

    def place(self, x: int, y: int, w: int, h: int) -> None:
        self._x, self._y = int(x), int(y)
        self._w, self._h = max(1, int(w)), max(1, int(h))
        hwnd = self._ensure()
        if hwnd:
            self._move(hwnd, self._x, self._y, self._w, self._h)

    def show(self) -> None:
        hwnd = self._ensure()
        if hwnd:
            import ctypes

            ctypes.windll.user32.ShowWindow(hwnd, 8)  # SW_SHOWNA

    def hide(self) -> None:
        if self._hwnd:
            import ctypes

            ctypes.windll.user32.ShowWindow(self._hwnd, 0)  # SW_HIDE

    def pixel_size(self) -> tuple[int, int]:
        return self._w, self._h

    def present(self, image: Any) -> None:
        hwnd = self._ensure()
        if not hwnd:
            return
        from PIL import Image

        from dodaios.platform.layered_window import update_layered

        raw, width, height = _qimage_rgba(image)
        update_layered(int(hwnd), Image.frombytes("RGBA", (width, height), raw))
        self._pump()

    def _ensure(self) -> int | None:
        if self._hwnd:
            return self._hwnd
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        windll_kernel = ctypes.windll.kernel32

        callback = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        def _on_message(hwnd, msg, wparam, lparam):  # type: ignore[no-untyped-def]
            return self._proc_message(hwnd, msg, wparam, lparam)

        proc = callback(_on_message)
        self._proc = proc
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        instance = windll_kernel.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
        wc.hInstance = instance
        wc.hCursor = user32.LoadCursorW(None, 32512)  # IDC_ARROW
        wc.lpszClassName = "DodaiosShaderPet"
        user32.RegisterClassW(ctypes.byref(wc))
        hwnd = user32.CreateWindowExW(
            0x00080000 | 0x00000008 | 0x00000080 | 0x08000000,
            "DodaiosShaderPet",
            "Dodaios shader pet",
            0x80000000,  # WS_POPUP
            self._x,
            self._y,
            self._w,
            self._h,
            None,
            None,
            instance,
            None,
        )
        self._hwnd = int(hwnd) if hwnd else None
        return self._hwnd

    def _proc_message(self, hwnd: int, msg: int, wparam: int, lparam: int) -> int:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        if msg == 0x0201:  # WM_LBUTTONDOWN
            point = self._cursor()
            rect = self._rect(hwnd)
            self._press = point
            self._origin = (rect[0], rect[1])
            self.dragging = False
            user32.SetCapture(hwnd)
            return 0
        if msg == 0x0200 and self._press is not None:  # WM_MOUSEMOVE
            point = self._cursor()
            if not self._hovering:
                self._hovering = True
                _emit({"op": "hover", "inside": True})
            self._track_leave(hwnd)
            dx = point[0] - self._press[0]
            dy = point[1] - self._press[1]
            past = abs(dx) + abs(dy) >= _DRAG_THRESHOLD_PX
            if self._origin is not None and (self.dragging or past):
                self.dragging = True
                x, y = self._origin[0] + dx, self._origin[1] + dy
                self._x, self._y = x, y
                self._move(hwnd, x, y, self._w, self._h)
                _emit({"op": "move", "x": x, "y": y})
            return 0
        if msg == 0x02A3:  # WM_MOUSELEAVE
            self._hovering = False
            _emit({"op": "hover", "inside": False})
            return 0
        if msg == 0x0202 and self._press is not None:  # WM_LBUTTONUP
            user32.ReleaseCapture()
            dragged = self.dragging
            self._press = None
            self.dragging = False
            if dragged:
                _emit({"op": "drop", "x": self._x, "y": self._y})
            return 0
        if msg == 0x0204:  # WM_RBUTTONDOWN
            point = self._cursor()
            _emit({"op": "menu", "x": point[0], "y": point[1]})
            return 0
        if msg == 0x0203:  # WM_LBUTTONDBLCLK
            _emit({"op": "mute"})
            return 0
        return int(user32.DefWindowProcW(hwnd, msg, wparam, lparam))

    def _cursor(self) -> tuple[int, int]:
        import ctypes
        from ctypes import wintypes

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        point = POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        return int(point.x), int(point.y)

    def _rect(self, hwnd: int) -> tuple[int, int, int, int]:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        rect = RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)

    def _move(self, hwnd: int, x: int, y: int, w: int, h: int) -> None:
        import ctypes

        ctypes.windll.user32.SetWindowPos(
            hwnd,
            -1,  # HWND_TOPMOST
            int(x),
            int(y),
            int(w),
            int(h),
            0x0010,  # SWP_NOACTIVATE
        )

    def _track_leave(self, hwnd: int) -> None:
        import ctypes
        from ctypes import wintypes

        class TRACKMOUSEEVENT(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("hwndTrack", wintypes.HWND),
                ("dwHoverTime", wintypes.DWORD),
            ]

        event = TRACKMOUSEEVENT()
        event.cbSize = ctypes.sizeof(TRACKMOUSEEVENT)
        event.dwFlags = 0x00000002  # TME_LEAVE
        event.hwndTrack = hwnd
        ctypes.windll.user32.TrackMouseEvent(ctypes.byref(event))

    def _pump(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class MSG(ctypes.Structure):
            _fields_ = [
                ("hwnd", wintypes.HWND),
                ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM),
                ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD),
                ("pt_x", wintypes.LONG),
                ("pt_y", wintypes.LONG),
            ]

        msg = MSG()
        while user32.PeekMessageW(ctypes.byref(msg), self._hwnd, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    raise SystemExit(main())
