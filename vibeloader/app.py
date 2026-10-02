"""Punto de entrada: QApplication, splash y ventana principal."""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from .config import SETTINGS_APP, SETTINGS_ORG, resource_path
from .logs import ensure_log_path
from .ui.main_window import MainWindow


def main():
    ensure_log_path()
    app = QApplication(sys.argv)
    app.setApplicationName(SETTINGS_APP)
    app.setOrganizationName(SETTINGS_ORG)

    splash = None
    splash_path = resource_path("splash_screen.png")
    if os.path.isfile(splash_path):
        pix = QPixmap(splash_path)
        if not pix.isNull():
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                max_w = max(120, int(geo.width() * 0.25))
                max_h = max(120, int(geo.height() * 0.25))
                pix = pix.scaled(
                    max_w,
                    max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
            if screen is not None:
                fg = splash.frameGeometry()
                fg.moveCenter(geo.center())
                splash.move(fg.topLeft())
            splash.show()
            app.processEvents()

    window = MainWindow()
    window.show()
    if splash is not None:
        splash.finish(window)

    sys.exit(app.exec())
