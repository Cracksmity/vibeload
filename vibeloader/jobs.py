"""Workers en hilos Qt: trabajo de descarga y extractor de metadatos."""
import os
import threading
import traceback

from PySide6.QtCore import QObject, Signal, Slot

from .config import (
    DEFAULT_TARGET_SIZE_MB,
    PRESET_CAR,
    PRESET_CURSOS,
    PRESET_DIRECTO,
    PRESET_MAX,
    PRESET_MP3,
    PRESET_TAMANO,
    PRESET_WHATSAPP,
)
from .errors import UserCancelledError
from .ffmpeg_core import (
    FFMPEG_PROFILE_CAR,
    FFMPEG_PROFILE_CURSOS,
    FFMPEG_PROFILE_TARGET,
    FFMPEG_PROFILE_WHATSAPP,
    convert,
)
from .logs import append_log_file
from .utils import FolderSnapshot, pick_auto_output_path, remove_files
from .ytdlp_core import (
    SPEC_CONVERT_SOURCE,
    SPEC_CONVERT_SOURCE_1080,
    SPEC_DIRECTO,
    SPEC_MAX,
    SPEC_MP3,
    clip_seconds,
    download,
    fetch_metadata,
)

# Presets que bajan una fuente y la procesan con ffmpeg:
# (perfil, fuente, nombre de salida, mensaje final)
CONVERT_PRESETS = {
    PRESET_WHATSAPP: (FFMPEG_PROFILE_WHATSAPP, SPEC_CONVERT_SOURCE, "id", "✨ Listo. Compatible con WhatsApp."),
    PRESET_CAR: (FFMPEG_PROFILE_CAR, SPEC_CONVERT_SOURCE, "title", "✨ Listo. Compatible con autoestéreos."),
    PRESET_CURSOS: (FFMPEG_PROFILE_CURSOS, SPEC_CONVERT_SOURCE, "title", "✨ Listo. Curso comprimido en H.265."),
    PRESET_TAMANO: (FFMPEG_PROFILE_TARGET, SPEC_CONVERT_SOURCE_1080, "title", "✨ Listo. Video comprimido al tamaño pedido."),
}

# Presets que yt-dlp entrega ya terminados.
DIRECT_PRESETS = {
    PRESET_MAX: (SPEC_MAX, "✨ Listo. Video descargado (hasta 1080p, MP4 compatible)."),
    PRESET_DIRECTO: (SPEC_DIRECTO, "✨ Listo. Video 720p descargado sin recodificar."),
    PRESET_MP3: (SPEC_MP3, "✨ Listo. Audio MP3 listo."),
}


class Worker(QObject):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)
    progress = Signal(int, str)
    completed = Signal(str)

    def __init__(
        self,
        url,
        carpeta_salida,
        preset,
        start_time,
        end_time,
        encoder_mode="auto",
        target_mb=DEFAULT_TARGET_SIZE_MB,
    ):
        super().__init__()
        self.encoder_mode = encoder_mode
        self.target_mb = target_mb
        self.url = url
        self.carpeta_salida = carpeta_salida
        self.preset = preset
        self.start_time = start_time
        self.end_time = end_time
        self._cancel_event = threading.Event()
        self._proc_holder = {}
        self._partial_outputs = []

    @Slot()
    def request_cancel(self):
        self._cancel_event.set()
        proc = self._proc_holder.get("p")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def _logger(self, msg):
        self.log.emit(msg)

    def _emit_progress(self, p, msg):
        self.progress.emit(max(0, min(100, int(p))), msg)

    def _run_convert(self):
        profile, spec, naming, done_msg = CONVERT_PRESETS[self.preset]
        # El recorte lo hace ffmpeg en la misma pasada (una sola codificación).
        res = download(
            self.url,
            self.carpeta_salida,
            spec,
            start_time=self.start_time,
            end_time=self.end_time,
            cut_with_ytdlp=False,
            logger=self._logger,
            cancel_event=self._cancel_event,
            emit_progress=self._emit_progress,
            pct_lo=0,
            pct_hi=60,
        )
        info = res.info
        vid = str(info.get("id") or "video").strip()
        if naming == "id":
            output_file = os.path.join(self.carpeta_salida, f"{vid}.mp4")
        else:
            title = (info.get("title") or "video").strip()
            output_file = pick_auto_output_path(self.carpeta_salida, title, vid, res.path)
        if not os.path.exists(output_file):
            self._partial_outputs.append(output_file)
        convert(
            res.path,
            output_file,
            profile,
            clip=clip_seconds(self.start_time, self.end_time),
            encoder_mode=self.encoder_mode,
            target_mb=self.target_mb if self.preset == PRESET_TAMANO else None,
            logger=self._logger,
            emit_progress=self._emit_progress,
            cancel_event=self._cancel_event,
            proc_holder=self._proc_holder,
            pct_lo=61,
            pct_hi=99,
        )
        remove_files([res.path], self._logger)
        self._logger(done_msg)
        return output_file

    def _run_direct(self):
        spec, done_msg = DIRECT_PRESETS[self.preset]
        res = download(
            self.url,
            self.carpeta_salida,
            spec,
            start_time=self.start_time,
            end_time=self.end_time,
            logger=self._logger,
            cancel_event=self._cancel_event,
            emit_progress=self._emit_progress,
            pct_lo=0,
            pct_hi=95,
        )
        self._logger(done_msg)
        return res.path

    @Slot()
    def run(self):
        snapshot = None
        try:
            self._logger("🌐 URL: " + self.url)
            self._logger("📁 Carpeta: " + self.carpeta_salida)
            self._logger(f"🎚 Modo: {self.preset}")
            self._emit_progress(0, "Iniciando…")
            os.makedirs(self.carpeta_salida, exist_ok=True)
            snapshot = FolderSnapshot(self.carpeta_salida)

            if self.preset in CONVERT_PRESETS:
                result_path = self._run_convert()
            elif self.preset in DIRECT_PRESETS:
                result_path = self._run_direct()
            else:
                raise ValueError(f"Preset no reconocido: {self.preset}")

            remove_files(snapshot.leftovers_after_success(result_path), self._logger)
            self._emit_progress(100, "Listo")
            self.completed.emit(result_path)

        except UserCancelledError as e:
            self._logger("⏹️ " + str(e))
            self.progress.emit(0, "Cancelado")
            self._cleanup_failure(snapshot)
        except Exception as e:
            append_log_file(traceback.format_exc())
            self._cleanup_failure(snapshot)
            self.error.emit(str(e))
        finally:
            self.finished.emit()

    def _cleanup_failure(self, snapshot):
        if snapshot is None:
            return
        remove_files(snapshot.leftovers_after_failure(self._partial_outputs), self._logger)


class MetadataFetcher(QObject):
    """Vive en su propio QThread; extrae info sin descargar."""

    fetched = Signal(dict, int)
    failed = Signal(str, int)
    log = Signal(str)

    @Slot(str, int)
    def fetch(self, url: str, token: int):
        if not url:
            return
        try:
            data = fetch_metadata(url, logger=self.log.emit)
        except Exception as e:
            self.failed.emit(str(e), token)
            return
        self.fetched.emit(data, token)
