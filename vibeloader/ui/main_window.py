"""Ventana principal: cabecera, avisos, vistas, cola de trabajos y tareas de fondo."""
import dataclasses
import logging
import os
import sys
import time

from PySide6.QtCore import QEvent, QProcess, QSettings, QThread, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import updater
from ..browsers import browser_display_name, detect_cookie_browser
from ..config import (
    ADVANCED_PRESETS,
    APP_VERSION,
    PRESET_MAX,
    SETTINGS_APP,
    SETTINGS_ORG,
    is_frozen,
    resource_path,
)
from ..errors import (
    ACTION_COOKIES,
    ACTION_FFMPEG,
    ACTION_FOLDER,
    ACTION_UPDATE,
    ACTION_WAIT,
    explain,
)
from ..ffmpeg_core import detect_hw_encoder, encoder_label, ffmpeg_version
from ..history import add_history
from ..jobs import Job
from ..logs import append_log_file, ensure_log_path
from ..settings import (
    load_default_dirs_from_settings,
    save_default_dirs_to_settings,
    suggested_default_dirs,
)
from ..tools import ffmpeg_available, ffmpeg_path, ffprobe_path, local_ffmpeg_dir
from ..utils import windows_safe_video_name
from ..ytdlp_core import fetch_metadata, ytdlp_version
from .advanced_view import AdvancedView
from .dialogs import DefaultFoldersConfigDialog
from .history_dialog import HistoryDialog
from .playlist_dialog import PlaylistDialog
from .qt_bridge import BackgroundTask, JobWorker, MetadataFetcher
from .simple_view import SimpleView
from .styles import THEMES, build_stylesheet
from .widgets import Banner, Header
from .win_integration import (
    TBPF_ERROR,
    TBPF_INDETERMINATE,
    TBPF_NOPROGRESS,
    TBPF_NORMAL,
    TaskbarProgress,
    style_title_bar,
)

THEME_MODES = (("system", "Automático (como Windows)"), ("dark", "Oscuro"), ("light", "Claro"))
WAIT_RETRY_MS = 120_000
FINISHED_STATES = ("listo", "error", "cancelado", "lista")


