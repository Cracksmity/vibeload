"""Ventana principal: une vistas, cola de trabajos, metadatos, tareas de fondo y bandeja."""
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

from .. import updater
from ..config import ADVANCED_PRESETS, APP_VERSION, SETTINGS_APP, SETTINGS_ORG, is_frozen, resource_path
from ..errors import friendly
from ..ffmpeg_core import ffmpeg_version
from ..history import add_history
from ..jobs import BackgroundTask, Job, MetadataFetcher, Worker
from ..logs import append_log_file, ensure_log_path
from ..settings import (
    load_default_dirs_from_settings,
    load_recent_urls,
    save_default_dirs_to_settings,
    save_recent_urls,
    suggested_default_dirs,
)
from ..tools import ffmpeg_available, ffmpeg_path, ffprobe_path, local_ffmpeg_dir
from ..utils import windows_safe_video_name
from ..ytdlp_core import fetch_metadata, ytdlp_version
from .advanced_view import AdvancedView
from .dialogs import DefaultFoldersConfigDialog
from .history_dialog import HistoryDialog
from .playlist_dialog import PlaylistDialog
from .simple_view import SimpleView
from .styles import THEMES, build_stylesheet


class MainWindow(QMainWindow):
    request_metadata = Signal(str, int)

    def __init__(self):
        super().__init__()
        ensure_log_path()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.setWindowTitle(f"VibeLoader {APP_VERSION} ✨")
        self.setMinimumSize(860, 680)
        self.setWindowIcon(QIcon(resource_path("assets/icono.ico")))

        loaded = load_default_dirs_from_settings(self.settings)
        self._pending_first_run = loaded is None
        self.default_dirs = loaded if loaded is not None else suggested_default_dirs()
        self.theme = str(self.settings.value("theme", "dark"))
        if self.theme not in THEMES:
            self.theme = "dark"
        self.recent_urls = load_recent_urls(self.settings)

        # Cola de trabajos
        self.worker = None
        self.thread = None
        self._job_running = False  # hay un Worker activo
        self._queue: list[Job] = []
        self._current_job: Job | None = None
        self._cancel_requested = False
        self._batch = None  # resumen de la tanda en curso (varios trabajos seguidos)
        self._pending_playlists: list[Job] = []
        self._bg_tasks = set()  # mantiene vivas las BackgroundTask en curso
        # Hilo + worker del trabajo anterior hasta que su hilo termine de cerrarse:
        # si Python suelta la última referencia antes, PySide destruye un QThread
        # en marcha y Qt aborta la app.
        self._retiring = set()

        self._meta_thread = QThread(self)
        self._meta = MetadataFetcher()
        self._meta.moveToThread(self._meta_thread)
        self.request_metadata.connect(self._meta.fetch)
        self._meta_thread.start()

        # Bandeja para notificaciones
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            icon_path = resource_path("assets/icono.ico")
            if os.path.exists(icon_path):
                self.tray.setIcon(QIcon(icon_path))
            else:
                self.tray.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
            self.tray.setToolTip("VibeLoader")

        # Vistas
        self.simple_view = SimpleView(self)
        self.advanced_view = AdvancedView(self)
        self.advanced_view.set_default_dirs(self.default_dirs)
        self.advanced_view.load_options(self.settings)
        self.advanced_view.options_changed.connect(self._on_options_changed)
        self._on_options_changed()
        self.simple_view.update_folder_hint(self.default_dirs)
        self.simple_view.set_recents(self.recent_urls)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.simple_view)
        self.stack.addWidget(self.advanced_view)
        self.setCentralWidget(self.stack)

        # Señales
        sv, av = self.simple_view, self.advanced_view
        sv.request_open_advanced.connect(self._show_advanced)
        sv.request_open_folders.connect(self._open_folders_dialog)
        sv.request_open_history.connect(self._open_history)
        sv.request_toggle_theme.connect(self._toggle_theme)
        sv.request_start.connect(self._start_from_simple)
        sv.request_cancel.connect(self._cancel_job)
        sv.request_fetch_metadata.connect(self._forward_metadata_request)

        av.request_open_simple.connect(self._show_simple)
        av.request_open_folders.connect(self._open_folders_dialog)
        av.request_open_history.connect(self._open_history)
        av.request_toggle_theme.connect(self._toggle_theme)
        av.request_start.connect(self._start_from_advanced)
        av.request_cancel.connect(self._cancel_job)
        av.request_remove_queued.connect(self._remove_queued)
        av.request_clear_queue.connect(self._clear_queue)
        av.request_update_ytdlp.connect(lambda: self._update_ytdlp(manual=True))
        av.request_install_ffmpeg.connect(self._offer_ffmpeg_download)
        av.auto_update_chk.setChecked(self.settings.value("auto_update_ytdlp", True, type=bool))
        av.auto_update_toggled.connect(lambda on: self.settings.setValue("auto_update_ytdlp", bool(on)))

        self._meta.fetched.connect(self.simple_view.on_metadata)
        self._meta.failed.connect(self.simple_view.on_metadata_failed)
        self._meta.log.connect(append_log_file)

        self._apply_theme()

        # Log de arranque
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

        # Vista inicial
        last_view = str(self.settings.value("last_view", "simple"))
        if self._pending_first_run or last_view != "advanced":
            self._show_simple()
        else:
            self._show_advanced()

        if self._pending_first_run:
            QTimer.singleShot(0, self._first_run_setup)
        else:
            QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)

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

    def _on_app_state_changed(self, state):
        if state == Qt.ApplicationState.ApplicationActive:
            QTimer.singleShot(150, self.simple_view.maybe_autopaste_clipboard)

    def _open_history(self):
        HistoryDialog(self, self.settings).exec()

    def _on_options_changed(self):
        self.advanced_view.save_options(self.settings)
        self._meta.cookies_browser = self.advanced_view.job_options().cookies_browser

    # ---------- Carpetas ----------
    def _first_run_setup(self):
        dlg = DefaultFoldersConfigDialog(self, dict(self.default_dirs), first_run=True)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.default_dirs = dlg.get_paths()
        save_default_dirs_to_settings(self.settings, self.default_dirs)
        self._refresh_dirs_in_views()
        QApplication.instance().applicationStateChanged.connect(self._on_app_state_changed)

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

    def _folder_for_preset(self, preset: str) -> str:
        folder = self.default_dirs.get(preset, "")
        return folder or suggested_default_dirs().get(preset, os.path.expanduser("~"))

    # ---------- Metadatos ----------
    def _forward_metadata_request(self, url: str, token: int):
        self._meta.latest_token = token
        self.request_metadata.emit(url, token)

    # ---------- Cola ----------
    def _start_from_simple(self, url: str, preset: str):
        job = Job(
            url=url,
            preset=preset,
            folder=self._folder_for_preset(preset),
            options=self.advanced_view.job_options(),
            from_simple=True,
        )
        self._enqueue(job, source_view=self.simple_view)

    def _start_from_advanced(self, url: str, preset: str, folder: str, start_t: str, end_t: str):
        job = Job(url=url, preset=preset, folder=folder, start=start_t, end=end_t, options=self.advanced_view.job_options())
        self._enqueue(job, source_view=self.advanced_view)

    def _enqueue(self, job: Job, source_view=None):
        if not ffmpeg_available():
            (source_view or self.simple_view).show_error(
                "No se encontró ffmpeg, que hace falta para todos los modos. "
                "Usa el botón «Descargar ffmpeg» o instálalo y agrégalo al PATH."
            )
            self._on_ffmpeg_missing()
            return
        self._remember_url(job.url)
        self._queue.append(job)
        if self._job_running:
            self._log_to_advanced(f"➕ Agregado a la cola ({len(self._queue)} pendientes): {job.url}")
        self._refresh_queue_ui()
        if not self._job_running:
            self._start_next()

    def _refresh_queue_ui(self):
        self.advanced_view.set_queue(self._queue, self._current_job if self._job_running else None)
        self.simple_view.set_queue_count(len(self._queue))

    def _remove_queued(self, job_id: int):
        self._queue = [j for j in self._queue if j.id != job_id]
        self._refresh_queue_ui()

    def _clear_queue(self):
        if self._queue:
            self._log_to_advanced(f"🗑️ Cola vaciada ({len(self._queue)} trabajos).")
        self._queue.clear()
        self._refresh_queue_ui()

    def _start_next(self):
        if not self._queue:
            self._finish_batch()
            return
        job = self._queue.pop(0)
        self._retire_current_thread()
        if self._batch is None:
            self._batch = {"total": 0, "ok": 0, "errors": [], "last_path": "", "cancelled": False}
            self._cancel_requested = False
            self.simple_view.set_busy(True)
            self.advanced_view.set_busy(True)
        self._batch["total"] += 1
        self._current_job = job
        job.status = "descargando"
        self._job_running = True
        self._refresh_queue_ui()

        self.thread = QThread()
        self.worker = Worker(job.url, job.folder, job.preset, job.start, job.end, options=job.options)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self._on_worker_log)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.completed.connect(self._on_worker_completed)
        self.worker.error.connect(self._on_worker_error)
        self.worker.playlist_detected.connect(self._on_playlist_detected)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def _retire_current_thread(self):
        thread, worker = self.thread, self.worker
        if thread is None:
            return
        pair = (thread, worker)
        try:
            running = thread.isRunning()
        except RuntimeError:
            running = False  # ya se borró: terminó
        if running:
            self._retiring.add(pair)
            thread.finished.connect(lambda: self._retiring.discard(pair))
        self.thread = self.worker = None

    def _cancel_job(self):
        """Cancela la descarga actual y vacía la cola."""
        if self.worker is not None and self._job_running:
            self._cancel_requested = True
            if self._queue:
                self._log_to_advanced(f"🗑️ Se quitan {len(self._queue)} trabajos de la cola.")
                self._queue.clear()
            self.worker.request_cancel()
            self._log_to_advanced("⏹️ Cancelación solicitada…")
            self._refresh_queue_ui()

    def _on_worker_log(self, msg: str):
        self.advanced_view.append_log(msg)
        append_log_file(msg)

    def _on_worker_progress(self, pct: int, msg: str):
        if self._batch and self._batch["total"] + len(self._queue) > 1:
            msg = f"[{self._batch['total']}/{self._batch['total'] + len(self._queue)}] {msg}"
        self.advanced_view.set_progress(pct, msg)
        self.simple_view.set_progress(pct, msg)

    def _on_worker_completed(self, file_path: str, title: str):
        job = self._current_job
        job.status, job.result_path, job.title = "listo", file_path, title
        self._batch["ok"] += 1
        self._batch["last_path"] = file_path
        add_history(self.settings, title=title, path=file_path, preset=job.preset, url=job.url)

    def _on_worker_error(self, msg: str):
        job = self._current_job
        job.status = "error"
        self._batch["errors"].append((job, msg))
        self.advanced_view.show_error(msg)

    def _on_playlist_detected(self, url: str):
        job = self._current_job
        job.status = "lista"
        self._pending_playlists.append(job)

    def _on_worker_finished(self):
        self._job_running = False
        if self._cancel_requested and self._current_job and self._current_job.status == "descargando":
            self._current_job.status = "cancelado"
            self._batch["cancelled"] = True
        self._current_job = None
        if self._queue and not self._cancel_requested:
            self._start_next()
        else:
            self._finish_batch()
        if self._pending_playlists:
            QTimer.singleShot(0, self._open_next_playlist)

    def _finish_batch(self):
        batch, self._batch = self._batch, None
        self.simple_view.set_busy(False)
        self.advanced_view.set_busy(False)
        self._refresh_queue_ui()
        if batch is None:
            return
        total, ok, errors = batch["total"], batch["ok"], batch["errors"]
        playlists_only = ok == 0 and not errors and not batch["cancelled"]
        if batch["cancelled"] and ok:
            self.advanced_view.show_cancelled()
            self.simple_view.show_success(
                batch["last_path"], f"{ok} de {total} descargas listas; el resto se canceló."
            )
        elif batch["cancelled"]:
            self.advanced_view.show_cancelled()
            self.simple_view.show_cancelled()
        elif playlists_only:
            self.advanced_view.set_progress(0, "Esperando…")
        elif ok == 0:
            msg = errors[-1][1]
            if total > 1:
                msg = f"Fallaron las {total} descargas. Última: {friendly(msg)}"
            self.simple_view.show_error(msg)
            self._notify("Hubo un problema con la descarga.", warning=True)
        else:
            note = ""
            if total > 1:
                note = f"{ok} de {total} descargas listas."
            if errors:
                note += f" {len(errors)} fallaron (detalles en el modo avanzado)."
            self.advanced_view.show_success(batch["last_path"])
            self.simple_view.show_success(batch["last_path"], note.strip())
            self._notify("Descarga lista." if total == 1 else f"{ok} de {total} descargas listas.")

    def _notify(self, text: str, warning: bool = False):
        if self.tray and not self.isActiveWindow():
            self.tray.show()
            icon = QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage("VibeLoader", text, icon, 5000)

    # ---------- Playlists ----------
    def _open_next_playlist(self):
        if not self._pending_playlists:
            return
        job = self._pending_playlists.pop(0)
        self.simple_view.show_notice("Leyendo la lista de reproducción…")

        def work(_task):
            return fetch_metadata(job.url, cookies_browser=job.options.cookies_browser)

        def on_done(data):
            self.simple_view.hide_notice()
            entries = data.get("entries") or []
            if not entries:
                self.simple_view.show_error("No se pudieron leer los videos de esta lista.")
            else:
                self._choose_from_playlist(job, data.get("title") or "", entries)
            if self._pending_playlists:
                QTimer.singleShot(0, self._open_next_playlist)

        def on_failed(msg):
            self.simple_view.hide_notice()
            self.simple_view.show_error(msg)

        self._run_task(work, "lectura de playlist", on_done, on_failed)

    def _choose_from_playlist(self, job: Job, title: str, entries: list):
        dlg = PlaylistDialog(self, title, entries, ADVANCED_PRESETS, job.preset)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        preset = dlg.preset()
        folder = self._folder_for_preset(preset) if job.from_simple else job.folder
        if dlg.use_subfolder() and title:
            folder = os.path.join(folder, windows_safe_video_name(title, max_len=80))
        urls = dlg.selected_urls()
        self._log_to_advanced(f"📃 {len(urls)} videos de «{title}» agregados a la cola → {folder}")
        self._queue.extend(
            Job(url=url, preset=preset, folder=folder, options=job.options, from_simple=job.from_simple)
            for url in urls
        )
        self._refresh_queue_ui()
        if not self._job_running:
            self._start_next()

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

    # ---------- Cierre ----------
    def closeEvent(self, e):
        if self._job_running:
            pendientes = f" y {len(self._queue)} en cola" if self._queue else ""
            r = QMessageBox.question(
                self,
                "Descarga en curso",
                f"Hay una descarga en curso{pendientes}. ¿Cancelar y salir?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self._cancel_job()
        stopped = self._stop_thread(self.thread, 15000) if self._job_running else True
        for thread, _worker in list(self._retiring):
            stopped = self._stop_thread(thread, 3000) and stopped
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
