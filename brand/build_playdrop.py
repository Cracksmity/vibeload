"""Genera la identidad Play-Drop: maestros SVG, cortes chicos, kit PNG, .ico y splash.

Uso (desde la raíz del repo):  .venv\\Scripts\\python brand\\build_playdrop.py

El símbolo es un triángulo hacia abajo (play girado = video, flecha = descarga,
V = Vibe) cortado en tres columnas (barras de ecualizador = audio).
Los tamaños chicos (16-48 px) no son reducciones del maestro: cada uno tiene su
geometría alineada a la grilla de píxeles.
Solo usa PySide6 (QtSvg para rasterizar, QPainterPath para el wordmark).
"""
import os
import struct
import sys

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QFont, QGuiApplication, QImage, QPainter, QPainterPath
from PySide6.QtSvg import QSvgRenderer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRAND = os.path.join(ROOT, "brand")
MASTER = os.path.join(BRAND, "master")
KIT = os.path.join(BRAND, "kit")
ASSETS = os.path.join(ROOT, "assets")

VIOLET = "#6D3DF2"
LAVENDER = "#B69CFF"
INK = "#0F0D16"
WHITE = "#FFFFFF"
BLACK = "#000000"


# La geometría vive en la app para que la cabecera dibuje el mismo símbolo.
sys.path.insert(0, ROOT)
from vibeloader.ui.brand import MASTER_GEOM, SMALL_CUTS, svg_path_d  # noqa: E402


def symbol_paths(**geom):
    return [svg_path_d(geom)]


# ------------------------------------------------------------------
# SVG
# ------------------------------------------------------------------
def svg_doc(w, h, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">\n'
        f"  <title>{title}</title>\n{body}</svg>\n"
    )


def sym_group(paths, fill, transform=""):
    t = f' transform="{transform}"' if transform else ""
    inner = "".join(f'    <path d="{p}"/>\n' for p in paths)
    return f'  <g fill="{fill}"{t}>\n{inner}  </g>\n'


def plate(size, fill, radius_ratio=0.225):
    r = round(size * radius_ratio, 2)
    return f'  <rect width="{size}" height="{size}" rx="{r}" fill="{fill}"/>\n'


def symbol_svg(fill, title="VibeLoader Play-Drop"):
    return svg_doc(256, 256, sym_group(symbol_paths(**MASTER_GEOM), fill), title)


def app_icon_svg(size=256, geom=None, plate_fill=VIOLET, fill=WHITE):
    paths = symbol_paths(**(geom or MASTER_GEOM))
    return svg_doc(size, size, plate(size, plate_fill) + sym_group(paths, fill), "VibeLoader")


def tray_svg(size, geom, fill=WHITE):
    return svg_doc(size, size, sym_group(symbol_paths(**geom), fill), "VibeLoader")


# ------------------------------------------------------------------
# Wordmark: "vibeloader" en minúsculas, Segoe UI Bold, a contornos
# ------------------------------------------------------------------
def wordmark_path(px_size=100):
    font = QFont("Segoe UI", 10)
    font.setPixelSize(px_size)
    font.setWeight(QFont.Weight.Bold)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
    qp = QPainterPath()
    qp.addText(0, 0, font, "vibeloader")
    br = qp.boundingRect()
    qp.translate(-br.left(), -br.top())
    parts = []
    i = 0
    n = qp.elementCount()
    while i < n:
        e = qp.elementAt(i)
        if e.type == QPainterPath.ElementType.MoveToElement:
            parts.append(f"M{e.x:.1f} {e.y:.1f}")
            i += 1
        elif e.type == QPainterPath.ElementType.LineToElement:
            parts.append(f"L{e.x:.1f} {e.y:.1f}")
            i += 1
        else:  # CurveTo + 2 CurveToData
            c1, c2 = qp.elementAt(i + 1), qp.elementAt(i + 2)
            parts.append(f"C{e.x:.1f} {e.y:.1f} {c1.x:.1f} {c1.y:.1f} {c2.x:.1f} {c2.y:.1f}")
            i += 3
    return " ".join(parts) + " Z", br.width(), br.height()


def horizontal_svg(sym_fill, text_fill, title):
    wm, ww, wh = wordmark_path(100)
    # Símbolo 256 -> 160 de alto visible; wordmark centrado en la altura.
    h = 200
    sym_scale = 0.78
    sym_x, sym_y = 0, (h - 256 * sym_scale) / 2 + 6
    text_x = 256 * sym_scale - 10
    text_y = (h - wh) / 2
    w = int(text_x + ww + 16)
    body = sym_group(symbol_paths(**MASTER_GEOM), sym_fill, f"translate({sym_x:.1f} {sym_y:.1f}) scale({sym_scale})")
    body += f'  <path fill="{text_fill}" transform="translate({text_x:.1f} {text_y:.1f})" d="{wm}"/>\n'
    return svg_doc(w, h, body, title)


