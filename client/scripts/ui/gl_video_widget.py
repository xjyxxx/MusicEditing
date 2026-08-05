"""OpenGL 视频/图像显示：RGB24 上传为纹理后绘制（Qt OpenGL Core 3.3）。"""

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

GL_FLOAT = 0x1406
GL_COLOR_BUFFER_BIT = 0x00004000
GL_TRIANGLE_STRIP = 0x0005


_VERT = """#version 330 core
layout(location = 0) in vec2 aPos;
layout(location = 1) in vec2 aUv;
out vec2 vUv;
void main() {
    vUv = aUv;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_FRAG = """#version 330 core
in vec2 vUv;
out vec4 FragColor;
uniform sampler2D uTex;
void main() {
    FragColor = texture(uTex, vUv);
}
"""


def _default_surface_format() -> QSurfaceFormat:
    fmt = QSurfaceFormat()
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSwapBehavior(QSurfaceFormat.DoubleBuffer)
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    return fmt


class GlVideoWidget(QOpenGLWidget):
    """将 RGB24 帧作为 OpenGL 纹理绘制；无帧时显示占位文字。点击画面可切换播放。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFormat(_default_surface_format())
        self.setMinimumHeight(240)
        self.setStyleSheet("background: #080A0E; border-radius: 10px;")
        self.setCursor(Qt.PointingHandCursor)

        self._placeholder = "请打开本地视频或音乐"
        self._has_frame = False
        self._tex_w = 0
        self._tex_h = 0
        self._pending_image: QImage | None = None
        self._pending_keep: bytes | None = None
        self._paused_overlay = False
        self._subtitle_text = ""

        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo: QOpenGLBuffer | None = None
        self._texture: QOpenGLTexture | None = None
        self._gl_ready = False

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text or ""
        if not self._has_frame:
            self.update()

    def set_paused_overlay(self, paused: bool) -> None:
        """暂停时在画面中央显示三角播放标志（提示点击继续）。"""
        paused = bool(paused)
        if self._paused_overlay == paused:
            return
        self._paused_overlay = paused
        self.update()

    def set_subtitle_text(self, text: str) -> None:
        text = (text or "").strip()
        if self._subtitle_text == text:
            return
        self._subtitle_text = text
        self.update()

    def clear_frame(self) -> None:
        self._has_frame = False
        self._pending_image = None
        self._pending_keep = None
        self.update()

    def set_rgb_frame(self, rgb: bytes | bytearray, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        need = width * height * 3
        if len(rgb) < need:
            return
        # 单次拷贝保留缓冲；垂直翻转改由 UV（避免 mirrored+copy）
        keep = bytes(rgb[:need]) if not isinstance(rgb, (bytes, bytearray)) else bytes(rgb[:need])
        img = QImage(keep, width, height, width * 3, QImage.Format_RGB888)
        self._pending_keep = keep
        self._pending_image = img
        self._has_frame = True
        self.update()

    def set_qimage(self, image: QImage) -> None:
        if image.isNull():
            return
        # 与视频帧一致：不做 mirrored，由绘制 UV 翻转
        img = image.convertToFormat(QImage.Format_RGB888)
        self._pending_keep = None
        self._pending_image = img.copy() if img.isNull() is False else img
        self._has_frame = True
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(640, 360)

    def initializeGL(self) -> None:
        self._program = QOpenGLShaderProgram(self)
        ok = (
            self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, _VERT)
            and self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, _FRAG)
            and self._program.link()
        )
        if not ok:
            self._gl_ready = False
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
            self._gl_ready = False
            return
        self._vao.bind()

        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        if not self._vbo.create():
            self._gl_ready = False
            return
        self._vbo.bind()
        self._vbo.allocate(raw, len(raw))

        self._program.bind()
        self._program.enableAttributeArray(0)
        self._program.setAttributeBuffer(0, GL_FLOAT, 0, 2, 16)
        self._program.enableAttributeArray(1)
        self._program.setAttributeBuffer(1, GL_FLOAT, 8, 2, 16)
        self._program.release()
        self._vbo.release()
        self._vao.release()
        self._gl_ready = True

    def resizeGL(self, w: int, h: int) -> None:
        funcs = self.context().functions() if self.context() else None
        if funcs:
            funcs.glViewport(0, 0, max(1, w), max(1, h))

    def paintGL(self) -> None:
        funcs = self.context().functions() if self.context() else None
        if not funcs:
            return
        funcs.glClearColor(0.039, 0.039, 0.071, 1.0)
        funcs.glClear(GL_COLOR_BUFFER_BIT)

        if self._pending_image is not None:
            self._upload_texture(self._pending_image)
            self._pending_image = None
            self._pending_keep = None

        drew_frame = bool(
            self._gl_ready and self._has_frame and self._texture and self._program
        )
        if drew_frame:
            self._draw_textured_quad()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        if not drew_frame:
            painter.setPen(Qt.gray)
            painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
        if self._subtitle_text:
            self._draw_subtitle(painter)
        if self._paused_overlay:
            self._draw_play_icon(painter)
        painter.end()

    def _draw_subtitle(self, painter: QPainter) -> None:
        """底部半透明字幕条。"""
        text = self._subtitle_text
        if not text:
            return
        margin = max(12, int(self.width() * 0.06))
        bottom = max(16, int(self.height() * 0.06))
        max_w = max(40, self.width() - margin * 2)
        font = painter.font()
        font.setPointSize(max(14, int(min(self.width(), self.height()) * 0.035)))
        font.setBold(True)
        painter.setFont(font)
        br = painter.boundingRect(
            0, 0, max_w, self.height(),
            Qt.AlignHCenter | Qt.AlignBottom | Qt.TextWordWrap,
            text,
        )
        pad_x, pad_y = 14, 8
        box_w = min(max_w, br.width() + pad_x * 2)
        box_h = br.height() + pad_y * 2
        box_x = (self.width() - box_w) // 2
        box_y = self.height() - bottom - box_h
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
        painter.drawRoundedRect(QRectF(box_x, box_y, box_w, box_h), 6, 6)
        painter.setPen(QColor(255, 255, 240))
        painter.drawText(
            QRectF(box_x + pad_x, box_y + pad_y, box_w - pad_x * 2, box_h - pad_y * 2),
            Qt.AlignHCenter | Qt.AlignVCenter | Qt.TextWordWrap,
            text,
        )

    def _draw_play_icon(self, painter: QPainter) -> None:
        """暂停时显示三角播放标志（提示点击继续）。"""
        side = min(self.width(), self.height())
        r = max(28, int(side * 0.11))
        cx = self.width() // 2
        cy = self.height() // 2

        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(0, 0, 0, 150)))
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 略偏右，视觉上更居中
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
        self._texture = QOpenGLTexture(image)
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

        # QImage 顶→底；OpenGL 纹理底→顶：用 V 翻转 UV，避免每帧 mirrored
        verts = [
            -sx, -sy, 0.0, 1.0,
             sx, -sy, 1.0, 1.0,
            -sx,  sy, 0.0, 0.0,
             sx,  sy, 1.0, 0.0,
        ]
        raw = array.array("f", verts).tobytes()
        self._vao.bind()
        self._vbo.bind()
        # PySide6: write(offset, data, count)
        self._vbo.write(0, raw, len(raw))

        self._program.bind()
        self._texture.bind()
        self._program.setUniformValue("uTex", 0)
        funcs = self.context().functions()
        funcs.glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)
        self._texture.release()
        self._program.release()
        self._vbo.release()
        self._vao.release()

    def cleanup_gl(self) -> None:
        if not self.context():
            return
        self.makeCurrent()
        try:
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
        finally:
            self.doneCurrent()
        self._gl_ready = False
