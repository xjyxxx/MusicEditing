"""视频/图像显示：优先 OpenGL 纹理；失败则纯 QWidget 软件绘制（避免有声无画）。"""

from __future__ import annotations

import array

from PySide6.QtCore import Qt, QSize, QRectF, QPointF, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPolygonF, QSurfaceFormat, QMouseEvent
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLTexture,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QWidget

GL_FLOAT = 0x1406
GL_COLOR_BUFFER_BIT = 0x00004000
GL_TRIANGLE_STRIP = 0x0005

# 兼容 Profile + GLSL 120：远程桌面 / Mesa / 软件 GL 常不支持 Core 3.30
_VERT = """#version 120
attribute vec2 aPos;
attribute vec2 aUv;
varying vec2 vUv;
void main() {
    vUv = aUv;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_FRAG = """#version 120
varying vec2 vUv;
uniform sampler2D uTex;
uniform float uExposure;
uniform float uContrast;
uniform float uSaturation;
uniform float uTemperature;
void main() {
    vec3 color = texture2D(uTex, vUv).rgb;
    color *= exp2(uExposure);
    color = (color - vec3(0.5)) * (1.0 + uContrast) + vec3(0.5);
    float luminance = dot(color, vec3(0.2126, 0.7152, 0.0722));
    color = mix(vec3(luminance), color, 1.0 + uSaturation);
    color.r += uTemperature * 0.08;
    color.b -= uTemperature * 0.08;
    gl_FragColor = vec4(clamp(color, 0.0, 1.0), 1.0);
}
"""


def _default_surface_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    fmt.setVersion(2, 1)
    fmt.setProfile(QSurfaceFormat.CompatibilityProfile)
    return fmt


def _draw_play_icon(painter: QPainter, width: int, height: int) -> None:
    side = min(width, height)
    r = max(28, int(side * 0.11))
    cx = width // 2
    cy = height // 2
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(QColor(0, 0, 0, 150)))
    painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
    tri_w = max(16, int(r * 0.7))
    tri_h = max(20, int(r * 0.85))
    ox = cx - tri_w // 3
    top = cy - tri_h // 2
    poly = QPolygonF([
        QPointF(ox, top),
        QPointF(ox, top + tri_h),
        QPointF(ox + tri_w, cy),
    ])
    painter.setBrush(QBrush(QColor(255, 255, 255, 235)))
    painter.drawPolygon(poly)


def _draw_frame_letterbox(
    painter: QPainter,
    image: QImage,
    width: int,
    height: int,
    zoom: float = 1.0,
) -> None:
    if image.isNull():
        return
    iw, ih = max(1, image.width()), max(1, image.height())
    scale = min(width / float(iw), height / float(ih)) * zoom
    tw, th = iw * scale, ih * scale
    target = QRectF((width - tw) * 0.5, (height - th) * 0.5, tw, th)
    painter.drawImage(target, image)


class SoftVideoWidget(QWidget):
    """纯软件绘制（QPainter）。OpenGL 不可用时的可靠回退，避免有声黑屏。"""

    clicked = Signal()
    renderReady = Signal()
    renderFailed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(8, 10, 14))
        self.setPalette(pal)
        self.setCursor(Qt.PointingHandCursor)
        self._placeholder = "请打开本地视频或音乐"
        self._has_frame = False
        self._current_image: QImage | None = None
        self._pending_keep: bytes | None = None
        self._paused_overlay = False
        self._photo_adjustments = (0.0, 0.0, 0.0, 0.0)
        self._view_zoom = 1.0
        self._gl_error = "software"
        self._ready_emitted = False

    @property
    def gl_ready(self) -> bool:
        return False

    @property
    def gl_error(self) -> str:
        return self._gl_error

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text or ""
        if not self._has_frame:
            self.update()

    def set_paused_overlay(self, paused: bool) -> None:
        paused = bool(paused)
        if self._paused_overlay == paused:
            return
        self._paused_overlay = paused
        self.update()

    def set_photo_adjustments(
        self, exposure: float = 0.0, contrast: float = 0.0,
        saturation: float = 0.0, temperature: float = 0.0,
    ) -> None:
        self._photo_adjustments = (
            max(-3.0, min(3.0, float(exposure))),
            max(-1.0, min(1.0, float(contrast))),
            max(-1.0, min(1.0, float(saturation))),
            max(-1.0, min(1.0, float(temperature))),
        )
        self.update()

    def set_view_zoom(self, zoom: float = 1.0) -> None:
        value = max(0.25, min(4.0, float(zoom)))
        if abs(value - self._view_zoom) < 1e-6:
            return
        self._view_zoom = value
        self.update()

    def clear_frame(self) -> None:
        self._has_frame = False
        self._pending_keep = None
        self._current_image = None
        self.update()

    def set_rgb_frame(self, rgb: bytes | bytearray, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        need = width * height * 3
        if len(rgb) < need:
            return
        if isinstance(rgb, bytes) and len(rgb) == need:
            keep = rgb
        else:
            keep = bytes(rgb[:need])
        img = QImage(keep, width, height, width * 3, QImage.Format_RGB888)
        self._pending_keep = keep
        self._current_image = img
        self._has_frame = True
        self.update()
        if not self._ready_emitted:
            self._ready_emitted = True
            self.renderReady.emit()

    def set_qimage(self, image: QImage) -> None:
        if image.isNull():
            return
        img = image.convertToFormat(QImage.Format_RGB888).copy()
        self._pending_keep = None
        self._current_image = img
        self._has_frame = True
        self.update()
        if not self._ready_emitted:
            self._ready_emitted = True
            self.renderReady.emit()

    def sizeHint(self) -> QSize:
        return QSize(640, 360)

    def cleanup_gl(self) -> None:
        return

    def paintEvent(self, event) -> None:  # noqa: ARG002
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(8, 10, 14))
        if self._has_frame and self._current_image is not None:
            _draw_frame_letterbox(
                painter, self._current_image, self.width(), self.height(), self._view_zoom,
            )
        else:
            painter.setPen(Qt.gray)
            painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
        if self._paused_overlay:
            _draw_play_icon(painter, self.width(), self.height())
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class GlVideoWidget(QOpenGLWidget):
    """RGB 帧 OpenGL 纹理绘制；初始化/绘制失败时由调用方切到 SoftVideoWidget。"""

    clicked = Signal()
    renderReady = Signal()
    renderFailed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFormat(_default_surface_format())
        self.setMinimumHeight(240)
        # 勿对 QOpenGLWidget 设 border-radius：Windows 上易导致原生子窗口黑屏
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(8, 10, 14))
        self.setPalette(pal)
        self.setCursor(Qt.PointingHandCursor)

        self._placeholder = "请打开本地视频或音乐"
        self._has_frame = False
        self._tex_w = 0
        self._tex_h = 0
        self._pending_image: QImage | None = None
        self._pending_keep: bytes | None = None
        self._current_image: QImage | None = None
        self._paused_overlay = False
        self._photo_adjustments = (0.0, 0.0, 0.0, 0.0)
        self._view_zoom = 1.0

        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo: QOpenGLBuffer | None = None
        self._texture: QOpenGLTexture | None = None
        self._uniform_locations: dict[str, int] = {}
        self._gl_ready = False
        self._render_ready_emitted = False
        self._gl_error = ""
        self._fail_emitted = False

    @property
    def gl_ready(self) -> bool:
        return self._gl_ready

    @property
    def gl_error(self) -> str:
        return self._gl_error

    def _fail_gl(self, reason: str) -> None:
        self._gl_ready = False
        self._gl_error = reason or "OpenGL 初始化失败"
        if not self._fail_emitted:
            self._fail_emitted = True
            self.renderFailed.emit(self._gl_error)

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text or ""
        if not self._has_frame:
            self.update()

    def set_paused_overlay(self, paused: bool) -> None:
        paused = bool(paused)
        if self._paused_overlay == paused:
            return
        self._paused_overlay = paused
        self.update()

    def set_photo_adjustments(
        self, exposure: float = 0.0, contrast: float = 0.0,
        saturation: float = 0.0, temperature: float = 0.0,
    ) -> None:
        self._photo_adjustments = (
            max(-3.0, min(3.0, float(exposure))),
            max(-1.0, min(1.0, float(contrast))),
            max(-1.0, min(1.0, float(saturation))),
            max(-1.0, min(1.0, float(temperature))),
        )
        self.update()

    def set_view_zoom(self, zoom: float = 1.0) -> None:
        value = max(0.25, min(4.0, float(zoom)))
        if abs(value - self._view_zoom) < 1e-6:
            return
        self._view_zoom = value
        self.update()

    def clear_frame(self) -> None:
        self._has_frame = False
        self._pending_image = None
        self._pending_keep = None
        self._current_image = None
        self.update()

    def set_rgb_frame(self, rgb: bytes | bytearray, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        need = width * height * 3
        if len(rgb) < need:
            return
        if isinstance(rgb, bytes) and len(rgb) == need:
            keep = rgb
        else:
            keep = bytes(rgb[:need])
        img = QImage(keep, width, height, width * 3, QImage.Format_RGB888)
        self._pending_keep = keep
        self._current_image = img
        self._pending_image = img
        self._has_frame = True
        self.update()

    def set_qimage(self, image: QImage) -> None:
        if image.isNull():
            return
        img = image.convertToFormat(QImage.Format_RGB888).copy()
        self._pending_keep = None
        self._current_image = img
        self._pending_image = img
        self._has_frame = True
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 360)

    def initializeGL(self) -> None:
        context = self.context()
        if context is None or not context.isValid():
            self._fail_gl("OpenGL 上下文不可用")
            return
        try:
            self._program = QOpenGLShaderProgram(self)
            if not self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, _VERT):
                self._fail_gl("顶点 Shader 编译失败: " + self._program.log())
                return
            if not self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, _FRAG):
                self._fail_gl("片元 Shader 编译失败: " + self._program.log())
                return
            if not self._program.link():
                self._fail_gl("Shader 链接失败: " + self._program.log())
                return
            self._uniform_locations = {
                name: self._program.uniformLocation(name.encode("ascii"))
                for name in ("uTex", "uExposure", "uContrast", "uSaturation", "uTemperature")
            }
            missing = [name for name, location in self._uniform_locations.items() if location < 0]
            if missing:
                self._fail_gl("Shader uniform 不可用: " + ", ".join(missing))
                return

            verts = [
                -1.0, -1.0, 0.0, 0.0,
                 1.0, -1.0, 1.0, 0.0,
                -1.0,  1.0, 0.0, 1.0,
                 1.0,  1.0, 1.0, 1.0,
            ]
            raw = array.array("f", verts).tobytes()
            self._vao = QOpenGLVertexArrayObject(self)
            if not self._vao.create():
                self._fail_gl("无法创建 OpenGL VAO")
                return
            self._vao.bind()
            self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
            if not self._vbo.create():
                self._vao.release()
                self._fail_gl("无法创建 OpenGL VBO")
                return
            self._vbo.bind()
            self._vbo.allocate(raw, len(raw))
            self._program.bind()
            loc_pos = self._program.attributeLocation("aPos")
            loc_uv = self._program.attributeLocation("aUv")
            if loc_pos < 0 or loc_uv < 0:
                self._fail_gl("Shader attribute 不可用")
                return
            self._program.enableAttributeArray(loc_pos)
            self._program.setAttributeBuffer(loc_pos, GL_FLOAT, 0, 2, 16)
            self._program.enableAttributeArray(loc_uv)
            self._program.setAttributeBuffer(loc_uv, GL_FLOAT, 8, 2, 16)
            self._program.release()
            self._vbo.release()
            self._vao.release()
            self._gl_error = ""
            self._gl_ready = True
        except Exception as exc:
            self._fail_gl(f"OpenGL 初始化异常: {exc}")

    def resizeGL(self, w: int, h: int) -> None:
        if not self._gl_ready:
            return
        funcs = self.context().functions() if self.context() else None
        if funcs:
            funcs.glViewport(0, 0, max(1, w), max(1, h))

    def paintGL(self) -> None:
        # GL 失败后绝不再 glClear：否则部分驱动上 QPainter 叠画仍是黑屏（有声无画）
        if not self._gl_ready:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.fillRect(self.rect(), QColor(8, 10, 14))
            if self._has_frame and self._current_image is not None:
                _draw_frame_letterbox(
                    painter, self._current_image, self.width(), self.height(), self._view_zoom,
                )
            else:
                painter.setPen(Qt.gray)
                painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
            if self._paused_overlay:
                _draw_play_icon(painter, self.width(), self.height())
            painter.end()
            return

        funcs = self.context().functions() if self.context() else None
        if not funcs:
            self._fail_gl("OpenGL functions 不可用")
            return
        funcs.glClearColor(0.039, 0.039, 0.071, 1.0)
        funcs.glClear(GL_COLOR_BUFFER_BIT)

        if self._pending_image is not None:
            try:
                self._upload_texture(self._pending_image)
                self._pending_image = None
            except Exception as exc:
                self._fail_gl(f"纹理上传失败: {exc}")
                return

        drew_frame = bool(self._has_frame and self._texture and self._program)
        if drew_frame:
            try:
                self._draw_textured_quad()
                if not self._render_ready_emitted:
                    self._render_ready_emitted = True
                    self.renderReady.emit()
            except Exception as exc:
                drew_frame = False
                self._fail_gl(f"OpenGL 绘制失败: {exc}")
                return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        if not drew_frame and self._has_frame and self._current_image is not None:
            _draw_frame_letterbox(
                painter, self._current_image, self.width(), self.height(), self._view_zoom,
            )
        elif not drew_frame:
            painter.setPen(Qt.gray)
            painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
        if self._paused_overlay:
            _draw_play_icon(painter, self.width(), self.height())
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def _upload_texture(self, image: QImage) -> None:
        if self._texture is not None:
            self._texture.destroy()
            self._texture = None
        # 部分驱动对 RGB888 纹理支持差，统一转 RGBA
        rgba = image.convertToFormat(QImage.Format_RGBA8888)
        self._texture = QOpenGLTexture(rgba)
        self._texture.setMinificationFilter(QOpenGLTexture.Linear)
        self._texture.setMagnificationFilter(QOpenGLTexture.Linear)
        self._texture.setWrapMode(QOpenGLTexture.ClampToEdge)
        self._tex_w = image.width()
        self._tex_h = image.height()

    def _draw_textured_quad(self) -> None:
        assert self._program and self._vao and self._vbo and self._texture
        vw = max(1, self.width())
        vh = max(1, self.height())
        tw = max(1, self._tex_w)
        th = max(1, self._tex_h)
        widget_aspect = vw / float(vh)
        tex_aspect = tw / float(th)
        if widget_aspect > tex_aspect:
            sx = tex_aspect / widget_aspect
            sy = 1.0
        else:
            sx = 1.0
            sy = widget_aspect / tex_aspect
        sx *= self._view_zoom
        sy *= self._view_zoom

        verts = [
            -sx, -sy, 0.0, 1.0,
             sx, -sy, 1.0, 1.0,
            -sx,  sy, 0.0, 0.0,
             sx,  sy, 1.0, 0.0,
        ]
        raw = array.array("f", verts).tobytes()
        self._vao.bind()
        self._vbo.bind()
        self._vbo.write(0, raw, len(raw))

        self._program.bind()
        self._texture.bind()
        locations = self._uniform_locations
        self._program.setUniformValue(locations["uTex"], 0)
        exposure, contrast, saturation, temperature = self._photo_adjustments
        self._program.setUniformValue(locations["uExposure"], float(exposure))
        self._program.setUniformValue(locations["uContrast"], float(contrast))
        self._program.setUniformValue(locations["uSaturation"], float(saturation))
        self._program.setUniformValue(locations["uTemperature"], float(temperature))
        funcs = self.context().functions()
        funcs.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        self._texture.release()
        self._program.release()
        self._vbo.release()
        self._vao.release()

    def cleanup_gl(self) -> None:
        context = self.context()
        if context is None or not context.isValid() or not self.isValid():
            self._gl_ready = False
            return
        try:
            self.makeCurrent()
            if self._texture is not None:
                self._texture.destroy()
                self._texture = None
            if self._vbo is not None:
                self._vbo.destroy()
                self._vbo = None
            if self._vao is not None:
                self._vao.destroy()
                self._vao = None
            self._program = None
        except Exception:
            pass
        finally:
            self.doneCurrent()
        self._gl_ready = False
