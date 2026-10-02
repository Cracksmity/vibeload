"""Adaptadores Qt del núcleo: convierten callbacks en señales entre hilos."""
import threading

from PySide6.QtCore import QObject, Signal, Slot

from ..jobs import JobRunner
from ..logs import log_exception
from ..ytdlp_core import fetch_metadata


class JobWorker(QObject):
    """Envuelve un JobRunner; se mueve a un QThread y emite señales hacia la GUI."""

    finished = Signal()
    error = Signal(str)
    log = Signal(str)
    progress = Signal(object)  # ProgressInfo
    completed = Signal(str, str)  # ruta, título
    playlist_detected = Signal(str)

    def __init__(self, job):
        super().__init__()
        self.runner = JobRunner(
            job.url,
            job.folder,
            job.preset,
            job.start,
            job.end,
            job.options,
            on_log=self.log.emit,
            on_progress=self.progress.emit,
            on_completed=self.completed.emit,
            on_error=self.error.emit,
            on_playlist=self.playlist_detected.emit,
            on_finished=self.finished.emit,
        )

    @Slot()
    def run(self):
        self.runner.run()

    def request_cancel(self):
        self.runner.request_cancel()


class MetadataFetcher(QObject):
    """Vive en su propio QThread; extrae info sin descargar."""

    fetched = Signal(dict, int)
    failed = Signal(str, int)
    log = Signal(str)

    def __init__(self):
        super().__init__()
        # Lo escribe el hilo de la GUI antes de pedir; si llegaron varios pedidos
        # seguidos (el usuario pegó varios enlaces), solo se procesa el último.
        self.latest_token = 0
        self.cookies_browser = None

    @Slot(str, int)
    def fetch(self, url: str, token: int):
        if not url or token != self.latest_token:
            return
        try:
            data = fetch_metadata(url, logger=self.log.emit, cookies_browser=self.cookies_browser)
        except Exception as e:
            self.failed.emit(str(e), token)
            return
        self.fetched.emit(data, token)


class BackgroundTask(QObject):
    """Corre fn(task) en un hilo de Python y avisa a la GUI con señales.

    Para tareas sueltas (actualizar yt-dlp, descargar ffmpeg). Las señales se
    emiten desde el hilo y Qt las entrega encoladas en el hilo de la GUI.
    """

    log = Signal(str)
    progress = Signal(object, object)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, name="tarea"):
        super().__init__()
        self._fn = fn
        self._name = name
        self.cancel_event = threading.Event()

    def start(self):
        threading.Thread(target=self._run, name=self._name, daemon=True).start()

    def _run(self):
        try:
            result = self._fn(self)
        except Exception as e:
            log_exception(f"Error en {self._name}")
            self.failed.emit(str(e))
            return
        self.done.emit(result)
