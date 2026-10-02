"""Punto de entrada: QApplication, splash y ventana principal."""
import sys

# Antes que nada: si hay un yt-dlp más nuevo descargado, que gane sobre el
# embebido en el .exe (tiene que pasar antes de cualquier `import yt_dlp`).
from .updater import activate_overlay

_OVERLAY_VERSION = activate_overlay()

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QSplashScreen  # noqa: E402

from .config import SETTINGS_APP, SETTINGS_ORG, is_frozen, resource_path  # noqa: E402
from .logs import append_log_file  # noqa: E402
from .ui.main_window import MainWindow  # noqa: E402

SPLASH_PATH = "assets/splash.png"


def _close_pyinstaller_splash():
    """En el .exe, PyInstaller muestra el splash mientras arranca (--splash)."""
    try:
        import pyi_splash  # solo existe dentro del .exe

        pyi_splash.close()
    except Exception:
        pass


def _qt_splash(app):
    """En modo desarrollo no hay splash de PyInstaller: se usa uno de Qt."""
    pix = QPixmap(resource_path(SPLASH_PATH))
    if pix.isNull():
        return None
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        geo = screen.availableGeometry()
        side = max(120, int(min(geo.width(), geo.height()) * 0.35))
        pix = pix.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
    splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
    if screen is not None:
        fg = splash.frameGeometry()
        fg.moveCenter(screen.availableGeometry().center())
        splash.move(fg.topLeft())
    splash.show()
    app.processEvents()
    return splash


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)

    splash = None if is_frozen() else _qt_splash(app)
    if _OVERLAY_VERSION:
        append_log_file(f"yt-dlp actualizado en uso: {_OVERLAY_VERSION}")

    window = MainWindow()
    window.show()
    if splash is not None:
        splash.finish(window)
    _close_pyinstaller_splash()

    sys.exit(app.exec())
