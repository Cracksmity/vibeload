"""Símbolo Play-Drop: geometría compartida por la app y por brand/build_playdrop.py.

Un triángulo hacia abajo (play girado = video, flecha = descarga, V = Vibe) con
dos ranuras desde el borde superior que dibujan tres barras de ecualizador.
"""
import math

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy, QWidget

# Maestro sobre lienzo de 256: barras de 53 / 42 / 53, ranuras de 14.
MASTER_GEOM = dict(
    x0=40, x1=216, top=64, apex_y=216, slits=((93, 107), (149, 163)), notch_y=124, r_outer=26, r_inner=3
)

# Cortes por tamaño (unidades = píxeles de ese tamaño). Bordes verticales y
# superiores en píxel entero; vértice inferior centrado en la grilla.
SMALL_CUTS = {
    16: dict(x0=2.5, x1=13.5, top=4, apex_y=13.6, r_outer=1.6),
    20: dict(x0=3, x1=17, top=5, apex_y=17, slits=((7, 8), (12, 13)), notch_y=10, r_outer=2, r_inner=0.2),
    24: dict(x0=3, x1=21, top=6, apex_y=21.5, slits=((8, 10), (14, 16)), notch_y=12, r_outer=2.4, r_inner=0.3),
    32: dict(x0=4, x1=28, top=8, apex_y=28.8, slits=((11, 13), (19, 21)), notch_y=16, r_outer=3.2, r_inner=0.4),
    48: dict(x0=6, x1=42, top=12, apex_y=43, slits=((16, 19), (29, 32)), notch_y=24, r_outer=4.8, r_inner=0.6),
}


def outline(x0, x1, top, apex_y, slits=(), notch_y=None, r_outer=0, r_inner=0):
    """Contorno como lista de esquinas (a, vértice, b): recta hasta a, curva a b."""
    cx = (x0 + x1) / 2
    pts, radii = [(x0, top)], [r_outer]
    for a, b in slits:
        half = (b - a) / 2
        pts += [(a, top), (a, notch_y), (b, notch_y), (b, top)]
        radii += [r_inner, half, half, r_inner]
    pts += [(x1, top), (cx, apex_y)]
    radii += [r_outer, r_outer]

    corners = []
    n = len(pts)
    for i in range(n):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % n]
        v_in = (p0[0] - p1[0], p0[1] - p1[1])
        v_out = (p2[0] - p1[0], p2[1] - p1[1])
        l_in, l_out = math.hypot(*v_in), math.hypot(*v_out)
        d = min(radii[i], l_in * 0.45, l_out * 0.45)
        a = (p1[0] + v_in[0] / l_in * d, p1[1] + v_in[1] / l_in * d)
        b = (p1[0] + v_out[0] / l_out * d, p1[1] + v_out[1] / l_out * d)
        corners.append((a, p1, b))
    return corners


def svg_path_d(geom) -> str:
    corners = outline(**geom)
    f = lambda v: f"{v:.2f}".rstrip("0").rstrip(".")  # noqa: E731
    d = f"M{f(corners[0][2][0])} {f(corners[0][2][1])}"
    for a, c, b in corners[1:] + corners[:1]:
        d += f" L{f(a[0])} {f(a[1])} Q{f(c[0])} {f(c[1])} {f(b[0])} {f(b[1])}"
    return d + " Z"


def painter_path(geom=None, scale=1.0, dx=0.0, dy=0.0) -> QPainterPath:
    corners = outline(**(geom or MASTER_GEOM))
    pt = lambda p: QPointF(p[0] * scale + dx, p[1] * scale + dy)  # noqa: E731
    path = QPainterPath(pt(corners[0][2]))
    for a, c, b in corners[1:] + corners[:1]:
        path.lineTo(pt(a))
        path.quadTo(pt(c), pt(b))
    path.closeSubpath()
    return path


class BrandMark(QWidget):
    """Símbolo sin placa, del color de acento del tema (cabecera de la ventana)."""

    def __init__(self, size: int = 22, parent=None):
        super().__init__(parent)
        self._size = size
        self._color = QColor("#B69CFF")
        self.setFixedSize(size, size)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_color(self, color: str):
        self._color = QColor(color)
        self.update()

    def sizeHint(self):
        return QSize(self._size, self._size)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # El maestro ocupa x 40..216 / y 64..216 del lienzo de 256: se recorta
        # ese margen para que el símbolo llene el widget.
        s = self._size / 176
        path = painter_path(MASTER_GEOM, s, -40 * s, -64 * s + (self._size - 152 * s) / 2)
        p.fillPath(path, self._color)
        p.end()