def splash_svg(w=480, h=270):
    wm, ww, wh = wordmark_path(30)
    sym = 132
    s = sym / 256
    sx, sy = (w - sym) / 2, 40
    body = f'  <rect width="{w}" height="{h}" fill="{INK}"/>\n'
    body += sym_group(symbol_paths(**MASTER_GEOM), LAVENDER, f"translate({sx:.1f} {sy:.1f}) scale({s:.4f})")
    body += f'  <path fill="#F2EFF8" transform="translate({(w - ww) / 2:.1f} {sy + sym + 6:.1f})" d="{wm}"/>\n'
    return svg_doc(w, h, body, "VibeLoader splash")


# ------------------------------------------------------------------
# Raster
# ------------------------------------------------------------------
def render(svg_text, w, h=None) -> QImage:
    h = h or w
    r = QSvgRenderer(QByteArray(svg_text.encode("utf-8")))
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, w, h))
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def write_ico(path, images: dict):
    """ICO con entradas PNG (válido desde Windows Vista)."""
    sizes = sorted(images)
    blobs = [png_bytes(images[s]) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(header + entries + b"".join(blobs))


def icon_image(size: int) -> QImage:
    """Ícono de app (placa violeta) con el corte que corresponde al tamaño."""
    if size in SMALL_CUTS:
        return render(app_icon_svg(size, SMALL_CUTS[size]), size)
    return render(app_icon_svg(256), size)


def save(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def main():
    if QGuiApplication.instance() is None:
        main.app = QGuiApplication(sys.argv)  # hace falta para las fuentes del wordmark
    os.makedirs(MASTER, exist_ok=True)
    os.makedirs(KIT, exist_ok=True)

    # Maestros
    save(os.path.join(MASTER, "vibeload-symbol.svg"), symbol_svg(BLACK))
    save(os.path.join(MASTER, "vibeload-symbol-color.svg"), symbol_svg(VIOLET))
    save(os.path.join(MASTER, "vibeload-symbol-dark.svg"), symbol_svg(LAVENDER))
    save(os.path.join(MASTER, "vibeload-app-icon.svg"), app_icon_svg(256))
    for s, g in SMALL_CUTS.items():
        save(os.path.join(MASTER, f"vibeload-app-icon-{s}.svg"), app_icon_svg(s, g))
        save(os.path.join(MASTER, f"vibeload-tray-{s}.svg"), tray_svg(s, g))
    save(os.path.join(MASTER, "vibeload-horizontal.svg"), horizontal_svg(VIOLET, "#16131D", "VibeLoader (claro)"))
    save(os.path.join(MASTER, "vibeload-horizontal-dark.svg"), horizontal_svg(LAVENDER, "#F2EFF8", "VibeLoader (oscuro)"))
    save(os.path.join(MASTER, "vibeload-horizontal-black.svg"), horizontal_svg(BLACK, BLACK, "VibeLoader (negro)"))
    save(os.path.join(MASTER, "vibeload-horizontal-white.svg"), horizontal_svg(WHITE, WHITE, "VibeLoader (blanco)"))
    save(os.path.join(MASTER, "vibeload-splash.svg"), splash_svg())

    # Kit PNG
    for s in (16, 20, 24, 32, 48, 64, 128, 256, 512, 1024):
        icon_image(s).save(os.path.join(KIT, f"vibeload-app-icon-{s}.png"))
    for s in (64, 256, 1024):
        render(symbol_svg(VIOLET), s).save(os.path.join(KIT, f"vibeload-symbol-color-{s}.png"))
        render(symbol_svg(WHITE), s).save(os.path.join(KIT, f"vibeload-symbol-white-{s}.png"))
        render(symbol_svg(BLACK), s).save(os.path.join(KIT, f"vibeload-symbol-black-{s}.png"))
    for name in ("horizontal", "horizontal-dark"):
        svg = open(os.path.join(MASTER, f"vibeload-{name}.svg"), encoding="utf-8").read()
        r = QSvgRenderer(QByteArray(svg.encode()))
        vb = r.viewBoxF()
        w = 1200
        render(svg, w, int(w * vb.height() / vb.width())).save(os.path.join(KIT, f"vibeload-{name}-1200.png"))

    ico_sizes = (16, 20, 24, 32, 48, 64, 128, 256)
    ico_imgs = {s: icon_image(s) for s in ico_sizes}
    write_ico(os.path.join(KIT, "vibeload_windows.ico"), ico_imgs)

    # Assets de la app
    write_ico(os.path.join(ASSETS, "icono.ico"), ico_imgs)
    write_ico(os.path.join(ASSETS, "source", "vibeload_256.ico"), ico_imgs)
    icon_image(1024).save(os.path.join(ASSETS, "source", "icono_1024.png"))
    render(splash_svg(), 480, 270).save(os.path.join(ASSETS, "splash.png"))
    render(splash_svg(), 2048, 1152).save(os.path.join(ASSETS, "source", "splash_screen_2048.png"))
    print("Play-Drop generado: brand/master, brand/kit, assets/icono.ico, assets/splash.png")


if __name__ == "__main__":
    main()
