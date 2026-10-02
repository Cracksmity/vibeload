"""Workers en hilos Qt: trabajo de descarga, metadatos y tareas sueltas."""
import itertools
import os
import threading
from dataclasses import dataclass, field

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
from .errors import PlaylistNotSupportedError, UserCancelledError
from .ffmpeg_core import (
    FFMPEG_PROFILE_CAR,
    FFMPEG_PROFILE_CURSOS,
    FFMPEG_PROFILE_TARGET,
    FFMPEG_PROFILE_WHATSAPP,
    can_embed_subtitles,
    convert,
    embed_subtitles,
)
from .logs import log_exception
from .utils import FolderSnapshot, pick_auto_output_path, remove_files
from .ytdlp_core import (
    SPEC_CONVERT_SOURCE,
    SPEC_CONVERT_SOURCE_1080,
    SPEC_DIRECTO,
    SPEC_MAX,
    SPEC_MP3,
    clip_seconds,
    download,
    download_subtitles,
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

SUBS_NONE = "none"
SUBS_SRT = "srt"
SUBS_EMBED = "embed"


@dataclass(frozen=True)
class JobOptions:
    encoder_mode: str = "auto"
    target_mb: float = DEFAULT_TARGET_SIZE_MB
    cookies_browser: str | None = None
    subs_mode: str = SUBS_NONE
    subs_langs: tuple = ("es",)


_job_ids = itertools.count(1)


@dataclass
class Job:
    """Un elemento de la cola."""

    url: str
    preset: str
    folder: str
    start: str = ""
    end: str = ""
    options: JobOptions = field(default_factory=JobOptions)
    id: int = field(default_factory=lambda: next(_job_ids))
    status: str = "en cola"  # en cola | descargando | listo | error | cancelado
    title: str = ""
    result_path: str = ""
    from_simple: bool = False  # la carpeta sale de las predeterminadas de cada modo


class Worker(QObject):
    finished = Signal()
    error = Signal(str)
    log = Signal(str)
    progress = Signal(int, str)
    completed = Signal(str, str)  # ruta, título
    playlist_detected = Signal(str)

    def __init__(self, url, carpeta_salida, preset, start_time, end_time, options: JobOptions | None = None):
        super().__init__()
        self.url = url
        self.carpeta_salida = carpeta_salida
        self.preset = preset
        self.start_time = start_time
        self.end_time = end_time
        self.options = options or JobOptions()
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

    def _check_cancel(self):
        if self._cancel_event.is_set():
            raise UserCancelledError("Cancelado por el usuario")

    def _download(self, spec, cut_with_ytdlp, pct_hi):
        return download(
            self.url,
            self.carpeta_salida,
            spec,
            start_time=self.start_time,
            end_time=self.end_time,
            cut_with_ytdlp=cut_with_ytdlp,
            logger=self._logger,
            cancel_event=self._cancel_event,
            emit_progress=self._emit_progress,
            pct_lo=0,
            pct_hi=pct_hi,
            cookies_browser=self.options.cookies_browser,
        )

    def _fetch_subtitles(self, pct):
        if self.options.subs_mode == SUBS_NONE or self.preset == PRESET_MP3:
            return []
        self._check_cancel()
        self._emit_progress(pct, "Bajando subtítulos…")
        subs = download_subtitles(
            self.url,
            self.carpeta_salida,
            list(self.options.subs_langs),
            logger=self._logger,
            cookies_browser=self.options.cookies_browser,
        )
        self._check_cancel()
        return subs

    def _place_srt_files(self, subs, video_path):
        """Deja los .srt al lado del video: 'Video.es.srt', 'Video.en.srt'."""
        base = os.path.splitext(video_path)[0]
        for path, lang in subs:
            dst = f"{base}.{lang}.srt"
            try:
                os.replace(path, dst)
                self._logger(f"💬 Subtítulos guardados: {os.path.basename(dst)}")
            except OSError as e:
                self._logger(f"⚠️ No se pudo guardar {dst}: {e}")

    def _run_convert(self):
        profile, spec, naming, done_msg = CONVERT_PRESETS[self.preset]
        # El recorte lo hace ffmpeg en la misma pasada (una sola codificación).
        res = self._download(spec, cut_with_ytdlp=False, pct_hi=58)
        info = res.info
        subs = self._fetch_subtitles(59)
        vid = str(info.get("id") or "video").strip()
        if naming == "id":
            output_file = os.path.join(self.carpeta_salida, f"{vid}.mp4")
        else:
            title = (info.get("title") or "video").strip()
            output_file = pick_auto_output_path(self.carpeta_salida, title, vid, res.path)
        if not os.path.exists(output_file):
            self._partial_outputs.append(output_file)
        embed = bool(subs) and self.options.subs_mode == SUBS_EMBED
        convert(
            res.path,
            output_file,
            profile,
            clip=clip_seconds(self.start_time, self.end_time),
            encoder_mode=self.options.encoder_mode,
            target_mb=self.options.target_mb if self.preset == PRESET_TAMANO else None,
            subtitles=subs if embed else (),
            logger=self._logger,
            emit_progress=self._emit_progress,
            cancel_event=self._cancel_event,
            proc_holder=self._proc_holder,
            pct_lo=61,
            pct_hi=99,
        )
        if embed:
            self._logger(f"💬 Subtítulos incrustados: {', '.join(lang for _p, lang in subs)}")
        elif subs:
            self._place_srt_files(subs, output_file)
        remove_files([res.path], self._logger)
        self._logger(done_msg)
        return output_file, info.get("title") or ""

    def _run_direct(self):
        spec, done_msg = DIRECT_PRESETS[self.preset]
        res = self._download(spec, cut_with_ytdlp=True, pct_hi=92)
        subs = self._fetch_subtitles(93)
        if subs:
            if self.options.subs_mode == SUBS_EMBED and can_embed_subtitles(res.path):
                self._emit_progress(96, "Incrustando subtítulos…")
                embed_subtitles(
                    res.path,
                    subs,
                    clip=clip_seconds(self.start_time, self.end_time),
                    logger=self._logger,
                    cancel_event=self._cancel_event,
                    proc_holder=self._proc_holder,
                )
            else:
                self._place_srt_files(subs, res.path)
        self._logger(done_msg)
        return res.path, res.info.get("title") or ""

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
                result_path, title = self._run_convert()
            elif self.preset in DIRECT_PRESETS:
                result_path, title = self._run_direct()
            else:
                raise ValueError(f"Preset no reconocido: {self.preset}")

            remove_files(snapshot.leftovers_after_success(result_path), self._logger)
            self._emit_progress(100, "Listo")
            self.completed.emit(result_path, title)

        except UserCancelledError as e:
            self._logger("⏹️ " + str(e))
            self.progress.emit(0, "Cancelado")
            self._cleanup_failure(snapshot)
        except PlaylistNotSupportedError as e:
            self._logger("📃 " + str(e))
            self.playlist_detected.emit(self.url)
        except Exception as e:
            log_exception(f"Error en el trabajo ({self.preset}) {self.url}")
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
