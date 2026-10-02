"""Quita del build de PyInstaller las partes de Qt que VibeLoader no usa.

La app usa solo Qt Widgets. El hook de PySide6 arrastra Qt Quick/QML (por el
teclado virtual), Qt PDF (por el plugin de imágenes PDF), el OpenGL por
software y las traducciones de Qt, que no se cargan.

Uso: python scripts\\slim_dist.py [dist\\VibeLoader]
"""
import os
import shutil
import sys

QT_FILES = (
    "opengl32sw.dll",
    "Qt6Pdf.dll",
    "Qt6Qml.dll",
    "Qt6QmlMeta.dll",
    "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll",
    "Qt6Quick.dll",
    "Qt6VirtualKeyboard.dll",
    "Qt6OpenGL.dll",
    "translations",
    os.path.join("plugins", "platforminputcontexts"),
    os.path.join("plugins", "generic"),
    os.path.join("plugins", "platforms", "qdirect2d.dll"),
    os.path.join("plugins", "platforms", "qminimal.dll"),
    os.path.join("plugins", "platforms", "qoffscreen.dll"),
    os.path.join("plugins", "imageformats", "qpdf.dll"),
    os.path.join("plugins", "imageformats", "qicns.dll"),
    os.path.join("plugins", "imageformats", "qtga.dll"),
    os.path.join("plugins", "imageformats", "qtiff.dll"),
    os.path.join("plugins", "imageformats", "qwbmp.dll"),
)


def _size(path: str) -> int:
    if os.path.isfile(path):
        return os.path.getsize(path)
    return sum(os.path.getsize(os.path.join(r, f)) for r, _d, fs in os.walk(path) for f in fs)


def slim(dist_dir: str) -> int:
    qt_dir = os.path.join(dist_dir, "_internal", "PySide6")
    if not os.path.isdir(qt_dir):
        raise SystemExit(f"No encontré {qt_dir}")
    freed = 0
    for rel in QT_FILES:
        path = os.path.join(qt_dir, rel)
        if not os.path.exists(path):
            continue
        freed += _size(path)
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    return freed


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join("dist", "VibeLoader")
    before = _size(target)
    freed = slim(target)
    print(f"Build adelgazado: {before / 2**20:.0f} MB -> {(before - freed) / 2**20:.0f} MB (-{freed / 2**20:.0f} MB)")