class MainWindow(QMainWindow):
    request_metadata = Signal(str, int)

    def __init__(self):
        super().__init__()
        ensure_log_path()
        self.settings = QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.setWindowTitle("VibeLoader")
        self.setMinimumSize(720, 540)
        self.setWindowIcon(QIcon(resource_path("assets/icono.ico")))
        geom = self.settings.value("window_geometry")
        if geom is None or not self.restoreGeometry(geom):
            self.resize(860, 640)

        loaded = load_default_dirs_from_settings(self.settings)
        self._pending_first_run = loaded is None
        self.default_dirs = loaded if loaded is not None else suggested_default_dirs()
        self.theme_mode = self._load_theme_mode()
        self.theme = "dark"

        # Cola de trabajos
        self.worker = None
        self.thread = None
        self._job_running = False  # hay un Worker activo
        self._jobs: list[Job] = []  # lo que muestra la cola (incluye terminados)
        self._queue: list[Job] = []  # pendientes
        self._current_job: Job | None = None
        self._cancel_mode = None  # None | "one" | "all"
        self._batch = None  # resumen de la tanda en curso (varios trabajos seguidos)
        self._pending_playlists: list[Job] = []
        self._bg_tasks = set()  # mantiene vivas las BackgroundTask en curso
        # Hilo + worker del trabajo anterior hasta que su hilo termine de cerrarse:
        # si Python suelta la última referencia antes, PySide destruye un QThread
        # en marcha y Qt aborta la app.
        self._retiring = set()
        self._ffmpeg_task = None
        self._hw_label = ""
        self._wait_retry = QTimer(self)
        self._wait_retry.setSingleShot(True)
        self._wait_retry.timeout.connect(self._retry_after_wait)
        self._wait_job: Job | None = None
        self.taskbar = TaskbarProgress()

        self._meta_thread = QThread(self)
        self._meta = MetadataFetcher()
        self._meta.moveToThread(self._meta_thread)
        self.request_metadata.connect(self._meta.fetch)
        self._meta_thread.start()

        # Bandeja para notificaciones
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(self)
            self.tray.setIcon(self.windowIcon())
            self.tray.setToolTip("VibeLoader")

        # Vistas
        self.simple_view = SimpleView(self)
        self.simple_view.last_preset = str(self.settings.value("simple_last_preset", PRESET_MAX))
        self.advanced_view = AdvancedView(self)
        self.advanced_view.set_default_dirs(self.default_dirs)
        self.advanced_view.load_options(self.settings)
        self.advanced_view.options_changed.connect(self._on_options_changed)
        self._on_options_changed()
        self.simple_view.update_folder_hint(self.default_dirs)

        self.header = Header(self._build_menu())
        self.header.mode_changed.connect(lambda i: self._show_advanced() if i else self._show_simple())
        self.header.history_clicked.connect(self._open_history)
        self.banner = Banner()
        self.stack = QStackedWidget()
        self.stack.addWidget(self.simple_view)
        self.stack.addWidget(self.advanced_view)

        root = QWidget()
        root.setObjectName("Root")
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.header)
        banner_wrap = QVBoxLayout()
        banner_wrap.setContentsMargins(16, 10, 16, 0)
        banner_wrap.addWidget(self.banner)
        rl.addLayout(banner_wrap)
        rl.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        # Señales
        sv, av = self.simple_view, self.advanced_view
        sv.request_open_folders.connect(self._open_folders_dialog)
        sv.request_start.connect(self._start_from_simple)
        sv.request_cancel.connect(self._cancel_all)
        sv.request_fetch_metadata.connect(self._forward_metadata_request)
        av.request_open_folders.connect(self._open_folders_dialog)
        av.request_start.connect(self._start_from_advanced)
        av.request_job_action.connect(self._on_job_action)
        av.request_cancel_all.connect(self._cancel_all)
        av.request_clear_finished.connect(self._clear_finished)

        self._meta.fetched.connect(self.simple_view.on_metadata)
        self._meta.failed.connect(self.simple_view.on_metadata_failed)
        self._meta.log.connect(append_log_file)

        hints = QGuiApplication.styleHints()
        if hasattr(hints, "colorSchemeChanged"):
            hints.colorSchemeChanged.connect(lambda _s: self._apply_theme())
        self._apply_theme()

        # Registro de arranque
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
            self._show_ffmpeg_banner()
        else:
            QTimer.singleShot(1500, self._detect_hw_encoder)
        self._refresh_tools_status()

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

        if not self._restore_pending_retry():
            QTimer.singleShot(300, self.simple_view.maybe_autopaste_clipboard)

    # ---------- Menú ⋯ ----------
    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        theme_menu = menu.addMenu("Tema")
        group = QActionGroup(self)
        group.setExclusive(True)
        for key, label in THEME_MODES:
            act = QAction(label, self, checkable=True)
            act.setChecked(key == self.theme_mode)
            act.triggered.connect(lambda _=False, k=key: self._set_theme_mode(k))
            group.addAction(act)
            theme_menu.addAction(act)
        menu.addAction("Carpetas por formato…", self._open_folders_dialog)
        menu.addSeparator()
        menu.addAction("Actualizar el motor de descargas", lambda: self._update_ytdlp(manual=True))
        self.auto_update_act = QAction("Actualizarlo automáticamente", self, checkable=True)
        self.auto_update_act.setChecked(self.settings.value("auto_update_ytdlp", True, type=bool))
        self.auto_update_act.toggled.connect(lambda on: self.settings.setValue("auto_update_ytdlp", bool(on)))
        menu.addAction(self.auto_update_act)
        self.ffmpeg_act = menu.addAction("Instalar ffmpeg", self._install_ffmpeg)
        menu.addSeparator()
        menu.addAction("Abrir carpeta de registros", self._open_log_folder)
        menu.addAction("Acerca de VibeLoader", self._show_about)
        return menu

    def _open_log_folder(self):
        folder = os.path.dirname(ensure_log_path())
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _show_about(self):
        self.banner.show_message(
            f"VibeLoader {APP_VERSION} · motor de descargas yt-dlp {ytdlp_version()} · "
            f"{'ffmpeg instalado' if ffmpeg_available() else 'falta ffmpeg'}",
            kind="info",
        )

    # ---------- Tema ----------
    def _load_theme_mode(self) -> str:
        mode = self.settings.value("theme_mode")
        if mode is None:
            # Quien eligió un tema con el botón anterior lo conserva; el resto sigue a Windows.
            mode = self.settings.value("theme", "system")
        mode = str(mode)
        return mode if mode in ("system", "dark", "light") else "system"

    def _set_theme_mode(self, mode: str):
        self.theme_mode = mode
        self.settings.setValue("theme_mode", mode)
        self._apply_theme()

    def _effective_theme(self) -> str:
        if self.theme_mode in THEMES:
            return self.theme_mode
        hints = QGuiApplication.styleHints()
        scheme = hints.colorScheme() if hasattr(hints, "colorScheme") else Qt.ColorScheme.Unknown
        return "light" if scheme == Qt.ColorScheme.Light else "dark"

    def _apply_theme(self):
        self.theme = self._effective_theme()
        t = THEMES[self.theme]
        QApplication.instance().setStyleSheet(build_stylesheet(self.theme))
        self.header.mark.set_color(t["accent_soft"])
        self._style_title_bar()

    def _style_title_bar(self):
        t = THEMES[self.theme]
        style_title_bar(int(self.winId()), self.theme == "dark", caption=t["bg"], text=t["text"])

    def showEvent(self, e):
        super().showEvent(e)
        self._style_title_bar()
        QTimer.singleShot(0, lambda: self._current_view().url_edit.setFocus())

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.ActivationChange and self.isActiveWindow() and not self._job_running:
            self.taskbar.set_state(int(self.winId()), TBPF_NOPROGRESS)

    # ---------- Navegación ----------
    def _show_simple(self):
        self.stack.setCurrentWidget(self.simple_view)
        self.simple_view.url_edit.setFocus()
        self.header.modes.set_index(0)
        self.settings.setValue("last_view", "simple")

    def _show_advanced(self):
        self.stack.setCurrentWidget(self.advanced_view)
        self.advanced_view.url_edit.setFocus()
        self.header.modes.set_index(1)
        self.settings.setValue("last_view", "advanced")

    def _current_view(self):
        return self.stack.currentWidget()

    def _on_app_state_changed(self, state):
        if state == Qt.ApplicationState.ApplicationActive:
            QTimer.singleShot(150, self.simple_view.maybe_autopaste_clipboard)

    def _open_history(self):
        dlg = HistoryDialog(self, self.settings)
        dlg.exec()
        if dlg.chosen_url:
            self._current_view().set_url(dlg.chosen_url)

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
        self.settings.setValue("simple_last_preset", preset)
        job = Job(
            url=url,
            preset=preset,
            folder=self._folder_for_preset(preset),
            options=self.advanced_view.job_options(),
            from_simple=True,
        )
        self._enqueue(job)

    def _start_from_advanced(self, url: str, preset: str, folder: str, start_t: str, end_t: str):
        job = Job(url=url, preset=preset, folder=folder, start=start_t, end=end_t, options=self.advanced_view.job_options())
        self._enqueue(job)

    def _enqueue(self, job: Job):
        self._wait_retry.stop()
        if not ffmpeg_available():
            self.simple_view.show_error(
                "Falta ffmpeg, el componente que une y convierte los videos.",
                "Instalar ffmpeg",
                self._install_ffmpeg,
            )
            self._show_ffmpeg_banner()
            return
        self._queue.append(job)
        self._jobs.append(job)
        if self._job_running:
            self._log_to_advanced(f"➕ Agregado a la cola ({len(self._queue)} pendientes): {job.url}")
        self._refresh_queue_ui()
        if not self._job_running:
            self._start_next()

    def _refresh_queue_ui(self):
        self.advanced_view.set_queue(self._jobs)
        self.simple_view.set_queue_count(len(self._queue))

    def _on_job_action(self, job_id: int, action: str):
        job = next((j for j in self._jobs if j.id == job_id), None)
        if job is None:
            return
        if action == "cancel" and job is self._current_job:
            self._cancel_current()
        elif action == "remove":
            self._queue = [j for j in self._queue if j.id != job_id]
            self._jobs = [j for j in self._jobs if j.id != job_id]
            self._refresh_queue_ui()
        elif action == "retry":
            self._retry(job)
        elif action == "open" and job.result_path and os.path.exists(job.result_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(job.result_path))

    def _clear_finished(self):
        self._jobs = [j for j in self._jobs if j.status not in FINISHED_STATES]
        self._refresh_queue_ui()

    def _start_next(self):
        if not self._queue:
            self._finish_batch()
            return
        job = self._queue.pop(0)
        self._retire_current_thread()
        if self._batch is None:
            self._batch = {"total": 0, "ok": 0, "errors": [], "last_path": "", "cancelled": False}
            self.simple_view.set_busy(True)
            self.advanced_view.set_busy(True)
            self.taskbar.set_state(int(self.winId()), TBPF_INDETERMINATE)
        self._cancel_mode = None
        self._batch["total"] += 1
        self._current_job = job
        job.status = "descargando"
        job.progress = None
        self._job_running = True
        self._refresh_queue_ui()

        self.thread = QThread()
        self.worker = JobWorker(job)
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

    def _cancel_current(self):
        """Cancela solo la descarga actual; la cola sigue."""
        if self.worker is not None and self._job_running:
            self._cancel_mode = "one"
            self.worker.request_cancel()
            self._log_to_advanced("⏹️ Cancelación solicitada…")

    def _cancel_all(self):
        """Cancela la descarga actual y vacía la cola."""
        if self._queue:
            self._log_to_advanced(f"🗑️ Se quitan {len(self._queue)} trabajos de la cola.")
            ids = {j.id for j in self._queue}
            self._jobs = [j for j in self._jobs if j.id not in ids]
            self._queue.clear()
        if self.worker is not None and self._job_running:
            self._cancel_mode = "all"
            self.worker.request_cancel()
            self._log_to_advanced("⏹️ Cancelación solicitada…")
        self._refresh_queue_ui()

    def _on_worker_log(self, msg: str):
        self.advanced_view.append_log(msg)
        append_log_file(msg)

    def _on_worker_progress(self, info):
        job = self._current_job
        if job is None:
            return
        job.progress = info
        self.advanced_view.update_job(job)
        self.simple_view.set_progress(info)
        self.taskbar.set_state(int(self.winId()), TBPF_NORMAL)
        self.taskbar.set_value(int(self.winId()), max(1, info.pct))

    def _on_worker_completed(self, file_path: str, title: str):
        job = self._current_job
        job.status, job.result_path, job.title = "listo", file_path, title
        self._batch["ok"] += 1
        self._batch["last_path"] = file_path
        add_history(self.settings, title=title, path=file_path, preset=job.preset, url=job.url)

    def _on_worker_error(self, msg: str):
        job = self._current_job
        job.status = "error"
        job.error = msg
        self._batch["errors"].append((job, msg))
        self.advanced_view.append_log("⚠ " + explain(msg)[0])

    def _on_playlist_detected(self, url: str):
        job = self._current_job
        job.status = "lista"
        self._pending_playlists.append(job)

    def _on_worker_finished(self):
        self._job_running = False
        job = self._current_job
        if self._cancel_mode and job and job.status == "descargando":
            job.status = "cancelado"
            self._batch["cancelled"] = True
        if job is not None:
            self.advanced_view.update_job(job)
        self._current_job = None
        if self._queue and self._cancel_mode != "all":
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
        hwnd = int(self.winId())
        self.taskbar.set_state(hwnd, TBPF_NOPROGRESS)
        if batch is None:
            return
        total, ok, errors = batch["total"], batch["ok"], batch["errors"]
        playlists_only = ok == 0 and not errors and not batch["cancelled"]
        if batch["cancelled"] and ok:
            self.simple_view.show_success(batch["last_path"], f"{ok} de {total} listas; el resto se canceló")
        elif batch["cancelled"]:
            self.simple_view.show_cancelled()
        elif playlists_only:
            pass
        elif ok == 0:
            job, msg = errors[-1]
            self._present_error(job, msg, total)
            if not self.isActiveWindow():
                self.taskbar.set_state(hwnd, TBPF_ERROR)
                self.taskbar.set_value(hwnd, 100)
            self._notify("Hubo un problema con la descarga.", warning=True)
        else:
            note = f"{ok} de {total} listas" if total > 1 else ""
            if errors:
                note += f" · {len(errors)} fallaron (míralas en Avanzado)"
            self.simple_view.show_success(batch["last_path"], note.strip(" ·"))
            self._notify("Descarga lista." if total == 1 else f"{ok} de {total} descargas listas.")

    def _notify(self, text: str, warning: bool = False):
        if self.tray and not self.isActiveWindow():
            self.tray.show()
            icon = QSystemTrayIcon.MessageIcon.Warning if warning else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage("VibeLoader", text, icon, 5000)

    # ---------- Errores con acción ----------
    def _present_error(self, job: Job, msg: str, total: int = 1):
        text, action = explain(msg)
        if total > 1:
            text = f"Fallaron las {total} descargas. {text}"
        sv = self.simple_view
        if action == ACTION_COOKIES:
            current = job.options.cookies_browser
            if current:
                sv.show_error(
                    text,
                    "Reintentar",
                    lambda: self._retry(job),
                    note=f"Ya usamos tu sesión de {browser_display_name(current)}: "
                    "inicia sesión en YouTube en ese navegador.",
                )
            else:
                browser = detect_cookie_browser()
                name = browser_display_name(browser)
                note = "" if browser == "firefox" else f"Cierra {name} antes de seguir."
                sv.show_error(text, f"Usar mi sesión de {name}", lambda: self._retry_with_cookies(job, browser), note=note)
        elif action == ACTION_UPDATE:
            sv.show_error(text, "Actualizar y reintentar", lambda: self._update_ytdlp(manual=True, retry_job=job))
        elif action == ACTION_WAIT:
            self._wait_job = job
            self._wait_retry.start(WAIT_RETRY_MS)
            sv.show_error(text, "Reintentar ahora", lambda: self._retry(job), note="Reintentamos solos en 2 minutos.")
        elif action == ACTION_FFMPEG:
            sv.show_error(text, "Instalar ffmpeg", self._install_ffmpeg)
        elif action == ACTION_FOLDER:
            sv.show_error(text, "Elegir carpeta", self._open_folders_dialog)
        elif action:
            sv.show_error(text, "Reintentar", lambda: self._retry(job))
        else:
            sv.show_error(text)

    def _retry(self, job: Job, options=None):
        self._wait_retry.stop()
        self._jobs = [j for j in self._jobs if j.id != job.id]
        self._enqueue(
            Job(
                url=job.url,
                preset=job.preset,
                folder=job.folder,
                start=job.start,
                end=job.end,
                options=options or job.options,
                from_simple=job.from_simple,
            )
        )

    def _retry_with_cookies(self, job: Job, browser: str):
        self.advanced_view.set_cookies_browser(browser)  # guarda la opción vía options_changed
        self._retry(job, dataclasses.replace(job.options, cookies_browser=browser))

    def _retry_after_wait(self):
        job, self._wait_job = self._wait_job, None
        if job is not None and not self._job_running:
            self._retry(job)

    # ---------- Playlists ----------
    def _open_next_playlist(self):
        if not self._pending_playlists:
            return
        job = self._pending_playlists.pop(0)
        self.banner.show_message("Leyendo la lista de reproducción…", closable=False)

        def work(_task):
            return fetch_metadata(job.url, cookies_browser=job.options.cookies_browser)

        def on_done(data):
            self.banner.hide()
            entries = data.get("entries") or []
            if not entries:
                self.simple_view.show_error("No pudimos leer los videos de esta lista.")
            else:
                self._choose_from_playlist(job, data.get("title") or "", entries)
            if self._pending_playlists:
                QTimer.singleShot(0, self._open_next_playlist)

        def on_failed(msg):
            self.banner.hide()
            self._present_error(job, msg)

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
        self._jobs = [j for j in self._jobs if j.id != job.id]
        new = [Job(url=url, preset=preset, folder=folder, options=job.options, from_simple=job.from_simple) for url in urls]
        self._queue.extend(new)
        self._jobs.extend(new)
        self._refresh_queue_ui()
        if not self._job_running:
            self._start_next()

    # ---------- Registro ----------
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

    def _refresh_tools_status(self):
        ff = "ffmpeg ✓" if ffmpeg_available() else "ffmpeg ✗ (falta)"
        if self._hw_label:
            ff += f" · {self._hw_label}"
        self.advanced_view.set_tools_status(f"yt-dlp {ytdlp_version()}  ·  {ff}")
        self.ffmpeg_act.setText("Reinstalar ffmpeg" if ffmpeg_available() else "Instalar ffmpeg")

    def _detect_hw_encoder(self):
        def on_done(enc):
            self._hw_label = encoder_label(enc).split(" (")[0] if enc else "solo CPU"
            self._refresh_tools_status()

        self._run_task(lambda _t: detect_hw_encoder("h264"), "detección de GPU", on_done, lambda _m: None)

    # ---------- ffmpeg ----------
    def _show_ffmpeg_banner(self):
        self.banner.show_message(
            "Falta ffmpeg, el componente que une y convierte los videos. Se descarga una vez "
            "(unos 185 MB) a la carpeta de VibeLoader, sin tocar el sistema.",
            kind="warn",
            button="Instalar ffmpeg",
            action=self._install_ffmpeg,
            closable=False,
        )

    def _install_ffmpeg(self):
        if self._job_running:
            self.banner.show_message("Espera a que termine la descarga en curso para instalar ffmpeg.")
            return
        if self._ffmpeg_task is not None:
            return

        def work(task):
            task.log.emit("⬇️ Descargando ffmpeg…")
            return updater.install_ffmpeg(
                local_ffmpeg_dir(),
                progress=lambda d, t: task.progress.emit(d, t),
                is_cancelled=task.cancel_event.is_set,
            )

        def cancel():
            if self._ffmpeg_task is not None:
                self._ffmpeg_task.cancel_event.set()

        def on_progress(done, total):
            if total:
                self.banner.show_message(
                    f"Descargando ffmpeg… {done >> 20} de {total >> 20} MB",
                    button="Cancelar",
                    action=cancel,
                    closable=False,
                )

        def on_done(name):
            self._ffmpeg_task = None
            self._log_to_advanced(f"✅ ffmpeg instalado ({name}) en {local_ffmpeg_dir()}")
            self._log_to_advanced(f"   {ffmpeg_version()}")
            self.banner.show_message("ffmpeg quedó instalado. Ya puedes descargar.", kind="ok")
            QTimer.singleShot(6000, self.banner.hide)
            self.simple_view.clear_status()
            self._refresh_tools_status()
            self._detect_hw_encoder()

        def on_failed(msg):
            task = self._ffmpeg_task
            self._ffmpeg_task = None
            self._log_to_advanced("❌ " + msg)
            if task is not None and task.cancel_event.is_set():
                self._show_ffmpeg_banner()
            else:
                self.banner.show_message(
                    f"No se pudo descargar ffmpeg: {msg}", kind="error", button="Reintentar", action=self._install_ffmpeg
                )

        self.banner.show_message("Preparando la descarga de ffmpeg…", button="Cancelar", action=cancel, closable=False)
        self._ffmpeg_task = self._run_task(work, "descarga de ffmpeg", on_done, on_failed, on_progress)

    # ---------- yt-dlp ----------
    def _update_ytdlp(self, manual: bool, retry_job: Job | None = None):
        if manual:
            self._log_to_advanced("🔄 Buscando actualización de yt-dlp…")
            self.banner.show_message("Buscando una versión nueva del motor de descargas…", closable=False)

        def work(task):
            log = task.log.emit if manual else append_log_file
            if is_frozen():
                return updater.install_latest_ytdlp(ytdlp_version(), logger=log)
            updater.pip_update_ytdlp(logger=log)
            return "pip"

        def on_done(result):
            self.settings.setValue("ytdlp_last_check", time.time())
            if result:
                version = "" if result == "pip" else f" (yt-dlp {result})"
                self._log_to_advanced(f"✅ yt-dlp{version} listo. Se usará al reiniciar VibeLoader.")
                if retry_job is not None:
                    self._remember_retry(retry_job)
                    self.banner.show_message(
                        "Mejora instalada. Reinicia VibeLoader para reintentar la descarga.",
                        kind="ok",
                        button="Reiniciar y reintentar",
                        action=self._restart_app,
                    )
                else:
                    self.banner.show_message(
                        f"Hay una mejora lista para el motor de descargas{version}. Se aplica al reiniciar.",
                        button="Reiniciar",
                        action=self._restart_app,
                    )
            elif retry_job is not None:
                self.banner.hide()
                self.simple_view.show_error(
                    "El motor de descargas ya está al día. El sitio puede haber cambiado; prueba más tarde.",
                    "Reintentar",
                    lambda: self._retry(retry_job),
                )
            elif manual:
                self.banner.show_message(f"El motor de descargas está al día (yt-dlp {ytdlp_version()}).", kind="ok")
                QTimer.singleShot(5000, self.banner.hide)

        def on_failed(msg):
            self._log_to_advanced("⚠️ No se pudo actualizar yt-dlp: " + msg)
            if manual:
                self.banner.show_message(
                    "No se pudo actualizar el motor de descargas. Revisa tu conexión.",
                    kind="error",
                    button="Reintentar",
                    action=lambda: self._update_ytdlp(manual=True, retry_job=retry_job),
                )

        self._run_task(work, "actualización de yt-dlp", on_done, on_failed)

    def _remember_retry(self, job: Job):
        self.settings.setValue("pending_retry_url", job.url)
        self.settings.setValue("pending_retry_view", "simple" if job.from_simple else "advanced")

    def _restore_pending_retry(self) -> bool:
        """Tras reiniciar por una actualización, deja el enlace listo para reintentar."""
        url = str(self.settings.value("pending_retry_url", "") or "")
        if not url:
            return False
        view = str(self.settings.value("pending_retry_view", "simple"))
        self.settings.remove("pending_retry_url")
        self.settings.remove("pending_retry_view")
        if view == "advanced":
            self._show_advanced()
            self.advanced_view.set_url(url)
        else:
            self._show_simple()
            self.simple_view.set_url(url)
        self.banner.show_message("Motor de descargas actualizado. Tu enlace está listo para reintentar.", kind="ok")
        QTimer.singleShot(8000, self.banner.hide)
        return True

    def _restart_app(self):
        if self._job_running:
            self.banner.show_message("Espera a que termine la descarga en curso para reiniciar.")
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
            self._cancel_all()
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.taskbar.set_state(int(self.winId()), TBPF_NOPROGRESS)
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
