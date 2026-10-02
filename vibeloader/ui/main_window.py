"""Ventana principal: une vistas, worker, metadatos y bandeja."""
import logging
import os
import sys
import time

from PySide6.QtCore import QProcess, QSettings, QThread, QTimer, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QStackedWidget,
    QSystemTrayIcon,
)

from ..config import APP_VERSION, DEFAULT_TARGET_SIZE_MB, SETTINGS_APP, SETTINGS_ORG, is_frozen, resource_path
from .. import updater
from ..jobs import BackgroundTask, MetadataFetcher, Worker
from ..logs import append_log_file, ensure_log_path
from ..settings import (
    load_default_dirs_from_settings,
    load_recent_urls,
    save_default_dirs_to_settings,
    save_recent_urls,
    suggested_default_dirs,
)
from ..ffmpeg_core import ffmpeg_version
from ..tools import ffmpeg_available, ffmpeg_path, ffprobe_path, local_ffmpeg_dir
from ..ytdlp_core import ytdlp_version
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
        self.setWindowTitle(f"VibeLoader {APP_VERSION} ✨")
        self.setMinimumSize(820, 620)
        self.setWindowIcon(QIcon(resource_path("assets/icono.ico")))

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
        self._bg_tasks = set()  # mantiene vivas las BackgroundTask en curso

        self._meta_thread = QThread(self)
        self._meta = MetadataFetcher()
        self._meta.moveToThread(self._meta_thread)
        self.request_metadata.connect(self._meta.fetch)
        self._meta_thread.start()

        # Tray for notifications
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            icon_path = resource_path("assets/icono.ico")
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
        self.advanced_view.request_update_ytdlp.connect(lambda: self._update_ytdlp(manual=True))
        self.advanced_view.request_install_ffmpeg.connect(self._offer_ffmpeg_download)
        self.advanced_view.auto_update_chk.setChecked(
            self.settings.value("auto_update_ytdlp", True, type=bool)
        )
        self.advanced_view.auto_update_toggled.connect(
            lambda on: self.settings.setValue("auto_update_ytdlp", bool(on))
        )

        self._meta.fetched.connect(self.simple_view.on_metadata)
        self._meta.failed.connect(self.simple_view.on_metadata_failed)
        self._meta.log.connect(append_log_file)

        # Theme & arranque
        self._apply_theme()

        # Start log
        self._log_to_advanced(
            f"🚀 VibeLoader {APP_VERSION} · yt-dlp {ytdlp_version()} · "
            f"{'exe' if is_frozen() else 'Python ' + sys.version.split()[0]}"
        )
        for name, path in (("ffmpeg", ffmpeg_path()), ("ffprobe", ffprobe_path())):
            self._log_to_advanced(f"{'✅' if path else '❌'} {name}: {path or 'NO encontrado'}")
        if ffmpeg_path():
            self._log_to_advanced(f"   {ffmpeg_version()}")
        if not ffmpeg_available():
            self._log_to_advanced(
                "⚠️ Sin ffmpeg y ffprobe no funciona ningún modo (unir video+audio, convertir, MP3)."
            )
            self._show_ffmpeg_notice()

        # yt-dlp al día (como máximo una vez por día, en segundo plano)
        if self.settings.value("auto_update_ytdlp", True, type=bool) and updater.should_check_now(
            self.settings.value("ytdlp_last_check", 0.0, type=float)
        ):
            QTimer.singleShot(3000, lambda: self._update_ytdlp(manual=False))

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

    # ---------- Tareas de fondo ----------
    def _run_task(self, fn, name, on_done, on_failed, on_progress=None):
        task = BackgroundTask(fn, name)
        self._bg_tasks.add(task)
        task.log.connect(self._log_to_advanced)
        if on_progress:
            task.progress.connect(on_progress)

        def _done(result):
            self._bg_tasks.discard(task)
            on_done(result)

        def _failed(msg):
            self._bg_tasks.discard(task)
            on_failed(msg)

        task.done.connect(_done)
        task.failed.connect(_failed)
        task.start()
        return task

    # ---------- ffmpeg ----------
    def _show_ffmpeg_notice(self):
        self.simple_view.show_notice(
            "Falta ffmpeg, que VibeLoader necesita para unir y convertir videos.",
            "Descargar ffmpeg",
            self._offer_ffmpeg_download,
        )

    def _on_ffmpeg_missing(self):
        self._show_ffmpeg_notice()
        self._offer_ffmpeg_download()

    def _offer_ffmpeg_download(self):
        if self._job_running:
            QMessageBox.information(self, "ffmpeg", "Espera a que termine la descarga en curso.")
            return
        r = QMessageBox.question(
            self,
            "Descargar ffmpeg",
            "VibeLoader descargará ffmpeg (unos 185 MB) desde GitHub (builds de BtbN), "
            "verificará el archivo y lo guardará en su propia carpeta:\n\n"
            f"{local_ffmpeg_dir()}\n\nNo se modifica nada del sistema. ¿Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if r != QMessageBox.StandardButton.Yes:
            return
        dlg = QProgressDialog("Descargando ffmpeg…", "Cancelar", 0, 100, self)
        dlg.setWindowTitle("ffmpeg")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)

        def work(task):
            task.log.emit("⬇️ Descargando ffmpeg…")
            return updater.install_ffmpeg(
                local_ffmpeg_dir(),
                progress=lambda d, t: task.progress.emit(d, t),
                is_cancelled=task.cancel_event.is_set,
            )

        def on_progress(done, total):
            if total:
                dlg.setValue(int(done * 100 / total))
                dlg.setLabelText(f"Descargando ffmpeg… {done >> 20} de {total >> 20} MB")

        def on_done(name):
            dlg.close()
            self.advanced_view.ffmpeg_btn.setEnabled(True)
            self._log_to_advanced(f"✅ ffmpeg instalado ({name}) en {local_ffmpeg_dir()}")
            self._log_to_advanced(f"   {ffmpeg_version()}")
            self.simple_view.show_notice("ffmpeg quedó instalado. Ya puedes descargar.")
            QTimer.singleShot(6000, self.simple_view.hide_notice)

        def on_failed(msg):
            dlg.close()
            self.advanced_view.ffmpeg_btn.setEnabled(True)
            self._log_to_advanced("❌ " + msg)
            if not task.cancel_event.is_set():
                QMessageBox.warning(self, "ffmpeg", f"No se pudo descargar ffmpeg:\n{msg}")

        self.advanced_view.ffmpeg_btn.setEnabled(False)
        task = self._run_task(work, "descarga de ffmpeg", on_done, on_failed, on_progress)
        dlg.canceled.connect(task.cancel_event.set)
        dlg.show()

    # ---------- yt-dlp ----------
    def _update_ytdlp(self, manual: bool):
        self.advanced_view.update_btn.setEnabled(False)
        if manual:
            self._log_to_advanced("🔄 Buscando actualización de yt-dlp…")

        def work(task):
            log = task.log.emit if manual else append_log_file
            if is_frozen():
                return updater.install_latest_ytdlp(ytdlp_version(), logger=log)
            updater.pip_update_ytdlp(logger=log)
            return "pip"

        def on_done(result):
            self.advanced_view.update_btn.setEnabled(True)
            self.settings.setValue("ytdlp_last_check", time.time())
            if result and result != "pip":
                self._log_to_advanced(f"✅ yt-dlp {result} listo. Se usará al reiniciar VibeLoader.")
                self.simple_view.show_notice(
                    f"Hay una versión nueva de yt-dlp ({result}) lista.",
                    "Reiniciar",
                    self._restart_app,
                )

        def on_failed(msg):
            self.advanced_view.update_btn.setEnabled(True)
            self._log_to_advanced("⚠️ No se pudo actualizar yt-dlp: " + msg)

        self._run_task(work, "actualización de yt-dlp", on_done, on_failed)

    def _restart_app(self):
        if self._job_running:
            QMessageBox.information(self, "Reiniciar", "Espera a que termine la descarga en curso.")
            return
        args = sys.argv[1:] if is_frozen() else sys.argv
        if QProcess.startDetached(sys.executable, args)[0]:
            self.close()

    # ---------- Metadatos ----------
    def _forward_metadata_request(self, url: str, token: int):
        self._meta.latest_token = token
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
        if not ffmpeg_available():
            source_view.show_error(
                "No se encontró ffmpeg, que hace falta para todos los modos. "
                "Usa el botón «Descargar ffmpeg» o instálalo y agrégalo al PATH."
            )
            self._on_ffmpeg_missing()
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
        if self._job_running:
            r = QMessageBox.question(
                self,
                "Descarga en curso",
                "Hay una descarga en curso. ¿Cancelarla y salir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self._job_cancelled = True
            if self.worker is not None:
                self.worker.request_cancel()
        stopped = self._stop_thread(self.thread, 15000) if self._job_running else True
        stopped = self._stop_thread(self._meta_thread, 3000) and stopped
        if not stopped:
            # Un hilo sigue bloqueado en la red. Destruir un QThread en marcha
            # aborta la app con un error, y terminate() puede corromper memoria:
            # se guarda todo y se sale del proceso directamente.
            append_log_file("⚠️ Cierre forzado: un hilo no terminó a tiempo.")
            self.settings.sync()
            logging.shutdown()
            os._exit(0)
        super().closeEvent(e)

    @staticmethod
    def _stop_thread(thread, timeout_ms: int) -> bool:
        """Pide al hilo que termine y espera. True si terminó.

        quit() se llama directo: la conexión worker.finished → thread.quit es
        encolada hacia este hilo (la GUI), que aquí está bloqueado en wait().
        """
        if thread is None:
            return True
        try:
            if not thread.isRunning():
                return True
            thread.quit()
            return thread.wait(timeout_ms)
        except RuntimeError:
            return True  # el objeto C++ ya se borró (deleteLater): el hilo terminó
