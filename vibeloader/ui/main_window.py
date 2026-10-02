"""Ventana principal: une vistas, worker, metadatos y bandeja."""
import os

from PySide6.QtCore import QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
)

from ..config import DEFAULT_TARGET_SIZE_MB, SETTINGS_APP, SETTINGS_ORG, resource_path
from ..jobs import MetadataFetcher, Worker
from ..logs import append_log_file, ensure_log_path
from ..settings import (
    load_default_dirs_from_settings,
    load_recent_urls,
    save_default_dirs_to_settings,
    save_recent_urls,
    suggested_default_dirs,
)
from ..utils import check_tool
from ..ytdlp_core import maybe_update_ytdlp_in_background
from .advanced_view import AdvancedView
from .dialogs import DefaultFoldersConfigDialog
from .simple_view import SimpleView
from .styles import THEMES, build_stylesheet


class MainWindow(QMainWindow):
    request_metadata = Signal(str, int)

    def __init__(self):
        super().__init__()
        ensure_log_path()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.setWindowTitle("VibeLoader ✨")
        self.setMinimumSize(820, 620)
        self.setWindowIcon(QIcon(resource_path("icono.ico")))

        loaded = load_default_dirs_from_settings(self.settings)
        self._pending_first_run = loaded is None
        self.default_dirs = loaded if loaded is not None else suggested_default_dirs()
        self.theme = str(self.settings.value("theme", "dark"))
        if self.theme not in THEMES:
            self.theme = "dark"
        self.recent_urls = load_recent_urls(self.settings)

        # Worker / metadata
        self.worker = None
        self.thread = None
        self._job_running = False
        self._job_cancelled = False
        self._job_failed = False
        self._active_view_for_job = None
        self._last_completed_path = None

        self._meta_thread = QThread(self)
        self._meta = MetadataFetcher()
        self._meta.moveToThread(self._meta_thread)
        self.request_metadata.connect(self._meta.fetch)
        self._meta_thread.start()

        # Tray for notifications
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            icon_path = resource_path("icono.ico")
            if os.path.exists(icon_path):
                self.tray.setIcon(QIcon(icon_path))
            else:
                self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
            self.tray.setToolTip("VibeLoader")

        # Views
        self.simple_view = SimpleView(self)
        self.advanced_view = AdvancedView(self)
        self.advanced_view.set_default_dirs(self.default_dirs)
        self.advanced_view.set_encoder_mode(str(self.settings.value("encoder_mode", "auto")))
        self.advanced_view.encoder_combo.currentIndexChanged.connect(
            lambda _i: self.settings.setValue("encoder_mode", self.advanced_view.encoder_mode())
        )
        self.simple_view.update_folder_hint(self.default_dirs)
        self.simple_view.set_recents(self.recent_urls)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.simple_view)
        self.stack.addWidget(self.advanced_view)
        self.setCentralWidget(self.stack)

        # Wire signals
        self.simple_view.request_open_advanced.connect(self._show_advanced)
        self.simple_view.request_open_folders.connect(self._open_folders_dialog)
        self.simple_view.request_toggle_theme.connect(self._toggle_theme)
        self.simple_view.request_start.connect(self._start_from_simple)
        self.simple_view.request_cancel.connect(self._cancel_job)
        self.simple_view.request_fetch_metadata.connect(self._forward_metadata_request)

        self.advanced_view.request_open_simple.connect(self._show_simple)
        self.advanced_view.request_open_folders.connect(self._open_folders_dialog)
        self.advanced_view.request_toggle_theme.connect(self._toggle_theme)
        self.advanced_view.request_start.connect(self._start_from_advanced)
        self.advanced_view.request_cancel.connect(self._cancel_job)

        self._meta.fetched.connect(self.simple_view.on_metadata)
        self._meta.failed.connect(self.simple_view.on_metadata_failed)
        self._meta.log.connect(append_log_file)

        # Theme & arranque
        self._apply_theme()

        # Start log
        self._log_to_advanced("🔎 Verificando herramientas…")
        for t in ("ffmpeg", "ffprobe"):
            ok = check_tool(t)
            self._log_to_advanced(
                f"{'✅' if ok else '❌'} {t}: {'OK' if ok else 'NO encontrado en PATH'}"
            )
        if not check_tool("ffmpeg") or not check_tool("ffprobe"):
            self._log_to_advanced(
                "⚠️ Necesitas ffmpeg y ffprobe en el PATH. Sin ellos no funcionan los modos WhatsApp, Auto ni MP3 con portada."
            )

        # Auto-update opcional
        if self.settings.value("auto_update_ytdlp", False, type=bool):
            self._log_to_advanced("🔄 Buscando actualización de yt-dlp…")
            maybe_update_ytdlp_in_background(self._log_to_advanced)

        # Decide vista inicial
        last_view = str(self.settings.value("last_view", "simple"))
        if self._pending_first_run or last_view != "advanced":
            self._show_simple()
        else:
            self._show_advanced()

        if self._pending_first_run:
            QTimer.singleShot(0, self._first_run_setup)
        else:
            QApplication.instance().applicationStateChanged.connect(
                self._on_app_state_changed
            )

        QTimer.singleShot(300, self.simple_view.maybe_autopaste_clipboard)

    # ---------- Tema ----------
    def _apply_theme(self):
        QApplication.instance().setStyleSheet(build_stylesheet(self.theme))

    def _toggle_theme(self):
        self.theme = "light" if self.theme == "dark" else "dark"
        self.settings.setValue("theme", self.theme)
        self._apply_theme()

    # ---------- Navegación ----------
    def _show_simple(self):
        self.stack.setCurrentWidget(self.simple_view)
        self.settings.setValue("last_view", "simple")

    def _show_advanced(self):
        self.stack.setCurrentWidget(self.advanced_view)
        self.settings.setValue("last_view", "advanced")

    # ---------- App focus ----------
    def _on_app_state_changed(self, state):
        if state == Qt.ApplicationState.ApplicationActive:
            QTimer.singleShot(150, self.simple_view.maybe_autopaste_clipboard)

    # ---------- Carpetas ----------
    def _first_run_setup(self):
        dlg = DefaultFoldersConfigDialog(self, dict(self.default_dirs), first_run=True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.default_dirs = dlg.get_paths()
        save_default_dirs_to_settings(self.settings, self.default_dirs)
        self._refresh_dirs_in_views()
        QApplication.instance().applicationStateChanged.connect(
            self._on_app_state_changed
        )

    def _open_folders_dialog(self):
        dlg = DefaultFoldersConfigDialog(self, dict(self.default_dirs), first_run=False)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.default_dirs = dlg.get_paths()
        save_default_dirs_to_settings(self.settings, self.default_dirs)
        self._refresh_dirs_in_views()

    def _refresh_dirs_in_views(self):
        self.simple_view.update_folder_hint(self.default_dirs)
        self.advanced_view.set_default_dirs(self.default_dirs)

    # ---------- Metadatos ----------
    def _forward_metadata_request(self, url: str, token: int):
        self.request_metadata.emit(url, token)

    # ---------- Job ----------
    def _start_from_simple(self, url: str, preset: str):
        folder = self.default_dirs.get(preset, "")
        if not folder:
            folder = suggested_default_dirs().get(preset, os.path.expanduser("~"))
        self._launch_job(url, preset, folder, "", "", source_view=self.simple_view)

    def _start_from_advanced(
        self, url: str, preset: str, folder: str, start_t: str, end_t: str
    ):
        self._launch_job(url, preset, folder, start_t, end_t, source_view=self.advanced_view)

    def _launch_job(self, url, preset, folder, start_t, end_t, source_view):
        if self._job_running:
            self._log_to_advanced("⚠️ Ya hay una descarga en curso.")
            return
        self._job_running = True
        self._job_cancelled = False
        self._job_failed = False
        self._active_view_for_job = source_view
        self._remember_url(url)

        source_view.set_busy(True)
        if source_view is self.simple_view:
            self.advanced_view.set_busy(True)
        else:
            self.simple_view.set_busy(True)

        self.thread = QThread()
        self.worker = Worker(
            url,
            folder,
            preset,
            start_t,
            end_t,
            encoder_mode=self.advanced_view.encoder_mode(),
            target_mb=self.advanced_view.target_size_mb() or DEFAULT_TARGET_SIZE_MB,
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._on_worker_log)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.completed.connect(self._on_worker_completed)
        self.worker.error.connect(self._on_worker_error)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _cancel_job(self):
        if self.worker is not None and self._job_running:
            self._job_cancelled = True
            self.worker.request_cancel()
            self._log_to_advanced("⏹️ Cancelación solicitada…")

    def _on_worker_log(self, msg: str):
        self.advanced_view.append_log(msg)
        append_log_file(msg)

    def _on_worker_progress(self, pct: int, msg: str):
        self.advanced_view.set_progress(pct, msg)
        self.simple_view.set_progress(pct, msg)

    def _on_worker_completed(self, file_path: str):
        self._last_completed_path = file_path

    def _on_worker_error(self, msg: str):
        self._job_failed = True
        self.advanced_view.show_error(msg)
        self.simple_view.show_error(msg)
        if self.tray and not self.isActiveWindow():
            self.tray.show()
            self.tray.showMessage(
                "VibeLoader", "Hubo un problema con la descarga.", QSystemTrayIcon.MessageIcon.Warning, 5000
            )

    def _on_worker_finished(self):
        path = getattr(self, "_last_completed_path", None)
        self._job_running = False
        self.advanced_view.set_busy(False)
        self.simple_view.set_busy(False)
        if self._job_cancelled:
            self.advanced_view.show_cancelled()
            self.simple_view.show_cancelled()
        elif self._job_failed:
            pass
        else:
            self.advanced_view.show_success(path or "")
            self.simple_view.show_success(path or "")
            if self.tray and not self.isActiveWindow():
                self.tray.show()
                self.tray.showMessage(
                    "VibeLoader",
                    "Descarga lista.",
                    QSystemTrayIcon.MessageIcon.Information,
                    4000,
                )
        self._last_completed_path = None

    # ---------- Recientes ----------
    def _remember_url(self, url: str):
        if not url:
            return
        urls = [u for u in self.recent_urls if u != url]
        urls.insert(0, url)
        self.recent_urls = urls[:5]
        save_recent_urls(self.settings, self.recent_urls)
        self.simple_view.set_recents(self.recent_urls)

    # ---------- Logging ----------
    def _log_to_advanced(self, msg: str):
        self.advanced_view.append_log(msg)
        append_log_file(msg)

    # ---------- Cierre ----------
    def closeEvent(self, e):
        try:
            if self.worker is not None and self._job_running:
                self.worker.request_cancel()
            self._meta_thread.quit()
            self._meta_thread.wait(1500)
        except Exception:
            pass
        super().closeEvent(e)
