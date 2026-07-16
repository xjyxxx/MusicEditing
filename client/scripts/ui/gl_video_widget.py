"""OpenGL 视频/图像显示：RGB24 上传为纹理后绘制（Qt OpenGL Core 3.3）。"""

from __future__ import annotations

import array

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QImage, QPainter, QSurfaceFormat
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
    """将 RGB24 帧作为 OpenGL 纹理绘制；无帧时显示占位文字。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFormat(_default_surface_format())
        self.setMinimumHeight(240)
        self.setStyleSheet("background: #0a0a12; border-radius: 6px;")

        self._placeholder = "请打开本地视频"
        self._has_frame = False
        self._tex_w = 0
        self._tex_h = 0
        self._pending_image: QImage | None = None

        self._program: QOpenGLShaderProgram | None = None
        self._vao: QOpenGLVertexArrayObject | None = None
        self._vbo: QOpenGLBuffer | None = None
        self._texture: QOpenGLTexture | None = None
        self._gl_ready = False

    def set_placeholder(self, text: str) -> None:
        self._placeholder = text or ""
        if not self._has_frame:
            self.update()

    def clear_frame(self) -> None:
        self._has_frame = False
        self._pending_image = None
        self.update()

    def set_rgb_frame(self, rgb: bytes | bytearray, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            return
        need = width * height * 3
        if len(rgb) < need:
            return
        img = QImage(bytes(rgb[:need]), width, height, width * 3, QImage.Format_RGB888)
        # OpenGL 纹理原点在左下，QImage 在左上
        self._pending_image = img.copy().mirrored(False, True)
        self._has_frame = True
        self.update()

    def set_qimage(self, image: QImage) -> None:
        if image.isNull():
            return
        img = image.convertToFormat(QImage.Format_RGB888)
        self._pending_image = img.copy().mirrored(False, True)
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

        if self._gl_ready and self._has_frame and self._texture and self._program:
            self._draw_textured_quad()
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.TextAntialiasing)
        painter.setPen(Qt.gray)
        painter.drawText(self.rect(), Qt.AlignCenter, self._placeholder)
        painter.end()

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

        verts = [
            -sx, -sy, 0.0, 0.0,
             sx, -sy, 1.0, 0.0,
            -sx,  sy, 0.0, 1.0,
             sx,  sy, 1.0, 1.0,
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
